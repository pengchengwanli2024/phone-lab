#!/usr/bin/env python3
"""Task-scoped control indicator with a heartbeat and fail-closed lease."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local" / "control-monitor"
COMPONENT = "org.phonelab.indicator/.ControlIndicatorService"


class Lease:
    def __init__(self, device, serial=None, key=None):
        self.device, self.serial = device, serial
        self.key = key or device
        if not re.fullmatch(r'[a-z0-9-]{1,64}', self.key):
            raise ValueError('Invalid lease key')
        self.stop_event = threading.Event()
        self.thread = None
        self.error = None

    def _save(self, active):
        entry = {"active": active, "updated": time.time(), "expires": time.time() + 35,
                 "phone_indicator": "native_xctest" if self.device == "ios" else
                     ("unavailable" if self.error else "status_bar")}
        tmp = STATE / (self.key + ".tmp")
        tmp.write_text(json.dumps(entry))
        os.chmod(tmp, 0o600)
        tmp.replace(STATE / (self.key + ".json"))

    def _android(self, start):
        if self.device != "android":
            return
        if not self.serial:
            raise ValueError("An explicit Android serial is required")
        argv = ["adb", "-s", self.serial, "shell", "am",
                "start-foreground-service" if start else "stopservice", "-n", COMPONENT]
        result = subprocess.run(argv, capture_output=True, timeout=12)
        output = result.stdout + result.stderr
        lines = {line.strip() for channel in (result.stdout, result.stderr)
                 for line in channel.splitlines()}
        stop_ok = bool(lines & {b"Service stopped", b"Service not stopped: was not running."})
        if not start and result.returncode in (0, 255) and stop_ok:
            return
        if result.returncode or b"Error" in output:
            raise RuntimeError("Android indicator service unavailable")

    def _heartbeat(self):
        while not self.stop_event.wait(15):
            try:
                self._android(True)
                self.error = None
            except Exception:
                self.error = "indicator_unavailable"
            self._save(True)

    def __enter__(self):
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(STATE, 0o700)
        self.lock = open(STATE / (self.key + ".lock"), "a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("This monitor already has an active controller for the device")
        try:
            self._android(True)
        except Exception:
            self.lock.close()
            raise
        self._save(True)
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)
        try:
            self._android(False)
        finally:
            self._save(False)
            self.lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=["android", "ios"], required=True)
    parser.add_argument("--serial", default=os.environ.get("PHONE_LAB_ANDROID_SERIAL"))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Pass a command after --")
    with Lease(args.device, args.serial):
        raise SystemExit(subprocess.run(command).returncode)


if __name__ == "__main__":
    main()
