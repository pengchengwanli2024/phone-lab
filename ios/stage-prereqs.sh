#!/usr/bin/env bash
# stage-prereqs.sh — install the two WebDriverAgent prerequisites that need
# neither sudo nor an Apple ID. Safe to re-run (idempotent).
#
#   1) iproxy from libimobiledevice  (host<->device USB port forwarding,
#      host 8100 -> device 8100 WDA control, host 9100 -> device 9100 MJPEG)
#   2) a WebDriverAgent checkout at ~/Library/Caches/dsh-ios/wda/src
#      pinned to the commit the installed plugin was audited against
#      (assets/qa-wda-simulator/source-version.json: cachedCommit)
#
# Why (plugin source): lib/wda-host.js:222 resolveWdaTooling() ->
#   available = projectOk && xcodebuild !== undefined && iproxy !== undefined
# and ensureRunning() throws 'unavailable' when that is false.
# README.md: "a WebDriverAgent checkout at ~/Library/Caches/dsh-ios/wda/src
# (the plugin builds its WebDriverAgentRunner scheme from there — it never
# downloads or clones anything)".
#
# This script only creates files outside ~/phone-lab/ios under the plugin's own
# cache directory and Homebrew's prefix. Nothing here needs sudo.
# Run it, then: ~/phone-lab/ios/healthcheck.sh --all
set -u

WDA_SRC="$HOME/Library/Caches/dsh-ios/wda/src"
WDA_REPO="${WDA_REPO:-https://github.com/appium/WebDriverAgent.git}"
WDA_COMMIT="${WDA_COMMIT:-6e2b5c026f728aed9098481e756b458db87d1272}"   # v16.12.1
PYM="${PYM_PORT:-$HOME/phone-toolkit/venv/bin/pymobiledevice3}"
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"

step() { printf '\n== %s ==\n' "$*"; }
ok()   { printf 'PASS  %s\n' "$*"; }
bad()  { printf 'FAIL  %s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1; }

RC=0

step "1/3  iproxy (libimobiledevice)"
if need iproxy; then
  ok "iproxy already on PATH: $(command -v iproxy)"
else
  if need brew; then
    echo "installing libimobiledevice with Homebrew ($(command -v brew)) ..."
    if brew install libimobiledevice; then
      if need iproxy; then
        ok "iproxy installed: $(command -v iproxy)"
      else
        bad "brew install reported success but iproxy is still not on PATH — check 'brew --prefix libimobiledevice'/bin"
        RC=1
      fi
    else
      bad "brew install libimobiledevice failed — see the Homebrew output above"
      RC=1
    fi
  else
    bad "Homebrew not found; install libimobiledevice by hand so that 'iproxy' is on PATH"
    RC=1
  fi
fi

step "2/3  WebDriverAgent checkout at $WDA_SRC"
mkdir -p "$(dirname "$WDA_SRC")"
if [ -d "$WDA_SRC/WebDriverAgent.xcodeproj" ]; then
  ok "checkout already present: $WDA_SRC/WebDriverAgent.xcodeproj"
  if [ -d "$WDA_SRC/.git" ]; then
    printf '      checked-out revision: %s\n' "$(git -C "$WDA_SRC" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  fi
else
  if [ -e "$WDA_SRC" ]; then
    bad "$WDA_SRC exists but does not contain WebDriverAgent.xcodeproj — move it aside and re-run"
    RC=1
  elif ! need git; then
    bad "git not found; install the Xcode command line tools or git, then re-run"
    RC=1
  else
    echo "cloning $WDA_REPO ..."
    if git clone "$WDA_REPO" "$WDA_SRC"; then
      if git -C "$WDA_SRC" checkout "$WDA_COMMIT"; then
        ok "checked out pinned revision ${WDA_COMMIT:0:12} (appium/WebDriverAgent v16.12.1)"
      else
        bad "clone succeeded but 'git checkout $WDA_COMMIT' failed — keep the clone, the plugin only needs the project, but the audited revision differs"
        RC=1
      fi
    else
      bad "git clone failed — check network access to github.com"
      RC=1
    fi
  fi
fi

step "3/3  re-check"
"$SELF_DIR/healthcheck.sh" --all
RC=$?

if [ "$RC" -eq 0 ]; then
  printf '\nprerequisites staged and all checks pass.\n'
else
  printf '\nprerequisites staged where possible; remaining failures are listed above\n'
  printf '(the sudo/Apple-ID steps are in %s/README.md §A).\n' "$SELF_DIR"
fi
exit "$RC"
