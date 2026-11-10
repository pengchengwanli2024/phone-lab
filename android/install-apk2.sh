#!/bin/bash
# Robust installer for vivo: wraps adb install in a timeout and taps vivo's
# 继续安装 / 完成 / 打开 dialogs while the install is in flight.
set -u
D="$1"; shift
PY="$(dirname "$0")/confirm-install.py"
AAPT=/opt/homebrew/share/android-commandlinetools/build-tools/36.0.0/aapt2
for f in "$@"; do
  pkg=$($AAPT dump badging "$f" 2>/dev/null | sed -n "s/^package: name='\([^']*\)'.*/\1/p")
  echo "=== $(basename "$f") pkg=$pkg size=$(du -h "$f" | cut -f1) $(date +%H:%M:%S)"
  timeout 300 adb -s "$D" install -r "$f" > /tmp/one.log 2>&1 &
  IP=$!
  for i in $(seq 1 300); do
    kill -0 "$IP" 2>/dev/null || break
    sleep 1
    out=$(python3 "$PY" "$D" 2>/dev/null) && echo "   iter$i: $out"
  done
  wait "$IP" 2>/dev/null; echo "   adb: $(tail -1 /tmp/one.log)"
  ver=$(adb -s "$D" shell dumpsys package "$pkg" 2>/dev/null | sed -n 's/.*versionName=\([^ ]*\).*/\1/p' | head -1)
  echo "   -> installed ${ver:-<NONE>}"
done
