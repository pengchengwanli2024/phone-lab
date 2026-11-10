#!/usr/bin/env python3
"""Poll the vivo install-confirmation dialog and tap 继续安装 when it appears.
Exit 0 = tapped, 3 = no dialog. Device serial from argv[1]."""
import subprocess, sys, re
D = sys.argv[1]
def sh(*a): return subprocess.run(['adb','-s',D]+list(a),capture_output=True,text=True).stdout
sh('shell','uiautomator','dump','/sdcard/ci.xml')
xml = sh('shell','cat','/sdcard/ci.xml')
for tag in re.findall(r'<node[^>]*>', xml):
    m = re.search(r'text="(继续安装|立即安装|安装)"', tag)
    if not m: continue
    b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
    if not b: continue
    x1,y1,x2,y2 = map(int, b.groups())
    cx, cy = (x1+x2)//2, (y1+y2)//2
    sh('shell','input','tap',str(cx),str(cy))
    print(f"tapped {m.group(1)!r} at ({cx},{cy})")
    sys.exit(0)
sys.exit(3)
