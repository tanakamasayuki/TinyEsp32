"""Instrument actual Arduino CLI tool executions; explicit build path, S3 profile.

Usage: python3 profile_pipeline.py PREVIOUS_SURVEY_DIR NEW_OUTPUT_DIR
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

old = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
root.mkdir(parents=True, exist_ok=True)
sketch = root / 'Minimal'
sketch.mkdir(exist_ok=True)
(sketch / 'Minimal.ino').write_text('void setup() {}\nvoid loop() { delay(1); }\n')
shutil.copyfile(old / 'Minimal/sketch.yaml', sketch / 'sketch.yaml')
props = dict(line.split('=', 1) for line in (old / 'properties.txt').read_text().splitlines() if '=' in line)
tool_dir = root / 'tools'
tool_dir.mkdir(exist_ok=True)
shutil.copyfile(Path(__file__).with_name('trace_tool.py'), tool_dir / 'trace_tool.py')
(tool_dir / 'trace_tool.py').chmod(0o755)
commands = {}
for name in ['xtensa-esp32s3-elf-gcc', 'xtensa-esp32s3-elf-g++',
             'xtensa-esp32s3-elf-gcc-ar', 'xtensa-esp32s3-elf-size']:
    commands[name] = [str(Path(props['compiler.path']) / name)]
commands['esptool'] = [str(Path(props['tools.esptool_py.path']) / 'esptool')]
commands['partition'] = [sys.executable, str(Path(props['runtime.platform.path']) / 'tools/gen_esp32part.py')]
log = root / 'tools.jsonl'
(tool_dir / 'tools.json').write_text(json.dumps(dict(commands=commands, log=str(log))))
for name in commands:
    dest = tool_dir / name
    if not dest.exists():
        dest.symlink_to('trace_tool.py')
base = ['arduino-cli', 'compile', '--profile', 's3', '--jobs', '4', '--verbose', '--no-color',
        '--build-path', str(root / 'build'),
        '--build-property', f'compiler.path={tool_dir}/',
        '--build-property', f'tools.esptool_py.path={tool_dir}',
        '--build-property', f'tools.gen_esp32part.cmd={tool_dir}/partition', str(sketch)]
results = []
for label in ['cold', 'warm_1', 'edit_1', 'warm_2', 'edit_2', 'warm_3', 'edit_3']:
    if label.startswith('edit'):
        value = int(label[-1]) + 1
        (sketch / 'Minimal.ino').write_text(f'void setup() {{}}\nvoid loop() {{ delay({value}); }}\n')
    log.write_text('')
    begin = time.monotonic()
    with (root / (label + '.log')).open('w') as stream:
        process = subprocess.Popen(base, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            stream.write(f'{time.monotonic()-begin:.6f} {line}')
        code = process.wait()
    wall = time.monotonic()-begin
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    for row in rows:
        row['start'] -= begin
        row['end'] -= begin
    result = dict(label=label, wall=wall, exit_code=code, tools=rows)
    results.append(result)
    (root / 'pipeline.json').write_text(json.dumps(results, indent=2))
    print(label, round(wall, 3), 's', len(rows), 'tool calls', flush=True)
    if code or any(row['exit_code'] for row in rows):
        raise RuntimeError((root / (label + '.log')).read_text()[-3000:])
