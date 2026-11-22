import subprocess,time,json,os
from pathlib import Path
root=Path(__file__).parent
results=[]
def run(name,sketch='Minimal',explicit=True,extra=()):
 cmd=['arduino-cli','compile','--profile','s3','--jobs','4','--verbose','--no-color']
 if explicit: cmd+=['--build-path',str(root/'build')]
 cmd+=list(extra)+[str(root/sketch)]
 start=time.monotonic(); events=[]
 with (root/(name+'.log')).open('w') as f:
  proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
  for line in proc.stdout:
   elapsed=time.monotonic()-start
   f.write(f'{elapsed:.6f} '+line); events.append((elapsed,line))
  code=proc.wait()
 elapsed=time.monotonic()-start
 def match(s): return [round(t,6) for t,l in events if s in l]
 r=dict(name=name,command=cmd,seconds=round(elapsed,3),exit_code=code,core_compiles=sum('/cores/esp32/' in l and ' -o ' in l and ' -c ' in l and ' -E ' not in l for _,l in events),sketch_compiles=sum('/sketch/' in l and ' -o ' in l and ' -c ' in l and ' -E ' not in l for _,l in events),markers={s:match(s) for s in ['Detecting libraries','Generating function prototypes','Compiling sketch','Compiling libraries','Compiling core','Linking everything','elf2image','merge-bin','Using previously compiled','Using precompiled core']})
 results.append(r);(root/'results.json').write_text(json.dumps(results,indent=2)); print(json.dumps(r),flush=True)
 if code: raise SystemExit(code)
run('explicit_cold')
run('explicit_warm_1')
run('explicit_warm_2')
(root/'Minimal/Minimal.ino').write_text('void setup() {}\nvoid loop() { delay(2); }\n')
run('explicit_edit')
run('explicit_newdir',extra=['--build-path',str(root/'build2')])
run('default_first',explicit=False)
run('default_warm',explicit=False)
(root/'Other').mkdir()
(root/'Other/Other.ino').write_text('void setup() {}\nvoid loop() { delay(1); }\n')
(root/'Other/sketch.yaml').write_text((root/'Minimal/sketch.yaml').read_text())
run('default_other',sketch='Other',explicit=False)
