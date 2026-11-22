"""Attribute final allocated input sections in a GNU map to archives/objects.

Usage: python3 profile_map.py LINK_MAP ELF SIZE_TOOL OUTPUT_JSON
Only counts input sections after the discarded-section part of the map.
"""
import collections
import json
from pathlib import Path
import re
import subprocess
import sys

mapping, elf, size_tool, destination = sys.argv[1:]
text = Path(mapping).read_text().split('Linker script and memory map', 1)[1]
allowed = {'.iram0.vectors', '.iram0.text', '.iram0.text_end', '.flash.text',
           '.flash.rodata', '.flash.appdesc', '.eh_frame', '.dram0.data', '.dram0.bss',
           '.iram0.data', '.iram0.bss', '.rtc.text', '.rtc.force_fast', '.rtc.force_slow'}
current = None
pending = False
input_section = ''
objects = collections.defaultdict(collections.Counter)
archives = collections.defaultdict(collections.Counter)
section_sizes = {}
section_addresses = {}
for line in subprocess.check_output([size_tool, '-A', elf], text=True).splitlines():
    match = re.match(r'^(\.\S+)\s+(\d+)\s+(\d+)$', line)
    if match and match.group(1) in allowed:
        section_sizes[match.group(1)] = int(match.group(2))
        section_addresses[match.group(1)] = int(match.group(3))
owners = collections.defaultdict(dict)
for line in text.splitlines():
    match = re.match(r'^(\.\S+)(?:\s|$)', line)
    if match:
        current = match.group(1)
        pending = False
        continue
    if current not in allowed:
        continue
    match = re.match(r'^ (\.\S+)\s*(.*)$', line)
    if match:
        pending = True
        input_section = match.group(1)
        body = match.group(2)
    elif pending:
        body = line.strip()
    else:
        continue
    match = re.match(r'^0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(.+\.(?:a\([^)]*\)|o))$', body)
    if match:
        address, size = int(match.group(1), 16), int(match.group(2), 16)
        obj = match.group(3)
        archive_match = re.search(r'([^/]+\.a)\(', obj)
        archive = archive_match.group(1) if archive_match else Path(obj).name
        # GNU ld reports the whole merged string pool against its first input.
        # Attributing that size to the first object's archive would be false.
        if re.search(r'\.str\d+\.\d+', input_section):
            obj = archive = '<linker string pool>'
        start = section_addresses.get(current, 0)
        end = start + section_sizes.get(current, 0)
        for byte in range(max(address, start), min(address + size, end)):
            owners[current].setdefault(byte, set()).add((obj, archive))
        pending = False
    elif body.startswith('0x'):
        pending = False
for section, addresses in owners.items():
    for candidates in addresses.values():
        objnames = {item[0] for item in candidates}
        arnames = {item[1] for item in candidates}
        obj = next(iter(objnames)) if len(objnames) == 1 else '<merged/shared>'
        archive = next(iter(arnames)) if len(arnames) == 1 else '<merged/shared>'
        objects[obj][section] += 1
        archives[archive][section] += 1
accounted = {section: sum(counts[section] for counts in objects.values()) for section in section_sizes}
assert all(accounted[s] <= section_sizes[s] for s in section_sizes), (section_sizes, accounted)
result = dict(elf_sections=section_sizes, accounted=accounted,
              unattributed={s:section_sizes[s]-accounted[s] for s in section_sizes},
              archives=dict(archives), objects=dict(objects))
Path(destination).write_text(json.dumps(result, indent=2))
for archive, counts in sorted(archives.items(), key=lambda s:sum(s[1].values()), reverse=True)[:20]:
    print(archive, sum(counts.values()), dict(counts))
print('ELF totals', sum(section_sizes.values()), 'accounted', sum(accounted.values()))
