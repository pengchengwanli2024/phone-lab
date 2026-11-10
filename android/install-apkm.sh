#!/bin/bash
# Install an .apkm/.xapk bundle on an Android device (vivo dialog auto-confirm).
# usage: install-apkm.sh <device-serial> <bundle.apkm> [arch=arm64-v8a] [dpi=xxhdpi]
set -u
DEV=${1:?serial}; APKM=${2:?apkm}; ARCH=${3:-arm64-v8a}; DPI=${4:-xxhdpi}
WORK=$(mktemp -d /tmp/apkm.XXXXXX)
unzip -q -o "$APKM" -d "$WORK" || { echo "unzip failed"; exit 1; }
BASE="$WORK/base.apk"; [ -f "$BASE" ] || BASE=$(ls "$WORK"/*.apk | head -1)
FILES=("$BASE")
for s in "$WORK/split_config.${ARCH}.apk" "$WORK/split_config.${DPI}.apk"; do [ -f "$s" ] && FILES+=("$s"); done
echo "files: ${#FILES[@]}"
SID=$(adb -s "$DEV" shell pm install-create -r -t 2>/dev/null | grep -o '[0-9]\+')
[ -n "$SID" ] || { echo "no session"; exit 1; }
for f in "${FILES[@]}"; do
  n=$(basename "$f")
  adb -s "$DEV" push "$f" "/data/local/tmp/$n" >/dev/null 2>&1
  adb -s "$DEV" shell pm install-write "$SID" "$n" "/data/local/tmp/$n" 2>&1 | tail -1
done
( adb -s "$DEV" shell pm install-commit "$SID" > /tmp/apkm-commit.log 2>&1 ) &
for i in $(seq 1 30); do
  sleep 2
  adb -s "$DEV" shell uiautomator dump /sdcard/_dlg.xml >/dev/null 2>&1
  if adb -s "$DEV" shell cat /sdcard/_dlg.xml 2>/dev/null | grep -q "继续安装"; then
    adb -s "$DEV" shell cat /sdcard/_dlg.xml > /tmp/_dlg.xml
    python3 - <<'PY' > /tmp/_taps
import re
x=open('/tmp/_dlg.xml',encoding='utf-8',errors='ignore').read()
for m in re.finditer(r'<node[^>]*text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', x):
    t=m.group(1); x1,y1,x2,y2=map(int,m.groups()[1:])
    if t.strip() in ('继续安装','已了解应用的风险检测结果'):
        print((x1+x2)//2, (y1+y2)//2)
PY
    while read -r cx cy; do [ -n "${cx:-}" ] && adb -s "$DEV" shell input tap "$cx" "$cy"; sleep 1; done < /tmp/_taps
  fi
done
wait; cat /tmp/apkm-commit.log | tail -2
