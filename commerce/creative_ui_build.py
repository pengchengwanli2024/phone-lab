"""Inline the creative module for browser and opaque Harness iframe parity."""
from pathlib import Path
import sys

root=Path(__file__).resolve().parent
target=root/'web/app.js';current=target.read_text()
start,end='/* COMMERCE_CREATIVE_START */','/* COMMERCE_CREATIVE_END */'
block=start+'\n'+(root/'creative_ui.js').read_text().rstrip()+'\n'+end
if start in current:
    before,tail=current.split(start,1);_,after=tail.split(end,1);result=before+block+after
else:result=block+'\n'+current
if '--check' in sys.argv:
    if result!=current:raise SystemExit('Creative UI is stale; run python3 commerce/creative_ui_build.py')
    print('Creative inline module matches its source.')
else:
    if target.read_text()!=current:raise SystemExit('Concurrent UI edit detected; retry.')
    target.write_text(result)
