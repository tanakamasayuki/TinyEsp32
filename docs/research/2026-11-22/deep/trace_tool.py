#!/usr/bin/env python3
"""Instrument a real tool, accounting for its CPU time including descendants."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

config = json.loads((Path(__file__).resolve().parent / 'tools.json').read_text())
tool = Path(sys.argv[0]).name
args = config['commands'][tool] + sys.argv[1:]
begin = time.monotonic()
process = subprocess.Popen(args)
_, status, usage = os.wait4(process.pid, 0)
process.returncode = os.waitstatus_to_exitcode(status)
row = dict(tool=tool, args=sys.argv[1:], start=begin, end=time.monotonic(),
           user=usage.ru_utime, system=usage.ru_stime,
           cpu=usage.ru_utime + usage.ru_stime, maxrss_kib=usage.ru_maxrss,
           exit_code=process.returncode)
with open(config['log'], 'a') as stream:
    fcntl.flock(stream, fcntl.LOCK_EX)
    stream.write(json.dumps(row) + '\n')
sys.exit(process.returncode)
