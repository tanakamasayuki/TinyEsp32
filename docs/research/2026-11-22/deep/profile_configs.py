"""Show that command-line CONFIG defines do not reconfigure a prebuilt SDK.

Usage: python3 profile_configs.py COMPILE_COMMANDS_JSON OUTPUT_DIR
"""
import json
from pathlib import Path
import subprocess
import sys

entry = next(e for e in json.loads(Path(sys.argv[1]).read_text()) if '/sketch/' in e['file'])
out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
args = entry['arguments'].copy()
args.remove('-c')
args.remove('-MMD')
args[args.index('-o') + 1] = str(out / 'config-macros.txt')
requested = dict(CONFIG_FREERTOS_HZ=100, CONFIG_BT_NIMBLE_MAX_CONNECTIONS=8,
                 CONFIG_USB_HOST_CONTROL_TRANSFER_MAX_SIZE=8192)
args += ['-E', '-dM'] + [f'-D{name}={value}' for name, value in requested.items()]
process = subprocess.run(args, cwd=entry['directory'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
process.check_returncode()
macros = (out / 'config-macros.txt').read_text().splitlines()
selected = [line for line in macros if any(line.startswith('#define ' + key + ' ') for key in requested)]
result = dict(requested=requested, observed=selected, exit_code=process.returncode, command=args)
(out / 'frozen-config.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
