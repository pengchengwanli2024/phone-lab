#!/bin/bash
# iPhone helpers that work WITHOUT the developer certificate being trusted
# (CoreDevice/devicectl path). Tap-level control still needs WDA (see README.md).
# usage: iphone.sh <shot|apps|launch|relaunch|info> [args]
set -u
DEV="${IPHONE_UDID:?Set IPHONE_UDID to the target device UDID}"
XC="${XCRUN:-xcrun}"
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
SHOTS="${IOS_SHOTS_DIR:-$SELF_DIR/shots}"
mkdir -p "$SHOTS"
cmd=${1:-}; shift || true
case "$cmd" in
  shot)
    out="$SHOTS/latest.png"
    $XC devicectl device capture screenshot --device "$DEV" --destination "$out" >/dev/null 2>&1 || { echo "screenshot failed"; exit 1; }
    echo "$out"; sips -g pixelWidth -g pixelHeight "$out" 2>/dev/null | tail -2 ;;
  apps)
    $XC devicectl device info apps --device "$DEV" --json-output /tmp/_iphone_apps.json >/dev/null 2>&1
    python3 - <<'PY'
import json
d=json.load(open('/tmp/_iphone_apps.json'))
apps=(d.get('result') or {}).get('apps') or []
for a in sorted(apps, key=lambda x: (x.get('name') or '').lower()):
    print(f"{a.get('bundleIdentifier','?'):55} {a.get('name','?'):28} {a.get('version','')}")
print(f"-- {len(apps)} apps")
PY
    ;;
  launch)   [ $# -ge 1 ] || { echo "usage: iphone.sh launch <bundleId>"; exit 2; }; $XC devicectl device process launch --device "$DEV" "$1" 2>&1 | grep -m1 -E "Launched|error|Error" ;;
  relaunch) [ $# -ge 1 ] || { echo "usage: iphone.sh relaunch <bundleId>"; exit 2; }; $XC devicectl device process launch --terminate-existing --device "$DEV" "$1" 2>&1 | grep -m1 -E "Launched|error|Error" ;;
  info)     $XC devicectl list devices 2>&1 | tail -3 ;;
  *) echo "usage: iphone.sh <shot|apps|launch|relaunch|info> [args]"; exit 2 ;;
esac
