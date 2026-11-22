from pathlib import Path
import subprocess,shlex,re,json
root=Path(__file__).parent
commands=[shlex.split(x.split(' ',1)[1]) for x in (root/'explicit_cold.log').read_text().splitlines() if re.match(r'^[0-9.]+ /.*',x)]
cc=next(a for a in commands if any(s.endswith('/sketch/Minimal.ino.cpp') for s in a) and '-E' not in a and '-c' in a)
link=next(a for a in commands if any('Minimal.ino.elf' in s for s in a) and '-o' in a and '-c' not in a and 'g++' in a[0])
src=root/'no_report.cpp';src.write_text('void printBeforeSetupInfo() {}\nvoid printAfterSetupInfo() {}\n')
cc[cc.index('-o')-1]=str(src);cc[cc.index('-o')+1]=str(root/'no_report.o');subprocess.run(cc,check=True)
link[link.index('-o')+1]=str(root/'no_report.elf');link.insert(link.index('-Wl,--start-group')+1,str(root/'no_report.o'))
link=[s.replace(str(root/'build/Minimal.ino.map'),str(root/'no_report.map')) for s in link];subprocess.run(link,check=True)
image=next(a for a in commands if 'elf2image' in a and any(s.endswith('/Minimal.ino.elf') for s in a))
image[image.index('-o')+1]=str(root/'no_report.bin');image[-1]=str(root/'no_report.elf');subprocess.run(image,check=True,stdout=subprocess.DEVNULL)
nm=str(Path(cc[0]).parent/'xtensa-esp32s3-elf-nm')
res={'baseline_bin_bytes':(root/'build/Minimal.ino.bin').stat().st_size,'no_report_bin_bytes':(root/'no_report.bin').stat().st_size}
for label,file in [('baseline','build/Minimal.ino.elf'),('no_report','no_report.elf')]:
 t=subprocess.check_output([nm,'-S','-C',str(root/file)],text=True)
 res[label+'_symbols']=[s for s in t.splitlines() if any(x in s for x in ['printBeforeSetupInfo','String::String','_vfprintf_r','_svfprintf_r','_dtoa_r'])]
(root/'debug_report_probe.json').write_text(json.dumps(res,indent=2)); print(json.dumps(res,indent=2))
