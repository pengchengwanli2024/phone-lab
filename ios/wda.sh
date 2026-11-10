#!/bin/bash
# WebDriverAgent client for the iPhone (tap-level control), WDA 16.x session-scoped API.
# Set WDA_URL for your own forwarded WebDriverAgent endpoint.
set -u
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE="${WDA_URL:-http://127.0.0.1:8100}"
OUT="${IOS_SHOTS_DIR:-$SELF_DIR/shots}"; mkdir -p "$OUT"
_sid() {
  for i in 1 2 3; do
    s=$(curl -s -m 40 -X POST -H 'Content-Type: application/json' -d '{"capabilities":{}}' "$BASE/session" | python3 -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: print(""); raise SystemExit
print(d.get("sessionId") or (d.get("value") or {}).get("sessionId") or "")')
    [ -n "$s" ] && { echo "$s"; return; }; sleep 2
  done; echo ""
}
_end() { curl -s -m 10 -X DELETE "$BASE/session/$1" >/dev/null; }
_show() { python3 -c 'import sys,json
raw=sys.stdin.read()
try: d=json.loads(raw)
except Exception: print(raw[:300]); raise SystemExit
print(json.dumps(d.get("value",d), ensure_ascii=False)[:600])'; }
cmd=${1:-}; shift || true
case "$cmd" in
  status) curl -s -m 15 "$BASE/status" | _show ;;
  url) echo "$BASE" ;;
  shot)
    curl -s -m 30 "$BASE/screenshot" | python3 -c 'import sys,json,base64
d=json.load(sys.stdin); v=d.get("value",d)
if isinstance(v,dict) and "screen" in v: v=v["screen"]
open("'"$OUT"'/wda-latest.png","wb").write(base64.b64decode(v))'
    echo "$OUT/wda-latest.png" ;;
  tree) curl -s -m 40 "$BASE/source?format=json" | python3 -c 'import sys,json
d=json.load(sys.stdin); v=d.get("value",d)
def walk(n,dep=0):
    if isinstance(n,dict):
        t=n.get("type") or ""; nm=n.get("name") or n.get("label") or ""; rid=n.get("rawIdentifier") or ""
        r=n.get("rect") or {}
        if nm or rid: print("  "*dep + f"{t} {nm!r} {rid} rect={r.get(\"x\")},{r.get(\"y\")},{r.get(\"width\")},{r.get(\"height\")}")
        for c in n.get("children") or []: walk(c,dep+1)
walk(v)' | head -80 ;;
  tap)
    S=$(_sid); [ -z "$S" ] && { echo "no session"; exit 1; }
    curl -s -m 70 -X POST -H 'Content-Type: application/json' -d "{\"x\":$1,\"y\":$2}" "$BASE/session/$S/wda/tap" | _show
    _end "$S"; echo "tapped $1,$2" ;;
  swipe)
    S=$(_sid); [ -z "$S" ] && { echo "no session"; exit 1; }
    curl -s -m 70 -X POST -H 'Content-Type: application/json' -d "{\"fromX\":$1,\"fromY\":$2,\"toX\":$3,\"toY\":$4,\"duration\":${5:-0.3}}" "$BASE/session/$S/wda/dragfromtoforduration" | _show
    _end "$S"; echo "swiped $1,$2 -> $3,$4" ;;
  tapxy)  # tap by element rect center from tree: tapxy "text fragment"
    S=$(_sid); [ -z "$S" ] && { echo "no session"; exit 1; }
    X=$(curl -s -m 40 "$BASE/source?format=json" | python3 -c 'import sys,json
d=json.load(sys.stdin); v=d.get("value",d); frag=sys.argv[1]
def walk(n):
    if isinstance(n,dict):
        nm=(n.get("name") or n.get("label") or "")
        if frag in nm and n.get("rect"):
            r=n["rect"]; print(int(r["x"]+r["width"]/2), int(r["y"]+r["height"]/2)); raise SystemExit
        for c in n.get("children") or []: walk(c)
walk(v)' "$1")
    echo "center=$X"; [ -z "$X" ] && { echo "element not found"; _end "$S"; exit 1; }
    curl -s -m 70 -X POST -H 'Content-Type: application/json' -d "{\"x\":${X% *},\"y\":${X#* }}" "$BASE/session/$S/wda/tap" | _show
    _end "$S"; echo "tapped $1" ;;
  launch)
    S=$(_sid); [ -z "$S" ] && { echo "no session"; exit 1; }
    curl -s -m 70 -X POST -H 'Content-Type: application/json' -d "{\"bundleId\":\"$1\"}" "$BASE/session/$S/wda/apps/launch" | _show
    _end "$S" ;;
  apps)
    S=$(_sid); [ -z "$S" ] && { echo "no session"; exit 1; }
    curl -s -m 60 "$BASE/session/$S/wda/apps/list" | _show; _end "$S" ;;
  home)
    S=$(_sid); [ -z "$S" ] && { echo "no session"; exit 1; }
    curl -s -m 60 -X POST -H 'Content-Type: application/json' -d '{}' "$BASE/session/$S/wda/homescreen" | _show; _end "$S" ;;
  *) echo "usage: wda.sh <status|url|shot|tree|tap x y|tapxy 'label'|swipe x1 y1 x2 y2 [d]|launch <bundle>|apps|home>"; exit 2 ;;
esac
