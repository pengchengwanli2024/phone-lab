#!/usr/bin/env bash
#
# healthcheck.sh — is this machine ready to drive an Android device (and is the
# device actually answering adb)? Idempotent: safe to run any number of times.
#
# Exit codes
#   0  healthy (device present, state=device, screenshot OK, input check ran)
#   1  generic failure (see message)
#   2  adb binary not found
#   3  no device attached (USB debugging off / MTP-only port / cable)
#   4  device present but not authorized (accept the RSA prompt on the phone)
#   5  device authorized but state is offline/other
#   6  screencap failed
#
# Usage
#   ./healthcheck.sh              # normal run, keeps last screenshot under .healthcheck/
#   ./healthcheck.sh --strict-input   # also fail (rc 7) if simulated HOME input
#                                     # cannot be observed to change the screen
#   ADB=/path/to/adb ./healthcheck.sh
#
# Environment
#   ADB        path to adb (default: adb on PATH, then the Homebrew platform-tools path)
#   VIVO       device label used in messages (default: NEX 3 5G)
#   SERIAL     expected device serial; if set, the script requires exactly this serial

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${SCRIPT_DIR}/.healthcheck"
VIVO="${VIVO:-NEX 3 5G}"
STRICT_INPUT=0

for arg in "$@"; do
  case "$arg" in
    --strict-input) STRICT_INPUT=1 ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "healthcheck: unknown argument '$arg' (try --help)" >&2; exit 1 ;;
  esac
done

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
say()   { printf '%s\n' "$*"; }
fail()  { local rc="$1"; shift; red "FAIL: $*"; exit "$rc"; }

# ---------------------------------------------------------------- 1. adb binary
ADB_BIN="${ADB:-}"
if [ -z "$ADB_BIN" ]; then
  if command -v adb >/dev/null 2>&1; then
    ADB_BIN="$(command -v adb)"
  elif [ -x /opt/homebrew/share/android-commandlinetools/platform-tools/adb ]; then
    ADB_BIN=/opt/homebrew/share/android-commandlinetools/platform-tools/adb
  else
    fail 2 "adb not found on PATH and not at the Homebrew platform-tools path. Install Android platform-tools, or run: ADB=/path/to/adb $0"
  fi
fi
[ -x "$ADB_BIN" ] || fail 2 "adb path '$ADB_BIN' is not executable"
say "adb         : $ADB_BIN"
say "adb version : $("$ADB_BIN" version 2>/dev/null | head -1)"

# ------------------------------------------------------- 2. exactly one device
start_server() {
  "$ADB_BIN" start-server >/dev/null 2>&1 || true
}
start_server

list_devices() { "$ADB_BIN" devices -l 2>/dev/null | awk 'NR>1 && NF>0 {print}'; }

DEVICES="$(list_devices)"
COUNT="$(printf '%s\n' "$DEVICES" | grep -c . || true)"

if [ "$COUNT" -eq 0 ]; then
  red "FAIL: no Android device is visible to adb."
  cat <<EOF

  What was expected: a USB-attached phone in state 'device'.
  What to do on the ${VIVO} (this is a DEVICE-side setting, not a host problem):
    1. Settings -> About phone -> tap 'Software version' 7 times
       (vivo: Settings -> 系统管理/关于手机 -> 软件版本信息)
    2. Settings -> Developer options -> turn ON 'USB debugging'
    3. If present, ALSO turn ON the vivo-specific
       'USB debugging (security settings)' / 'USB 调试(安全设置)' /
       'USB模拟点击' — without it vivo silently drops simulated taps.
    4. Replug the USB cable and accept the
       'Allow USB debugging?' RSA fingerprint prompt with 'Always allow'.
  Host-side sanity: the phone must appear as a USB device at all —
    ioreg -p IOUSB -w0 -l | grep -i vivo        # -l is required; properties are hidden without it
    ioreg -p IOUSB -w0 -l | grep -i "${SERIAL:-YOUR_ANDROID_SERIAL}"    # expect the USB serial to show up
EOF
  exit 3
fi

if [ "$COUNT" -gt 1 ]; then
  red "FAIL: $COUNT devices attached, need exactly one."
  say "$DEVICES"
  say "Disconnect extras, or pin one with: SERIAL=<serial> $0"
  exit 1
fi

if [ -n "${SERIAL:-}" ]; then
  # exact first-field comparison: a serial sits at the start of its line, so a
  # "[[:space:]]<serial>[[:space:]]" regex would reject the correct serial.
  printf '%s\n' "$DEVICES" | awk -v s="$SERIAL" '$1==s{f=1} END{exit !f}' \
    || fail 1 "attached device is not the expected serial '$SERIAL': $(printf '%s' "$DEVICES")"
fi

SERIAL_NUM="$(printf '%s\n' "$DEVICES" | awk '{print $1; exit}')"
STATE="$(printf '%s\n' "$DEVICES" | awk '{print $2; exit}')"
say "serial      : $SERIAL_NUM"
say "state       : $STATE"

case "$STATE" in
  device) : ;;
  unauthorized)
    red "FAIL: the phone shows up but is NOT authorized."
    say "Unlock the ${VIVO} and accept the 'Allow USB debugging?' RSA prompt (tick 'Always allow')."
    say "If the prompt never appears: Developer options -> Revoke USB debugging authorizations, then replug."
    exit 4 ;;
  offline)
    red "FAIL: device is 'offline' (adb sees it but cannot talk to it)."
    say "Replug the cable; try: $ADB_BIN kill-server && $ADB_BIN start-server"
    exit 5 ;;
  *)
    red "FAIL: device state is '$STATE', expected 'device'."
    exit 5 ;;
esac

ADBS=("$ADB_BIN" -s "$SERIAL_NUM")
"${ADBS[@]}" wait-for-device >/dev/null 2>&1 || true

# ------------------------------------------------------ 3. identity properties
getprop() { "${ADBS[@]}" shell getprop "$1" 2>/dev/null | tr -d '\r'; }
MODEL="$(getprop ro.product.model)"
MANUF="$(getprop ro.product.manufacturer)"
BRAND="$(getprop ro.product.brand)"
REL="$(getprop ro.build.version.release)"
SDK="$(getprop ro.build.version.sdk)"
FINGER="$(getprop ro.build.fingerprint)"

say "model       : ${MODEL:-<unknown>}"
say "manufacturer: ${MANUF:-<unknown>} (brand ${BRAND:-?})"
say "android     : ${REL:-?} (sdk ${SDK:-?})"
say "fingerprint : ${FINGER:-<unknown>}"

[ -n "$MODEL" ] || fail 1 "getprop ro.product.model returned empty — adb shell is not usable"

# --------------------------------------------------------------- 4. screencap
mkdir -p "$WORK_DIR"
SHOT="$WORK_DIR/screen.png"
: > "$SHOT"
"${ADBS[@]}" exec-out screencap -p > "$SHOT" 2>"$WORK_DIR/screencap.err"
SHOT_BYTES=0
[ -f "$SHOT" ] && SHOT_BYTES=$(wc -c < "$SHOT" | tr -d ' ')
if [ "$SHOT_BYTES" -lt 1000 ]; then
  red "FAIL: screencap produced ${SHOT_BYTES} bytes (expected a PNG)."
  [ -s "$WORK_DIR/screencap.err" ] && say "stderr: $(cat "$WORK_DIR/screencap.err")"
  say "A locked screen still screenshots; a blocked one does not. Unlock the phone and retry."
  exit 6
fi
if ! head -c 8 "$SHOT" | od -An -tx1 | tr -d ' \n' | grep -qi '^89504e47'; then
  fail 6 "screencap output is not a PNG (magic mismatch: $(head -c 8 "$SHOT" | od -An -tx1))"
fi
SIZE="$("${ADBS[@]}" shell wm size 2>/dev/null | tr -d '\r')"
say "screenshot  : $SHOT (${SHOT_BYTES} bytes) ${SIZE:+| $SIZE}"

# ------------------------------------------------- 5. simulated input (HOME key)
hash_of() { shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'; }

BEFORE="$WORK_DIR/before.png"
cp "$SHOT" "$BEFORE"
H1="$(hash_of "$BEFORE")"

# KEYCODE_HOME = 3
"${ADBS[@]}" shell input keyevent 3 >/dev/null 2>&1
INPUT_RC=$?
sleep 1.5
AFTER="$WORK_DIR/after_input.png"
"${ADBS[@]}" exec-out screencap -p > "$AFTER" 2>/dev/null
H2="$(hash_of "$AFTER")"

say "input HOME  : exit=$INPUT_RC, screen $( [ "$H1" = "$H2" ] && echo 'unchanged' || echo 'changed' )"
if [ "$INPUT_RC" -ne 0 ]; then
  yellow "WARN: 'input keyevent 3' exited $INPUT_RC — simulated input is failing on this build."
  yellow "      Enable Developer options -> 'USB debugging (security settings)' / 'USB模拟点击'."
elif [ "$H1" = "$H2" ]; then
  yellow "WARN: screen did not change after KEYCODE_HOME."
  yellow "      Either the phone was already on the home screen, or vivo silently dropped the"
  yellow "      injected event. Confirm by hand, then enable"
  yellow "      Developer options -> 'USB debugging (security settings)' / 'USB模拟点击'."
  if [ "$STRICT_INPUT" -eq 1 ]; then
    red "FAIL: --strict-input requested but simulated input could not be observed."
    exit 7
  fi
else
  green "input       : simulated key event landed (screen changed)"
fi

# ---------------------------------------------------------------- 6. inventory
PKG_COUNT="$("${ADBS[@]}" shell pm list packages 2>/dev/null | tr -d '\r' | grep -c . || true)"
say "packages    : ${PKG_COUNT:-0} reported by pm list packages"

green "OK: $MODEL ($SERIAL_NUM) is online and drivable; adb + screenshot + input checks ran."
say  "Evidence kept in $WORK_DIR (screen.png, before.png, after_input.png)."
exit 0
