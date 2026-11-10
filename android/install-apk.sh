#!/bin/bash
# Install one or more APKs on the vivo, auto-confirming vivo's 继续安装 dialog.
# usage: install-apk.sh <serial> <apk> [apk...]
set -u
D="$1"; shift
PY="$(dirname "$0")/confirm-install.py"
for f in "$@"; do
  pkg=$(/opt/homebrew/share/android-commandlinetools/build-tools/36.0.0/aapt2 dump badging "$f" 2>/dev/null | sed -n "s/^package: name='\([^']*\)'.*/\1/p")
  echo "=== $(basename "$f")  pkg=$pkg  $(du -h "$f" | cut -f1)"
  adb -s "$D" install -r "$f" > /tmp/install-one.log 2>&1 &
  IP=$!
  tapped=""
  for i in $(seq 1 120); do
    kill -0 "$IP" 2>/dev/null || break
    sleep 1
    if [ -z "$tapped" ]; then
      if out=$(python3 "$PY" "$D" 2>/dev/null); then tapped="$out"; echo "   $out (iter $i)"; fi
    fi
  done
  wait "$IP"; rc=$?
  tail -1 /tmp/install-one.log
  if [ -n "$pkg" ]; then
    ver=$(adb -s "$D" shell dumpsys package "$pkg" 2>/dev/null | sed -n 's/.*versionName=\([^ ]*\).*/\1/p' | head -1)
    echo "   installed versionName=${ver:-<not installed>}"
  fi
done
