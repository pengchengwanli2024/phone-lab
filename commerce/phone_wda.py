"""Local WebDriverAgent lifecycle for one paired iPhone.

WDA is started from the already-built private runner; no source checkout or
network download is required. The manager keeps xcodebuild and the usbmux
forwarder alive for the commerce service and exposes only the localhost port.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / '.local' / 'phone-automation'
PORT = 8100
BASE = f'http://127.0.0.1:{PORT}'
XCODE = '/Applications/Xcode.app/Contents/Developer'
XCODEBUILD = '/usr/bin/xcodebuild'
XCRUN = '/opt/homebrew/bin/xcrun'
IPROXY = ROOT / 'bin' / 'iproxy'
XCTESTRUN = ROOT / 'ios' / '.build' / 'Build' / 'Products' / 'WebDriverAgentRunner_iphoneos27.2-arm64.xctestrun'


def _request(method, path, body=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method,
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def ready(timeout=3):
    try:
        value = _request('GET', '/status', timeout=timeout)
        state = value.get('value', value)
        return bool(state.get('ready'))
    except (OSError, ValueError, urllib.error.URLError):
        return False


class WdaClient:
    def __init__(self):
        self.session = ''
        self.size = (430, 932)
        self._lock = threading.Lock()
        self.open()

    def _call(self, method, path, body=None):
        return _request(method, path, body, timeout=25)

    def open(self):
        with self._lock:
            if self.session:
                return
            value = self._call('POST', '/session', {'capabilities': {}})
            payload = value.get('value') or {}
            session = value.get('sessionId') or payload.get('sessionId')
            if not session:
                raise ValueError('phone_control_unavailable')
            self.session = str(session)
            try:
                size = self._call('GET', f'/session/{self.session}/window/size').get('value') or {}
                self.size = (int(size.get('width') or self.size[0]), int(size.get('height') or self.size[1]))
            except Exception:
                pass

    def close(self):
        with self._lock:
            session, self.session = self.session, ''
        if session:
            try:
                self._call('DELETE', f'/session/{session}')
            except Exception:
                pass

    def tap(self, x, y):
        self.open()
        self._call('POST', f'/session/{self.session}/wda/tap', {'x': x, 'y': y})

    def swipe(self, x1, y1, x2, y2, duration=0.3):
        self.open()
        self._call('POST', f'/session/{self.session}/wda/dragfromtoforduration',
                   {'fromX': x1, 'fromY': y1, 'toX': x2, 'toY': y2, 'duration': duration})

    def home(self):
        self.open()
        self._call('POST', f'/session/{self.session}/wda/pressButton', {'name': 'home'})

    def text(self, value):
        self.open()
        self._call('POST', f'/session/{self.session}/wda/keys', {'value': list(value)})


class WdaManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._xcode = None
        self._iproxy = None
        self._udid = ''

    def _alive(self, process):
        return process is not None and process.poll() is None

    def _stop(self):
        for process in (self._iproxy, self._xcode):
            if self._alive(process):
                try:
                    process.terminate()
                except OSError:
                    pass
        self._iproxy = self._xcode = None

    def ensure(self, udid):
        udid = str(udid or '')
        if not udid:
            raise ValueError('phone_control_unavailable')
        with self._lock:
            if self._alive(self._xcode) and self._alive(self._iproxy) and ready():
                self._udid = udid
                return
            self._stop()
            if not XCTESTRUN.is_file() or not IPROXY.is_file():
                raise ValueError('phone_control_unavailable')
            STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(STATE, 0o700)
            except OSError:
                pass
            log = open(STATE / 'wda.log', 'ab', buffering=0)
            env = dict(os.environ)
            env['DEVELOPER_DIR'] = XCODE
            self._xcode = subprocess.Popen(
                [XCODEBUILD, 'test-without-building', '-xctestrun', str(XCTESTRUN),
                 '-destination', 'id=' + udid, '-destination-timeout', '30'],
                stdout=log, stderr=log, env=env, start_new_session=True,
            )
            log.close()
            self._iproxy = subprocess.Popen(
                [str(IPROXY), str(PORT), str(PORT), udid],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            self._udid = udid
        deadline = time.time() + 45
        while time.time() < deadline:
            if ready(timeout=2):
                return
            if not self._alive(self._xcode):
                self._stop()
                raise ValueError('phone_control_unavailable')
            time.sleep(1)
        self._stop()
        raise ValueError('phone_control_unavailable')

    def stop(self):
        with self._lock:
            self._stop()
            self._udid = ''
