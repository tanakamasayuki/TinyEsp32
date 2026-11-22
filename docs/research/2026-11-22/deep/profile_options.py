"""Count translation units affected by each build-time option via preprocessing.

Usage: python3 profile_options.py COMPILE_COMMANDS_JSON OUTPUT_DIR
Hash changes are dependency evidence, not necessarily machine-code changes.
"""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

entries = [e for e in json.loads(Path(sys.argv[1]).read_text()) if '/cores/esp32/' in e['file']]
out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
variants = dict(baseline={}, fcpu80={'F_CPU':'80000000L'},
                loop_core0={'ARDUINO_RUNNING_CORE':'0'},
                event_core0={'ARDUINO_EVENT_RUNNING_CORE':'0'},
                debug4={'CORE_DEBUG_LEVEL':'4'},
                cdc1={'ARDUINO_USB_CDC_ON_BOOT':'1'},
                no_global_serial={'NO_GLOBAL_SERIAL':'1'})


def job(task):
    index, name = task
    entry = entries[index]
    args = entry['arguments'].copy()
    args.remove('-c')
    args.remove('-MMD')
    args += ['-E', '-P', '-D__DATE__="Jan 01 2000"', '-D__TIME__="00:00:00"']
    for key, value in variants[name].items():
        args = [a for a in args if not (a == '-D' + key or a.startswith('-D' + key + '='))]
        args += ['-D' + key + '=' + value]
    pp = out / f'{index:02d}_{name}.ii'
    args[args.index('-o') + 1] = str(pp)
    result = subprocess.run(args, cwd=entry['directory'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(entry['file']+' '+name+' '+result.stderr.decode()[-1000:])
    data = pp.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    pp.unlink()
    return dict(file=entry['file'], variant=name, sha256=digest, pp_bytes=len(data))


records = []
tasks = [(i, name) for name in variants for i in range(len(entries))]
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    for row in pool.map(job, tasks):
        records.append(row)
        if len(records) % 60 == 0:
            print(len(records), '/', len(tasks), flush=True)
(out / 'option-raw.json').write_text(json.dumps(records, indent=2))
baseline = {r['file']: r['sha256'] for r in records if r['variant']=='baseline'}
summary = {}
for name in variants:
    changed = [r['file'] for r in records if r['variant']==name and r['sha256']!=baseline[r['file']]]
    summary[name] = dict(defines=variants[name], changed_count=len(changed), changed_files=changed)
(out / 'option-summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
