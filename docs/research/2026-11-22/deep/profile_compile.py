"""Replay compile_commands with per-process CPU accounting and GCC phase reports.

Usage: python3 profile_compile.py COMPILE_COMMANDS_JSON OUTPUT_DIR
Does not change platform, SDK, or the original build directory.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys
import time

database = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
entries = json.loads(database.read_text())
records = []
with_report = '--plain' not in sys.argv[3:]


def measure(args, cwd, prefix):
    begin = time.monotonic()
    with prefix.with_suffix('.stdout').open('wb') as stdout, prefix.with_suffix('.stderr').open('wb') as stderr:
        process = subprocess.Popen(args, cwd=cwd, stdout=stdout, stderr=stderr)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    return dict(wall=time.monotonic() - begin, user=usage.ru_utime,
                system=usage.ru_stime, cpu=usage.ru_utime + usage.ru_stime,
                maxrss_kib=usage.ru_maxrss, exit_code=process.returncode)


def job(task):
    index, repeat = task
    entry = entries[index]
    args = entry['arguments'].copy()
    prefix = out / f'compile_{index:02d}_{repeat}'
    obj = prefix.with_suffix('.o')
    args[args.index('-o') + 1] = str(obj)
    if with_report:
        args += ['-ftime-report']
    result = measure(args, entry['directory'], prefix)
    if result['exit_code']:
        raise RuntimeError(prefix.with_suffix('.stderr').read_text())
    phases = {}
    for line in prefix.with_suffix('.stderr').read_text().splitlines():
        match = re.match(r'^\s*(.*?)\s*:\s*([\d.]+)(?:\s*\([^)]*\))?\s+([\d.]+)(?:\s*\([^)]*\))?\s+([\d.]+)', line)
        if match:
            name, user, system, wall = match.groups()
            phases[name.strip()] = dict(user=float(user), system=float(system),
                                       cpu=float(user) + float(system), wall=float(wall))
    return dict(index=index, repeat=repeat, file=entry['file'], **result,
                object_bytes=obj.stat().st_size, gcc=phases)


tasks = [(index, repeat) for repeat in range(3) for index in range(len(entries))]
random.Random(20261122).shuffle(tasks)
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    for result in pool.map(job, tasks):
        records.append(result)
        (out / 'compile-raw.json').write_text(json.dumps(records, indent=2))
        if len(records) % 20 == 0:
            print(f'{len(records)}/{len(tasks)} complete', flush=True)

summary = []
for index, entry in enumerate(entries):
    samples = [r for r in records if r['index'] == index]
    gcc = {}
    for phase in set().union(*(s['gcc'] for s in samples)):
        gcc[phase] = {key: statistics.median(s['gcc'].get(phase, {}).get(key, 0) for s in samples)
                      for key in ('cpu', 'wall', 'user', 'system')}
    summary.append(dict(file=entry['file'], language=Path(entry['file']).suffix,
                        median_cpu=statistics.median(s['cpu'] for s in samples),
                        median_wall=statistics.median(s['wall'] for s in samples),
                        cpu_samples=[s['cpu'] for s in samples],
                        median_maxrss_kib=statistics.median(s['maxrss_kib'] for s in samples),
                        object_bytes=samples[0]['object_bytes'], gcc=gcc))
summary.sort(key=lambda s: s['median_cpu'], reverse=True)
(out / 'compile-summary.json').write_text(json.dumps(summary, indent=2))
for item in summary[:15]:
    print(f"{item['median_cpu']:.3f} CPU s {Path(item['file']).name}")
