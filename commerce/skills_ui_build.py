"""Inline capability business UI without changing shared generated modules."""
from pathlib import Path
import sys
root=Path(__file__).resolve().parent;target=root/'web/app.js';original=target.read_text()
start,end='/* COMMERCE_SKILLS_START */','/* COMMERCE_SKILLS_END */'
block=start+'\n'+(root/'skills_ui.js').read_text().rstrip()+'\n'+end
if start in original:
    before,tail=original.split(start,1);_,after=tail.split(end,1);result=before+block+after
else:result=block+'\n'+original
if '--check' in sys.argv:
    if result!=original:raise SystemExit('Skill library UI is stale')
    print('Skill library UI matches source.')
else:
    if target.read_text()!=original:raise SystemExit('Concurrent UI edit; retry')
    target.write_text(result)
