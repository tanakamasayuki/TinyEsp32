from pathlib import Path
import subprocess,shlex,time,json,re,statistics
root=Path(__file__).parent
lines=(root/'explicit_cold.log').read_text().splitlines()
commands=[shlex.split(x.split(' ',1)[1]) for x in lines if re.match(r'^[0-9.]+ /.*',x)]
cc=next(a for a in commands if any('/sketch/Minimal.ino.cpp'==s[-len('/sketch/Minimal.ino.cpp'):] for s in a) and '-E' not in a and '-c' in a)
link=next(a for a in commands if any('Minimal.ino.elf' in s for s in a) and '-o' in a and '-c' not in a and 'g++' in a[0])
res={}
def run(name,args,n=3):
 times=[]
 for i in range(n):
  t=time.perf_counter(); p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE); times.append(round(time.perf_counter()-t,4))
  if p.returncode: print(p.stderr.decode()[-2000:]);raise SystemExit(p.returncode)
 res[name]={'seconds':times,'median':statistics.median(times)}
 return p
for name,inc in [('stdint','#include <stdint.h>'),('arduino','#include <Arduino.h>')]:
 src=root/(name+'.cpp');src.write_text(inc+'\nvoid probe(){}\n')
 args=cc.copy();args[args.index('-o')+1]=str(root/(name+'.o'));args[args.index('-o')-1]=str(src)
 pp=args.copy(); pp.remove('-c');pp.remove('-MMD'); pp+=['-E','-H'];pp[pp.index('-o')+1]=str(root/(name+'.ii'))
 p=run(name+'_preprocess',pp)
 res[name+'_preprocess'].update(bytes=(root/(name+'.ii')).stat().st_size,lines=len((root/(name+'.ii')).read_bytes().splitlines()),include_events=sum(bool(re.match(rb'^\.+ ',s)) for s in p.stderr.splitlines()))
 run(name+'_compile',args)
for name,remove in [('link_baseline',False),('link_no_cref',True)]:
 args=link.copy();args[args.index('-o')+1]=str(root/(name+'.elf'))
 args=[a.replace(str(root/'build/Minimal.ino.map'),str(root/(name+'.map'))) for a in args]
 if remove:
  # --cref is inside an SDK response file, so expand and remove only that flag.
  new=[]
  for a in args:
   if a.startswith('@') and Path(a[1:]).is_file():new+=shlex.split(Path(a[1:]).read_text())
   else:new.append(a)
  args=[a for a in new if a!='-Wl,--cref']
 run(name,args)
(root/'inspection.json').write_text(json.dumps(res,indent=2));print(json.dumps(res,indent=2))
