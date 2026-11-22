"""Measure marginal include costs with the same compiler and options.

Usage: python3 profile_headers.py COMPILE_COMMANDS_JSON OUTPUT_DIR
"""
import json
import os
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys
import time

out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
entry = next(e for e in json.loads(Path(sys.argv[1]).read_text()) if '/sketch/' in e['file'])
base = entry['arguments'].copy()
original_core = Path(next(s[2:] for s in base if s.startswith('-I') and s.endswith('/cores/esp32')))
api = Path('/home/mt/dev_wch/ArduinoCore-CH32RV/cores/arduino/api/ArduinoAPI.h')
arduino = (original_core / 'Arduino.h').read_text()
groups = {
    'full': [],
    'without_serial': ['HardwareSerial.h'],
    'without_network': ['IPAddress.h', 'Client.h', 'Server.h', 'Udp.h'],
    'without_esp': ['Esp.h'],
    'without_stl_helpers': ['algorithm', 'cmath'],
    'without_serial_network_esp': ['HardwareSerial.h', 'IPAddress.h', 'Client.h', 'Server.h', 'Udp.h', 'Esp.h', 'freertos_stats.h'],
}
sources = dict(stdint='#include <stdint.h>\n',
               functional='#include <functional>\n',
               algorithm='#include <algorithm>\n',
               freertos='#include <freertos/FreeRTOS.h>\n#include <freertos/task.h>\n',
               hal='#include <esp32-hal.h>\n',
               print_stream='#include <Print.h>\n#include <Stream.h>\n',
               arduino_core_api=f'#include "{api}"\n')
for name, headers in groups.items():
    directory = out / name
    directory.mkdir(exist_ok=True)
    text = arduino
    for header in headers:
        text = re.sub(r'^#include [<"]' + re.escape(header) + r'[>"]\s*$', '', text, flags=re.MULTILINE)
    if name == 'without_stl_helpers':
        text = re.sub(r'^using std::.*?;\s*$', '', text, flags=re.MULTILINE)
    (directory / 'Arduino.h').write_text(text)
    sources[name] = f'#include "{directory}/Arduino.h"\n'
records = []
tasks = [(name, repeat) for repeat in range(5) for name in sources]
random.Random(20261122).shuffle(tasks)
for name, repeat in tasks:
    src = out / (name + '.cpp')
    src.write_text(sources[name] + 'void probe() {}\n')
    args = base.copy()
    args[args.index(entry['file'])] = str(src)
    args[args.index('-o') + 1] = str(out / (name + '.o'))
    prefix = out / f'{name}_{repeat}'
    if '--report' in sys.argv[3:]:
        args += ['-ftime-report']
    begin = time.monotonic()
    with prefix.with_suffix('.stderr').open('wb') as stderr:
        process = subprocess.Popen(args, cwd=entry['directory'], stdout=subprocess.DEVNULL, stderr=stderr)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    records.append(dict(name=name, repeat=repeat, cpu=usage.ru_utime + usage.ru_stime,
                        wall=time.monotonic() - begin, exit_code=process.returncode))
    if process.returncode:
        print(name, prefix.with_suffix('.stderr').read_text()[-1500:])
summary = []
for name in sources:
    samples = [s for s in records if s['name'] == name]
    if any(s['exit_code'] for s in samples):
        summary.append(dict(name=name, failed=True))
        continue
    src = out / (name + '.cpp')
    args = base.copy()
    args[args.index(entry['file'])] = str(src)
    args.remove('-c')
    args.remove('-MMD')
    args[args.index('-o') + 1] = str(out / (name + '.ii'))
    process = subprocess.run(args + ['-E', '-H'], cwd=entry['directory'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    text = (out / (name + '.ii')).read_bytes()
    summary.append(dict(name=name, median_cpu=statistics.median(s['cpu'] for s in samples),
                        median_wall=statistics.median(s['wall'] for s in samples),
                        cpu_samples=[s['cpu'] for s in samples],
                        pp_bytes=len(text), pp_lines=len(text.splitlines()),
                        include_events=sum(bool(re.match(rb'^\.+ ',s)) for s in process.stderr.splitlines())))
(out / 'header-raw.json').write_text(json.dumps(records, indent=2))
(out / 'header-summary.json').write_text(json.dumps(summary, indent=2))
for s in summary:
    print(s['name'], round(s.get('median_cpu', 0), 3), s.get('pp_lines'), s.get('failed', False), flush=True)
