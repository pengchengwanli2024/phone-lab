import sys, json, re, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import wda
print("[1] source (ttl 180s)...", flush=True)
try:
    src = wda._req("GET","/source?format=json",timeout=180).get("value")
except Exception as e:
    print("source failed:", e); sys.exit(2)
els=[]; wda.walk(src, els)
print("[2] elements:", len(els), flush=True)
cands=[e for e in els if re.search(r"(评论|comment|Comment|赞|like|Like|分享|Share|搜索|Search)", e["name"] or "")]
for c in cands[:20]: print("  ", c["type"], repr(c["name"])[:60], c["rect"], flush=True)
json.dump(els, open("/tmp/tt_els.json","w"))
