"""Auto-discovered local phone fleet.

Android devices are discovered through ADB and can be previewed/controlled.
Paired iPhones are discovered through CoreDevice and are preview-only until
WDA is available. Device identifiers never leave this module: the browser gets
stable hashed ids, labels and model names only. Frames stay in memory; the
only temporary file is the private devicectl screenshot, removed immediately.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from phone_bridge import ADB_CANDIDATES, FFMPEG_CANDIDATES, PhoneBridge, binary, jpeg_size, png_size
from phone_frame_policy import FrameCapturePolicy
from phone_wda import WdaClient, WdaManager, XCTESTRUN, ready as wda_ready

PROJECT = Path(__file__).resolve().parent.parent
CONFIG = PROJECT / '.local' / 'control-monitor' / 'config.json'
MAX_DEVICES = 12
DISCOVER_SECONDS = 30.0
SNAPSHOT_SECONDS = 1.2
FRAME_MAX_AGE_SECONDS = 15.0
XCRUN = '/opt/homebrew/bin/xcrun' if Path('/opt/homebrew/bin/xcrun').is_file() else (shutil.which('xcrun') or 'xcrun')
IOS_LOCK = threading.Lock()
NAME = re.compile(r'[^\w .()+-]', re.UNICODE)


def _clean(value, limit=60):
    text = NAME.sub('', str(value or '')).strip()
    return text[:limit]


def _device_id(prefix, secret):
    return prefix + hashlib.sha256(str(secret).encode()).hexdigest()[:15]


def _fresh_frame(cached, seconds):
    # A wall-clock rollback cannot make a cached observation fresh indefinitely.
    return bool(cached and 0 <= time.time() - cached[0] < seconds)


def _primary_serial():
    try:
        value = json.loads(CONFIG.read_text())
        return str(value.get('android_serial') or '')
    except (OSError, ValueError, TypeError):
        return ''


class IosDevice:
    def __init__(self, udid, model, identifier=''):
        self.udid = str(udid)
        self.model = _clean(model, 60) or 'iPhone'
        self.identifier = str(identifier or udid)

    def snapshot(self):
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            target = Path(tmp.name)
        try:
            with IOS_LOCK:
                done = subprocess.run(
                    [XCRUN, 'devicectl', 'device', 'capture', 'screenshot',
                     '--device', self.udid, '--destination', str(target)],
                    capture_output=True, timeout=25,
                )
            if done.returncode == 0:
                body = target.read_bytes()
                if body.startswith(b'\x89PNG\r\n\x1a\n'):
                    # A full iPhone screenshot is ~11 MB. The wall and detail only
                    # need a readable preview, so keep a bounded JPEG in memory.
                    ffmpeg = binary('ffmpeg', FFMPEG_CANDIDATES)
                    if ffmpeg:
                        try:
                            small = subprocess.run(
                                [ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', 'pipe:0',
                                 '-vf', 'scale=900:-2', '-frames:v', '1', '-f', 'image2pipe',
                                 '-vcodec', 'mjpeg', '-q:v', '6', 'pipe:1'],
                                input=body, capture_output=True, timeout=12,
                            )
                            if small.returncode == 0 and small.stdout.startswith(b'\xff\xd8'):
                                return 'image/jpeg', small.stdout
                        except (OSError, subprocess.SubprocessError):
                            pass
                    return 'image/png', body
            return None, None
        except (OSError, subprocess.SubprocessError):
            return None, None
        finally:
            try:
                target.unlink()
            except OSError:
                pass


class PhoneFleet:
    def __init__(self):
        self._lock = threading.RLock()
        self._discovered_at = 0.0
        self._android = {}   # id -> PhoneBridge
        self._ios = {}       # id -> IosDevice
        self._meta = {}      # id -> dict
        self._snap = {}      # id -> (at, mime, body)
        self._snap_locks = {}
        self._snap_running = set()
        self._capture_policy = FrameCapturePolicy()
        self._models = {}
        self._snap_ok = {}
        self._empty_since = {'android': 0.0, 'ios': 0.0}
        self._primary = _primary_serial()
        self._wda = WdaManager()
        self._ios_controls = {}
        self._stop_event = threading.Event()
        threading.Thread(target=self._watch_ios, name='phone-fleet-ios-control', daemon=True).start()

    # -- discovery ---------------------------------------------------------
    def _android_devices(self):
        adb = binary('adb', ADB_CANDIDATES)
        if not adb:
            return []
        try:
            done = subprocess.run([adb, 'devices', '-l'], capture_output=True, timeout=8)
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode:
            return None
        found = []
        for line in done.stdout.decode('utf-8', 'replace').splitlines():
            parts = line.split()
            if len(parts) < 2 or parts[1] != 'device':
                continue
            serial = parts[0]
            if not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', serial):
                continue
            model = ''
            for token in parts[2:]:
                if token.startswith('model:'):
                    model = token.split(':', 1)[1].replace('_', ' ')
                    break
            if serial not in self._models:
                label = _clean(model, 60) or 'Android'
                try:
                    props = subprocess.run(
                        [adb, '-s', serial, 'shell',
                         'getprop ro.product.brand; getprop ro.product.marketname; getprop ro.vivo.market.name'],
                        capture_output=True, timeout=5,
                    )
                    lines = [line.strip() for line in props.stdout.decode('utf-8', 'replace').splitlines() if line.strip()]
                    market = lines[1] if len(lines) > 1 and lines[1] else (lines[2] if len(lines) > 2 else '')
                    brand = lines[0] if lines else ''
                    if market:
                        label = _clean((brand + ' ' + market).strip(), 60)
                except (OSError, subprocess.SubprocessError):
                    pass
                self._models[serial] = label
            found.append((serial, self._models[serial]))
        return found

    def _ios_devices(self):
        if not Path(XCRUN).exists():
            return []
        try:
            with IOS_LOCK:
                done = subprocess.run(
                    [XCRUN, 'devicectl', 'list', 'devices', '--json-output', '-'],
                    capture_output=True, timeout=15,
                )
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode:
            return None
        try:
            value = json.loads(done.stdout)
            rows = value['result']['devices']
        except (ValueError, KeyError, TypeError):
            return None
        found = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            props = row.get('hardwareProperties') or {}
            connection = row.get('connectionProperties') or {}
            if props.get('reality') != 'physical':
                continue
            if connection.get('pairingState') != 'paired':
                continue
            # CoreDevice retains paired phones after unplugging. Pairing alone
            # is not a live developer transport for screenshots or WDA.
            if connection.get('tunnelState') != 'connected':
                continue
            udid = str(props.get('udid') or '')
            if not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', udid):
                continue
            found.append((udid, _clean(props.get('marketingName'), 60) or 'iPhone', str(row.get('identifier') or udid)))
        return found

    def _labels(self, rows):
        counts = {}
        for row in rows:
            counts[row[1]] = counts.get(row[1], 0) + 1
        seen = {}
        result = []
        for row in rows:
            label = row[1]
            seen[label] = seen.get(label, 0) + 1
            suffix = ' ' + str(seen[label]) if counts[label] > 1 else ''
            result.append(tuple([row[0], label + suffix] + list(row[2:])))
        return result

    def _grace(self, kind, found, existing, now):
        if found is None:
            return None
        if found:
            self._empty_since[kind] = 0.0
            return found
        if not existing:
            return found
        if not self._empty_since[kind]:
            self._empty_since[kind] = now
            return None
        if now - self._empty_since[kind] < 6:
            return None
        self._empty_since[kind] = 0.0
        return found

    def _refresh(self):
        now = time.time()
        with self._lock:
            if self._stop_event.is_set():
                return
            if now - self._discovered_at < DISCOVER_SECONDS:
                return
        android = self._android_devices()
        ios = self._ios_devices()
        android = self._grace('android', android, bool(self._android), now)
        ios = self._grace('ios', ios, bool(self._ios), now)
        with self._lock:
            if self._stop_event.is_set():
                return
            if android is None and ios is None:
                self._discovered_at = now
                return
            self._discovered_at = now
            if android is not None:
                wanted = {}
                for serial, model in self._labels(android):
                    ident = _device_id('a', serial)
                    wanted[ident] = (serial, model)
                for ident in list(self._android):
                    if ident not in wanted:
                        bridge = self._android.pop(ident)
                        self._meta.pop(ident, None)
                        self._snap.pop(ident, None)
                        self._snap_ok.pop(ident, None)
                        self._snap_locks.pop(ident, None)
                        self._capture_policy.forget(ident)
                        threading.Thread(target=bridge.stop, daemon=True).start()
                for ident, (serial, model) in wanted.items():
                    bridge = self._android.get(ident)
                    if bridge is None:
                        lease = 'android' if serial == self._primary else 'android-' + ident
                        bridge = PhoneBridge(serial=serial, lease_key=lease)
                        self._android[ident] = bridge
                    self._meta[ident] = {'kind': 'android', 'label': model, 'model': model}
                    self._snap_locks.setdefault(ident, threading.Lock())
            if ios is not None:
                wanted = {}
                for udid, model, identifier in self._labels(ios):
                    ident = _device_id('i', udid)
                    wanted[ident] = IosDevice(udid, model, identifier)
                for ident in list(self._ios):
                    if ident not in wanted:
                        self._ios.pop(ident, None)
                        self._meta.pop(ident, None)
                        self._snap.pop(ident, None)
                        self._snap_ok.pop(ident, None)
                        self._snap_locks.pop(ident, None)
                        self._capture_policy.forget(ident)
                for ident, device in wanted.items():
                    self._ios[ident] = device
                    self._meta[ident] = {'kind': 'ios', 'label': device.model, 'model': device.model}
                    self._snap_locks.setdefault(ident, threading.Lock())

    # -- status ------------------------------------------------------------
    def status(self):
        self._refresh()
        with self._lock:
            metas = dict(self._meta)
            android = dict(self._android)
            ios = dict(self._ios)
            snaps = {key: value[0] for key, value in self._snap.items()}
            delayed = {key for key in metas if self._snap_ok.get(key) is False
                       or (key in self._snap and not _fresh_frame(self._snap[key], FRAME_MAX_AGE_SECONDS))}
        devices = []
        for ident, meta in metas.items():
            if meta['kind'] == 'android':
                bridge = android.get(ident)
                if bridge is None:
                    continue
                try:
                    row = bridge.status(start_pipeline=False)['devices'][0]
                except Exception:
                    row = {'online': False, 'mode': 'error', 'quality': 'balanced', 'width': 0, 'height': 0,
                           'controlling': False, 'control_remaining': 0, 'error': 'phone_offline',
                           'capabilities': {'tap': False, 'swipe': False, 'key': False, 'text': 'none', 'multi_touch': False}}
                devices.append({
                    'id': ident, 'kind': 'android', 'label': meta['label'], 'model': meta['model'],
                    'online': bool(row.get('online')), 'mode': row.get('mode') or 'idle',
                    'quality': row.get('quality') or 'balanced', 'width': row.get('width') or 0,
                    'height': row.get('height') or 0, 'controlling': bool(row.get('controlling')),
                    'control_remaining': row.get('control_remaining') or 0,
                    'capabilities': row.get('capabilities') or {},
                    'error': row.get('error') or ('phone_frame_unavailable' if ident in delayed else ''),
                    'frame_at': snaps.get(ident, 0),
                    'controllable': True, 'control_reason': '',
                })
            else:
                device = ios.get(ident)
                if device is None:
                    continue
                online = True
                size = self._snap.get(ident)
                width = height = 0
                if size:
                    size = png_size(size[2]) or jpeg_size(size[2]) or (0, 0)
                    width, height = size
                control = self._ios_controls.get(ident)
                controlling = control is not None
                remaining = max(0, int(90 - (time.time() - control['last_input']))) if control else 0
                devices.append({
                    'id': ident, 'kind': 'ios', 'label': meta['label'], 'model': meta['model'],
                    'online': online, 'mode': 'snapshot', 'quality': '', 'width': width, 'height': height,
                    'controlling': controlling, 'control_remaining': remaining,
                    'capabilities': {'tap': True, 'swipe': True, 'key': True, 'text': 'ascii', 'multi_touch': False},
                    'error': 'phone_frame_unavailable' if ident in delayed else '',
                    'frame_at': snaps.get(ident, 0), 'controllable': XCTESTRUN.is_file(),
                    'control_reason': '' if XCTESTRUN.is_file() else 'wda_unavailable',
                })
        devices.sort(key=lambda row: (0 if row['kind'] == 'android' else 1, row['label'].lower(), row['id']))
        return {
            'devices': devices[:MAX_DEVICES],
            'control_seconds': 90,
            'notice': '自动发现已连接手机；Android 和 iPhone 均可显式控制，iPhone 使用 WDA，延迟高于 Android。画面只在本机内存显示，不录制、不落盘。',
        }

    # -- snapshots ---------------------------------------------------------
    def _snapshot_locked(self, ident, generation):
        with self._lock:
            meta = self._meta.get(ident)
            bridge = self._android.get(ident)
            ios = self._ios.get(ident)
            cached = self._snap.get(ident)
            lock = self._snap_locks.get(ident)
        if meta is None or lock is None or lock is not generation or self._stop_event.is_set():
            return None, None
        if _fresh_frame(cached, SNAPSHOT_SECONDS):
            return cached[1], cached[2]
        if not lock.acquire(blocking=False):
            return (cached[1], cached[2]) if _fresh_frame(cached, FRAME_MAX_AGE_SECONDS) else (None, None)
        try:
            if _fresh_frame(cached, SNAPSHOT_SECONDS):
                return cached[1], cached[2]
            if meta['kind'] == 'android' and bridge is not None:
                mime, body = bridge.snapshot()
            elif ios is not None:
                mime, body = ios.snapshot()
            else:
                mime, body = None, None
            if mime and body:
                with self._lock:
                    # Removal/reconnection and stop invalidate this capture's
                    # generation, even when the old subprocess finishes later.
                    if self._stop_event.is_set() or self._snap_locks.get(ident) is not lock:
                        return None, None
                    self._snap[ident] = (time.time(), mime, body)
                    self._snap_ok[ident] = True
                return mime, body
            with self._lock:
                if self._snap_locks.get(ident) is lock and not self._stop_event.is_set():
                    self._snap_ok[ident] = False
            return None, None
        finally:
            lock.release()

    def _warm(self, ident):
        with self._lock:
            if self._stop_event.is_set() or ident not in self._meta or ident in self._snap_running:
                return
            ticket = self._capture_policy.begin(ident)
            if ticket is None:
                return
            self._snap_running.add(ident)
            generation = self._snap_locks.get(ident)
        def work():
            success = False
            try:
                mime, body = self._snapshot_locked(ident, generation)
                success = bool(mime and body)
            except Exception:
                # Capture errors may contain private device details. Keep only
                # the existing public failure code, never raw subprocess text.
                with self._lock:
                    if self._snap_locks.get(ident) is generation and not self._stop_event.is_set():
                        self._snap_ok[ident] = False
            finally:
                with self._lock:
                    self._capture_policy.finish(ticket, success=success)
                    self._snap_running.discard(ident)
        try:
            threading.Thread(target=work, name='phone-fleet-snapshot', daemon=True).start()
        except RuntimeError:
            with self._lock:
                self._capture_policy.finish(ticket, success=False)
                self._snap_running.discard(ident)
                if self._snap_locks.get(ident) is generation and not self._stop_event.is_set():
                    self._snap_ok[ident] = False

    def snapshot(self, ident):
        self._refresh()
        ident = str(ident or '')
        with self._lock:
            if self._stop_event.is_set() or ident not in self._meta:
                return None, None
            cached = self._snap.get(ident)
        if _fresh_frame(cached, 2.0):
            return cached[1], cached[2]
        self._warm(ident)
        if _fresh_frame(cached, FRAME_MAX_AGE_SECONDS):
            return cached[1], cached[2]
        return None, None

    # -- live stream / control --------------------------------------------
    def live(self, ident):
        self._refresh()
        with self._lock:
            return self._android.get(str(ident or '')) is not None

    def frames(self, ident):
        self._refresh()
        with self._lock:
            bridge = self._android.get(str(ident or ''))
        if bridge is None:
            raise ValueError('phone_device_unknown')
        return bridge.frames()

    @staticmethod
    def _lease_class():
        path = PROJECT / 'monitor' / 'control.py'
        spec = importlib.util.spec_from_file_location('phone_fleet_monitor_control', path)
        if spec is None or spec.loader is None:
            raise ValueError('phone_indicator_unavailable')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.Lease

    def _start_ios(self, ident):
        with self._lock:
            device = self._ios.get(ident)
            if ident in self._ios_controls:
                return self.status()
        if device is None:
            raise ValueError('phone_device_unknown')
        try:
            self._wda.ensure(device.udid)
            client = WdaClient()
        except Exception:
            raise ValueError('phone_control_unavailable') from None
        try:
            lease = self._lease_class()('ios', key='ios-' + ident)
            lease.__enter__()
        except Exception:
            client.close()
            raise ValueError('phone_indicator_unavailable') from None
        with self._lock:
            self._ios_controls[ident] = {'client': client, 'lease': lease, 'size': client.size, 'last_input': time.time()}
        return self.status()

    def _end_ios(self, ident):
        with self._lock:
            control = self._ios_controls.pop(ident, None)
        if control is not None:
            try:
                control['client'].close()
            except Exception:
                pass
            try:
                control['lease'].__exit__(None, None, None)
            except Exception:
                pass

    def _watch_ios(self):
        while not self._stop_event.wait(3):
            now = time.time()
            with self._lock:
                expired = [key for key, value in self._ios_controls.items() if now - value['last_input'] > 90]
            for key in expired:
                self._end_ios(key)

    def control(self, payload):
        self._refresh()
        ident = str(payload.get('id') or '')
        action = str(payload.get('action') or '')
        with self._lock:
            bridge = self._android.get(ident)
            meta = self._meta.get(ident)
        if meta is None:
            raise ValueError('phone_device_unknown')
        if meta['kind'] == 'ios':
            if action == 'start':
                return self._start_ios(ident)
            if action == 'end':
                self._end_ios(ident)
                return self.status()
            raise ValueError('phone_action_invalid')
        if bridge is None:
            raise ValueError('phone_control_unavailable')
        bridge.control(payload)
        return self.status()

    def input(self, payload):
        self._refresh()
        ident = str(payload.get('id') or '')
        action = str(payload.get('action') or '')
        with self._lock:
            bridge = self._android.get(ident)
            meta = self._meta.get(ident)
            control = self._ios_controls.get(ident)
        if meta is None:
            raise ValueError('phone_device_unknown')
        if meta['kind'] == 'ios':
            if control is None:
                raise ValueError('phone_control_required')
            width, height = control['size']
            try:
                if action == 'tap':
                    x = max(0, min(width - 1, round(float(payload.get('x')) * width)))
                    y = max(0, min(height - 1, round(float(payload.get('y')) * height)))
                    control['client'].tap(x, y)
                elif action == 'swipe':
                    x1 = max(0, min(width - 1, round(float(payload.get('x1')) * width)))
                    y1 = max(0, min(height - 1, round(float(payload.get('y1')) * height)))
                    x2 = max(0, min(width - 1, round(float(payload.get('x2')) * width)))
                    y2 = max(0, min(height - 1, round(float(payload.get('y2')) * height)))
                    duration = max(0.08, min(2.0, float(payload.get('duration') or 300) / 1000))
                    control['client'].swipe(x1, y1, x2, y2, duration)
                elif action == 'key':
                    key = str(payload.get('key') or '')
                    if key == 'home':
                        control['client'].home()
                    elif key == 'back':
                        control['client'].swipe(round(width * 0.01), round(height * 0.5), round(width * 0.7), round(height * 0.5), 0.25)
                    else:
                        raise ValueError('phone_key_unknown')
                elif action == 'text':
                    value = str(payload.get('text') or '')
                    if not value or len(value) > 200:
                        raise ValueError('phone_text_invalid')
                    control['client'].text(value)
                else:
                    raise ValueError('phone_action_invalid')
            except ValueError:
                raise
            except Exception:
                raise ValueError('phone_input_failed') from None
            with self._lock:
                control['last_input'] = time.time()
            return {'ok': True, 'action': action, 'at': time.time()}
        if bridge is None:
            raise ValueError('phone_control_unavailable')
        value = dict(payload)
        value['device'] = 'android'
        return bridge.input(value)

    def stop(self):
        self._stop_event.set()
        with self._lock:
            self._capture_policy.close()
            ios_controls = list(self._ios_controls)
            bridges = list(self._android.values())
            self._android.clear()
            self._ios.clear()
            self._meta.clear()
            self._snap.clear()
            self._snap_ok.clear()
            self._snap_locks.clear()
        for ident in ios_controls:
            self._end_ios(ident)
        try:
            self._wda.stop()
        except Exception:
            pass
        for bridge in bridges:
            try:
                bridge.stop()
            except Exception:
                pass
