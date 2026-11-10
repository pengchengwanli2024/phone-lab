#!/usr/bin/env bash
# healthcheck.sh — ordered readiness checks for driving a PHYSICAL iPhone from
# DeepSeek Harness via the @zseven-w/dsh-ios plugin (ios_sim_devices +
# ios_real_start_wda + WDA-backed ios_sim_* tools).
#
# Every check prints PASS or FAIL. A FAIL prints the ONE action that fixes it.
# Default: stop at the first FAIL and exit non-zero (its 1-based number).
#   ./healthcheck.sh          # stop at first failure
#   ./healthcheck.sh --all    # run every check, summarise, exit 1 if any failed
#
# Facts this script asserts were read from the installed plugin source:
#   lib/devicectl.js  — realDevices come from `xcrun devicectl list devices`
#                       (spawn('xcrun', ...) → xcode-select must point at Xcode)
#   lib/wda-host.js   — resolveWdaTooling() requires
#                         (1) <cache>/wda/src/WebDriverAgent.xcodeproj
#                         (2) xcodebuild on PATH
#                         (3) iproxy on PATH            (iproxy = libimobiledevice)
#                       and ensureRunning() throws 'unavailable' when false.
#                       Tunnel: host 127.0.0.1:8100 -> device 8100 (control),
#                                host 9100 -> device 9100 (MJPEG).
#   README.md         — "a WebDriverAgent checkout at ~/Library/Caches/dsh-ios/wda/src
#                        (the plugin builds its WebDriverAgentRunner scheme from there
#                        — it never downloads or clones anything)"
#
# Overridable: IOS_UDID (target hardware UDID), IOS_XCODE (Xcode.app path),
#              PYM_PORT (pymobiledevice3 binary).
set -u

MACOS_STYLE=0
ALL=0
for arg in "$@"; do
  case "$arg" in
    --all) ALL=1 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 64 ;;
  esac
done

# Target device (iPhone 15 Pro Max, USB product name "iPhone").
TARGET_UDID="${IOS_UDID:?Set IOS_UDID to the target hardware UDID}"
TARGET_UDID_DASHED="$(printf '%s' "$TARGET_UDID" | sed -E 's/^(.{8})(.*)$/\1-\2/')"
XCODE_APP="${IOS_XCODE:-/Applications/Xcode.app}"
XCODE_DEV="$XCODE_APP/Contents/Developer"
WDA_SRC="$HOME/Library/Caches/dsh-ios/wda/src"
WDA_PROJECT="$WDA_SRC/WebDriverAgent.xcodeproj"
WDA_CONTROL_PORT="${WDA_CONTROL_PORT:-8100}"
PYM="${PYM_PORT:-$HOME/phone-toolkit/venv/bin/pymobiledevice3}"

if [ -t 1 ]; then MACOS_STYLE=1; fi
if [ "$MACOS_STYLE" = 1 ]; then
  C_OK=$'\033[32m'; C_BAD=$'\033[31m'; C_WARN=$'\033[33m'; C_OFF=$'\033[0m'
else
  C_OK=''; C_BAD=''; C_WARN=''; C_OFF=''
fi

TMPDIR_HC="$(mktemp -d "${TMPDIR:-/tmp}/ios-healthcheck.XXXXXX")"
cleanup() { rm -rf "$TMPDIR_HC"; }
trap cleanup EXIT HUP INT TERM

N=0
FAILED=0
FAIL_COUNT=0
SUMMARY=""

pass() {
  N=$((N + 1))
  printf '%sPASS%s [%d] %s\n' "$C_OK" "$C_OFF" "$N" "$1"
  SUMMARY="${SUMMARY}PASS [${N}] $1"$'\n'
}

fail() {
  # $1 = what failed, $2 = why (observed output / detail), $3 = single fix action
  N=$((N + 1))
  FAIL_COUNT=$((FAIL_COUNT + 1))
  FAILED=$N
  printf '%sFAIL%s [%d] %s\n' "$C_BAD" "$C_OFF" "$N" "$1"
  [ -n "${2:-}" ] && printf '       observed: %s\n' "$2"
  printf '       fix: %s\n' "$3"
  SUMMARY="${SUMMARY}FAIL [${N}] $1"$'\n'
  if [ "$ALL" = 1 ]; then return 0; fi
  printf '\n%sstopped at the first failing check (run with --all to see every check)%s\n' "$C_WARN" "$C_OFF"
  exit "$N"
}

skip() {
  N=$((N + 1))
  printf '%sSKIP%s [%d] %s\n' "$C_WARN" "$C_OFF" "$N" "$1"
  SUMMARY="${SUMMARY}SKIP [${N}] $1"$'\n'
}

note() { printf '       %s\n' "$1"; }

printf 'iOS real-device healthcheck — %s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')"
printf 'target UDID: %s (devicectl form %s)\n' "$TARGET_UDID" "$TARGET_UDID_DASHED"
printf 'Xcode app:   %s\n\n' "$XCODE_APP"

# ── 1. Xcode installed ──────────────────────────────────────────────────────
if [ -d "$XCODE_DEV" ] && [ -x "$XCODE_APP/Contents/MacOS/Xcode" ]; then
  XCODE_VER="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
    "$XCODE_APP/Contents/Info.plist" 2>/dev/null || echo unknown)"
  pass "Xcode installed at $XCODE_APP (version $XCODE_VER)"
else
  fail "Xcode not found at $XCODE_APP" \
    "missing $XCODE_DEV" \
    "install Xcode 27.x from the App Store (or set IOS_XCODE=/path/to/Xcode.app)"
fi

# ── 2. Xcode license accepted for THIS Xcode version ────────────────────────
PLIST=/Library/Preferences/com.apple.dt.Xcode.plist
AGREED="$(defaults read "$PLIST" IDEXcodeVersionForAgreedToGMLicense 2>/dev/null || echo '<none>')"
AGREED="$(printf '%s' "$AGREED" | tr -d '"')"
if [ "$AGREED" = "$XCODE_VER" ]; then
  pass "Xcode license accepted (IDEXcodeVersionForAgreedToGMLicense=$AGREED == Xcode $XCODE_VER)"
else
  fail "Xcode license NOT accepted for Xcode $XCODE_VER" \
    "IDEXcodeVersionForAgreedToGMLicense=${AGREED} in $PLIST; xcrun exits 69: \"You have not agreed to the Xcode license agreements\"" \
    "HUMAN, in Terminal: sudo xcodebuild -license accept"
fi

# ── 3. xcrun resolves Xcode tooling the way the DSH Host sees it ─────────────
# What matters is the bare `xcrun` the plugin spawns — NOT `xcode-select -p`.
# The running DSH Host can carry a stale DEVELOPER_DIR that overrides the
# xcode-select link (exactly what happened on this machine; fixed with a
# /opt/homebrew/bin/xcrun shim that forces DEVELOPER_DIR to Xcode).
SEL="$(xcode-select -p 2>&1 || true)"
XCRUN_PATH="$(command -v xcrun 2>/dev/null || echo '<none>')"
XCRUN_NOTE=""
if [ "$XCRUN_PATH" = "/opt/homebrew/bin/xcrun" ]; then
  XCRUN_NOTE=" (shim: forces DEVELOPER_DIR=$XCODE_DEV; rm /opt/homebrew/bin/xcrun reverts to /usr/bin/xcrun)"
fi
SIM_RC=0
DEV_XC_RC=0
xcrun simctl list devices >"$TMPDIR_HC/simctl.out" 2>&1 || SIM_RC=$?
xcrun devicectl list devices >"$TMPDIR_HC/devicectl.out" 2>&1 || DEV_XC_RC=$?
if [ "$SIM_RC" -eq 0 ] && [ "$DEV_XC_RC" -eq 0 ]; then
  pass "xcrun reaches Xcode tooling as the Host sees it: simctl rc=0, devicectl rc=0 via $XCRUN_PATH$XCRUN_NOTE"
  note "informational: xcode-select -p = $SEL"
else
  ERRS="$(tr '\n' ' ' <"$TMPDIR_HC/simctl.out" | cut -c1-160) | $(tr '\n' ' ' <"$TMPDIR_HC/devicectl.out" | cut -c1-160)"
  fail "xcrun does not reach Xcode tooling (simctl rc=$SIM_RC, devicectl rc=$DEV_XC_RC)" \
    "$ERRS" \
    "HUMAN: sudo xcode-select -s $XCODE_DEV; if xcode-select is already right but the Host inherits a stale DEVELOPER_DIR, add the /opt/homebrew/bin/xcrun shim (export DEVELOPER_DIR=$XCODE_DEV; exec /usr/bin/xcrun \"\$@\") or restart the DSH Host"
fi

# ── 4. devicectl sees the phone (needs checks 2+3) ──────────────────────────
# The plugin spawns a BARE `xcrun` (lib/devicectl.js) so this exact call is what
# ios_sim_devices / ios_real_start_wda will run.
dev_record() {
  # $1 = devicectl JSON path; prints one TAB-separated row for the target device
  python3 - "$1" "$TARGET_UDID_DASHED" <<'PY' 2>/dev/null || true
import json, sys
path, want = sys.argv[1], sys.argv[2].lower()
try:
    doc = json.load(open(path))
except Exception:
    sys.exit(0)
for dev in doc.get("result", {}).get("devices", []):
    hw = dev.get("hardwareProperties", {}) or {}
    udid = (hw.get("udid") or "").lower()
    ident = (dev.get("identifier") or "")
    if (udid == want or ident.lower() == want or want in udid or want in ident.lower()
            or want.replace("-", "") in (udid + ident).replace("-", "").lower()):
        dp = dev.get("deviceProperties", {}) or {}
        cp = dev.get("connectionProperties", {}) or {}
        tunnel = str(cp.get("tunnelState") or "unknown")
        pairing = str(cp.get("pairingState") or "unknown")
        # same derivation as the plugin's deriveState() (lib/devicectl.js)
        state = "unavailable" if tunnel == "unavailable" else ("available (paired)" if pairing == "paired" else "available")
        print("\t".join([
            dp.get("name") or "?",
            hw.get("udid") or "?",
            pairing,
            str(cp.get("transportType") or "unknown"),
            str(dp.get("developerModeStatus") or "unknown"),
            str(dp.get("osVersionNumber") or "?"),
            ident or "?",
            tunnel,
            state,
        ]))
        break
PY
}
set_device_fields() {
  D_NAME="$(printf '%s' "$1" | cut -f1)"
  D_UDID="$(printf '%s' "$1" | cut -f2)"
  D_PAIR="$(printf '%s' "$1" | cut -f3)"
  D_TRANS="$(printf '%s' "$1" | cut -f4)"
  D_DEVMODE="$(printf '%s' "$1" | cut -f5)"
  D_OS="$(printf '%s' "$1" | cut -f6)"
  D_TUNNEL="$(printf '%s' "$1" | cut -f8)"
  D_STATE="$(printf '%s' "$1" | cut -f9)"
}

DEV_JSON="$TMPDIR_HC/devices.json"
DEV_ERR="$TMPDIR_HC/devices.err"
DEV_INFO=""
D_NAME=""; D_UDID=""; D_PAIR=""; D_TRANS=""; D_DEVMODE=""; D_OS=""; D_TUNNEL=""; D_STATE=""
xcrun devicectl list devices --json-output "$DEV_JSON" --log-output "$TMPDIR_HC/devices.log" \
  >/dev/null 2>"$DEV_ERR"
DEV_RC=$?
if [ "$DEV_RC" -ne 0 ] || [ ! -s "$DEV_JSON" ]; then
  ERRTXT="$(tr '\n' ' ' <"$DEV_ERR" | cut -c1-300)"
  case "$ERRTXT" in
    *"not agreed to the Xcode license"*)
      FIX="HUMAN: sudo xcodebuild -license accept (then re-run this script)" ;;
    *"unable to find utility"*|*"not a developer tool"*)
      FIX="HUMAN: sudo xcode-select -s $XCODE_DEV (then re-run this script)" ;;
    *)
      FIX="run: xcrun devicectl list devices   # and fix the error it prints" ;;
  esac
  # Informational fallback: the bundled devicectl binary bypasses the xcrun shim,
  # so the device state can still be reported while check 4 stays FAILED.
  DIRECT="$XCODE_DEV/usr/bin/devicectl"
  DIRECT_JSON="$TMPDIR_HC/devices-direct.json"
  if [ -x "$DIRECT" ]; then
    DEVELOPER_DIR="$XCODE_DEV" "$DIRECT" list devices --json-output "$DIRECT_JSON" \
      --log-output "$TMPDIR_HC/devices-direct.log" >/dev/null 2>&1 || true
    if [ -s "$DIRECT_JSON" ]; then
      DEV_INFO="$(dev_record "$DIRECT_JSON")"
    fi
  fi
  if [ -n "$DEV_INFO" ]; then
    set_device_fields "$DEV_INFO"
    fail "xcrun devicectl list devices failed (exit $DEV_RC) — this IS what the ios_* tools run" \
      "$ERRTXT; direct binary bypass reported: $D_NAME ($D_UDID) pairing=$D_PAIR transport=$D_TRANS devMode=$D_DEVMODE iOS=$D_OS" \
      "$FIX"
  else
    fail "xcrun devicectl list devices failed (exit $DEV_RC)" "$ERRTXT" "$FIX"
  fi
else
  DEV_INFO="$(dev_record "$DEV_JSON")"
  if [ -n "$DEV_INFO" ]; then
    set_device_fields "$DEV_INFO"
    pass "devicectl sees the phone: $D_NAME ($D_UDID) iOS $D_OS transport=$D_TRANS pairing=$D_PAIR devMode=$D_DEVMODE"
  else
    fail "devicectl does not list the target phone $TARGET_UDID_DASHED" \
      "devices seen: $(python3 - "$DEV_JSON" <<'PY' 2>/dev/null || echo '<unparsable>'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    print('<unparsable>'); raise SystemExit
rows = []
for d in doc.get("result", {}).get("devices", []):
    hw = d.get("hardwareProperties", {}) or {}
    rows.append("%s/%s" % (d.get("deviceProperties", {}).get("name"), hw.get("udid")))
print(", ".join(rows) or "<none>")
PY
)" \
      "plug the iPhone in over USB with a DATA cable, unlock it, then re-run"
  fi
fi

# ── 5. Pairing / "Trust This Computer" ──────────────────────────────────────
if [ -z "$DEV_INFO" ]; then
  skip "pairing state unknown until devicectl works (checks 2-4)"
elif [ "$D_PAIR" = "paired" ]; then
  pass "device pairing state: paired (\"Trust This Computer\" was confirmed)"
else
  fail "device is NOT paired (pairingState=$D_PAIR)" \
    "a fresh USB connection requires the on-device Trust prompt; without pairing every devicectl device command fails with 'The device must be paired before it can be connected.'" \
    "HUMAN: unlock the iPhone, tap \"Trust\" on \"Trust This Computer?\", enter the passcode, then re-run"
fi

# ── 6. iOS Developer Mode enabled ───────────────────────────────────────────
# devicectl reports deviceProperties.developerModeStatus once it can read it
# ("enabled"/"disabled"); when the field is absent fall back to AMFI over
# lockdown (`pymobiledevice3 amfi developer-mode-status`), which is
# authoritative while the phone is paired. Developer Mode is what lets
# devicectl start its developer tunnel: with it off, tunnelState stays
# "unavailable", the plugin's deriveState() reports state "unavailable", and
# ios_sim_list_apps / ios_sim_processes / ios_real_start_wda all refuse.
DEVMODE_STATE="$(printf '%s' "${D_DEVMODE:-unknown}" | tr '[:upper:]' '[:lower:]')"
DEVMODE_SOURCE="devicectl"
if [ "$DEVMODE_STATE" != "enabled" ] && [ "$DEVMODE_STATE" != "disabled" ]; then
  if [ -x "$PYM" ]; then
    AMFI_RAW="$("$PYM" amfi developer-mode-status 2>/dev/null | tr -d '[:space:]' | tail -c 8)"
    case "$AMFI_RAW" in
      true|True|TRUE|1) DEVMODE_STATE="enabled"; DEVMODE_SOURCE="pymobiledevice3 amfi" ;;
      false|False|FALSE|0) DEVMODE_STATE="disabled"; DEVMODE_SOURCE="pymobiledevice3 amfi" ;;
    esac
  fi
fi
if [ -z "$DEV_INFO" ]; then
  skip "Developer Mode unknown until devicectl works (checks 3-4)"
elif [ "$DEVMODE_STATE" = "enabled" ]; then
  pass "iOS Developer Mode is enabled (source: $DEVMODE_SOURCE)"
else
  fail "iOS Developer Mode is DISABLED (source: $DEVMODE_SOURCE)" \
    "developerModeStatus=$D_DEVMODE tunnelState=$D_TUNNEL derivedState=$D_STATE; devicectl's tool errors read \"failed because Developer Mode is disabled on the device\"" \
    "HUMAN on the iPhone: Settings -> Privacy & Security -> Developer Mode -> On -> Restart (the phone reboots), keep it unlocked, then re-run"
fi

# ── 7. usbmux sees the phone (works WITHOUT trust) ──────────────────────────
if [ ! -x "$PYM" ]; then
  fail "pymobiledevice3 not found at $PYM" \
    "needed for the independent usbmux view (no trust required)" \
    "activate the toolkit venv or set PYM_PORT=/path/to/pymobiledevice3"
fi
if "$PYM" usbmux list >"$TMPDIR_HC/usbmux.json" 2>"$TMPDIR_HC/usbmux.err"; then
  if grep -qi "$(printf '%s' "$TARGET_UDID_DASHED" | tr 'A-F' 'a-f')" "$TMPDIR_HC/usbmux.json" \
     || grep -qi "$(printf '%s' "$TARGET_UDID" | tr 'A-F' 'a-f')" "$TMPDIR_HC/usbmux.json"; then
    pass "pymobiledevice3 usbmux sees the phone at USB level (no trust needed)"
  else
    fail "pymobiledevice3 usbmux list runs but does not contain $TARGET_UDID_DASHED" \
      "usbmux output: $(tr '\n' ' ' <"$TMPDIR_HC/usbmux.json" | cut -c1-300)" \
      "reconnect the USB cable / try another USB-C data cable"
  fi
else
  fail "pymobiledevice3 usbmux list failed" \
    "$(tr '\n' ' ' <"$TMPDIR_HC/usbmux.err" | cut -c1-300)" \
    "check the cable/port; run: $PYM usbmux list"
fi

# ── 8. Apple Development signing identity (needed by WDA) ───────────────────
IDENT_OUT="$TMPDIR_HC/identities.txt"
security find-identity -v -p codesigning >"$IDENT_OUT" 2>&1
IDENT_COUNT="$(grep -c 'Apple Development' "$IDENT_OUT" || true)"
if [ "$IDENT_COUNT" -ge 1 ]; then
  IDENT_LINE="$(grep 'Apple Development' "$IDENT_OUT" | head -1 | sed -E 's/^[[:space:]]*//')"
  TEAM="$(printf '%s' "$IDENT_LINE" | sed -nE 's/.*\(([0-9A-Z]{10})\)".*/\1/p')"
  CN="$(printf '%s' "$IDENT_LINE" | sed -nE 's/.*"(Apple Development[^"]*)".*/\1/p')"
  CERT_OU=""
  if [ -n "$CN" ]; then
    CERT_OU="$(security find-certificate -c "$CN" -p ~/Library/Keychains/login.keychain-db 2>/dev/null \
      | openssl x509 -noout -subject 2>/dev/null | sed -nE 's/.*OU=([0-9A-Z]{10}).*/\1/p')"
  fi
  pass "Apple Development signing identity present (${IDENT_COUNT}); team-in-name=${TEAM:-<none>}; cert-OU=${CERT_OU:-<unknown>}"
  note "identity: $IDENT_LINE"
  if [ -n "$CERT_OU" ] && [ -n "$TEAM" ] && [ "$CERT_OU" != "$TEAM" ]; then
    note "WARNING: the plugin derives the team from the name parentheses ($TEAM) but the provisioning team is the cert OU ($CERT_OU) — the plugin's build fails with: No Account for Team $TEAM. Set DSHPLUGIN_IOS_TEAM_ID=$CERT_OU (and DSHPLUGIN_IOS_WDA_BUNDLE_ID=<unique>) in the DSH Host environment."
  fi
else
  fail "no Apple Development signing identity in the login keychain" \
    "$(grep -v '^ *$' "$IDENT_OUT" | tr '\n' ' ' | cut -c1-300)" \
    "HUMAN: Xcode -> Settings (Cmd-,) -> Accounts -> + -> Apple ID -> sign in, then Manage Certificates -> + -> Apple Development (a free Apple ID is enough)"
fi

# ── 9. WDA tooling the plugin requires (checkout + xcodebuild + iproxy) ─────
TOOLING_DETAIL=""
if [ -d "$WDA_PROJECT" ]; then
  TOOLING_DETAIL="checkout=ok"
else
  TOOLING_DETAIL="checkout=MISSING ($WDA_PROJECT)"
fi
if command -v xcodebuild >/dev/null 2>&1; then
  TOOLING_DETAIL="$TOOLING_DETAIL; xcodebuild=$(command -v xcodebuild)"
else
  TOOLING_DETAIL="$TOOLING_DETAIL; xcodebuild=MISSING"
fi
if command -v iproxy >/dev/null 2>&1; then
  TOOLING_DETAIL="$TOOLING_DETAIL; iproxy=$(command -v iproxy)"
else
  TOOLING_DETAIL="$TOOLING_DETAIL; iproxy=MISSING"
fi
IPROXY_PATH="$(command -v iproxy 2>/dev/null || true)"
IPROXY_NOTE=""
if [ -n "$IPROXY_PATH" ]; then
  # A pymobiledevice3-backed shim (installed while the Xcode licence blocked
  # `brew install libimobiledevice`) works for the plugin's positional call
  # `iproxy <local> <device> <udid>`, but it needs the venv binary and is not a
  # real libimobiledevice iproxy. Detect it so the output says which one it is.
  if head -5 "$IPROXY_PATH" 2>/dev/null | grep -q "pymobiledevice3" || grep -q "phone-lab/bin/iproxy" <<EOF
$(readlink "$IPROXY_PATH" 2>/dev/null)
EOF
  then
    IPROXY_NOTE=" (pymobiledevice3 shim -> $(readlink "$IPROXY_PATH" 2>/dev/null || echo "$IPROXY_PATH"))"
  fi
fi
# The plugin builds the scheme `WebDriverAgentRunner` from that project
# (wda-host.js WDA_SCHEME), so prove the project actually offers it instead of
# only checking that the directory exists.
TOOLING_OK=1
TOOLING_NOTE=""
if [ -d "$WDA_PROJECT" ] && command -v xcodebuild >/dev/null 2>&1 && command -v iproxy >/dev/null 2>&1; then
  if [ "$AGREED" = "$XCODE_VER" ]; then
    XCB_LIST="$(DEVELOPER_DIR="$XCODE_DEV" xcodebuild -project "$WDA_PROJECT" -list 2>&1 || true)"
    if printf '%s' "$XCB_LIST" | grep -q "WebDriverAgentRunner$"; then
      TOOLING_NOTE="; scheme WebDriverAgentRunner ok"
      TOOLING_DETAIL="$TOOLING_DETAIL; WDA source $(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$WDA_SRC/WebDriverAgentLib/Info.plist" 2>/dev/null || echo '?')"
    else
      TOOLING_NOTE="; scheme WebDriverAgentRunner MISSING — 'xcodebuild -project <WDA_PROJECT> -list' failed or the project is incomplete"
      TOOLING_OK=0
    fi
  else
    TOOLING_NOTE="; scheme not checked (Xcode licence not accepted yet)"
    TOOLING_OK=0
  fi
else
  TOOLING_OK=0
fi
if [ "$TOOLING_OK" -eq 1 ]; then
  pass "WDA tooling usable [$TOOLING_DETAIL]$IPROXY_NOTE$TOOLING_NOTE"
else
  fail "WDA tooling incomplete (ios_real_start_wda would fail 'unavailable')" \
    "$TOOLING_DETAIL$IPROXY_NOTE$TOOLING_NOTE" \
    "put a complete WebDriverAgent checkout at $WDA_SRC with the WebDriverAgentRunner scheme (plugin never clones it) AND install iproxy (libimobiledevice, e.g. brew install libimobiledevice)"
fi

# ── 10. WDA answering on the host control port ──────────────────────────────
WDA_STATUS="$TMPDIR_HC/wda-status.json"
if curl -fsS -m 4 "http://127.0.0.1:${WDA_CONTROL_PORT}/status" -o "$WDA_STATUS" 2>"$TMPDIR_HC/curl.err"; then
  if grep -q '"state"' "$WDA_STATUS" 2>/dev/null; then
    pass "WebDriverAgent answers on 127.0.0.1:${WDA_CONTROL_PORT}/status"
    note "$(cut -c1-200 "$WDA_STATUS")"
  else
    pass "something answers on 127.0.0.1:${WDA_CONTROL_PORT} (not clearly WDA /status)"
    note "$(cut -c1-200 "$WDA_STATUS")"
  fi
else
  fail "WebDriverAgent is not answering on 127.0.0.1:${WDA_CONTROL_PORT}" \
    "curl: $(tr '\n' ' ' <"$TMPDIR_HC/curl.err" | cut -c1-200)" \
    "in the DSH conversation run the tool: ios_real_start_wda(udid=\"${D_UDID:-$TARGET_UDID_DASHED}\")"
fi

printf '\n'
if [ "$FAIL_COUNT" -eq 0 ]; then
  printf '%sALL CHECKS PASSED%s — the phone is ready for ios_sim_devices / ios_real_start_wda.\n' "$C_OK" "$C_OFF"
  exit 0
fi
printf '%s%d check(s) failed%s\n' "$C_BAD" "$FAIL_COUNT" "$C_OFF"
exit 1
