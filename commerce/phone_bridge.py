"""Loopback phone mirror and explicit, task-scoped control for the workbench.

Read-only preview is the default. A browser must start an explicit control lease
before any tap, swipe, key or text is sent. Frames stay in memory and are never
recorded or logged. Device identifiers are read from the existing private
monitor configuration and are never returned to the client.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import select
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
CONFIG = PROJECT / '.local' / 'control-monitor' / 'config.json'
ADB_CANDIDATES = (
    '/opt/homebrew/share/android-commandlinetools/platform-tools/adb',
    '/opt/homebrew/bin/adb', '/usr/local/bin/adb', '/usr/bin/adb',
)
FFMPEG_CANDIDATES = ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg')
CONTROL_IDLE_SECONDS = 90
STREAM_IDLE_SECONDS = 20
MAX_TEXT = 200
KEYS = {
    'back': 4, 'home': 3, 'recents': 187, 'enter': 66, 'delete': 67,
    'tab': 61, 'escape': 111, 'wakeup': 224,
    'up': 19, 'down': 20, 'left': 21, 'right': 22,
}
QUALITY = {
    'fast': {'width': 480, 'fps': 8, 'bitrate': 3_000_000, 'jpeg': 7},
    'balanced': {'width': 540, 'fps': 10, 'bitrate': 6_000_000, 'jpeg': 6},
    'sharp': {'width': 720, 'fps': 15, 'bitrate': 10_000_000, 'jpeg': 5},
}
_BINARY_CACHE: dict[str, str] = {}


def binary(name: str, candidates: tuple[str, ...]) -> str:
    if name in _BINARY_CACHE:
        return _BINARY_CACHE[name]
    found = shutil.which(name) or ''
    if not found:
        for candidate in candidates:
            if Path(candidate).is_file() and os.access(candidate, os.X_OK):
                found = candidate
                break
    _BINARY_CACHE[name] = found
    return found


def jpeg_size(blob: bytes):
    """Return (width, height) from a JPEG SOF marker, or None."""
    if len(blob) < 10 or not blob.startswith(b'\xff\xd8'):
        return None
    index = 2
    while index + 9 <= len(blob):
        if blob[index] != 0xFF:
            index += 1
            continue
        marker = blob[index + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if index + 4 > len(blob):
            return None
        length = int.from_bytes(blob[index + 2:index + 4], 'big')
        if length < 2 or index + 2 + length > len(blob):
            return None
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height = int.from_bytes(blob[index + 5:index + 7], 'big')
            width = int.from_bytes(blob[index + 7:index + 9], 'big')
            return (width, height) if width and height else None
        index += 2 + length
    return None


def png_size(blob: bytes):
    if len(blob) < 24 or not blob.startswith(b'\x89PNG\r\n\x1a\n') or blob[12:16] != b'IHDR':
        return None
    width = int.from_bytes(blob[16:20], 'big')
    height = int.from_bytes(blob[20:24], 'big')
    return (width, height) if width and height else None


class JpegFramer:
    """Split a concatenated MJPEG byte stream into complete JPEG frames."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk: bytes):
        self.buffer.extend(chunk)
        frames = []
        while True:
            start = self.buffer.find(b'\xff\xd8')
            if start < 0:
                if self.buffer[-1:] == b'\xff':
                    del self.buffer[:-1]
                else:
                    self.buffer.clear()
                break
            if start:
                del self.buffer[:start]
            end = self.buffer.find(b'\xff\xd9', 2)
            if end < 0:
                if len(self.buffer) > 8 * 1024 * 1024:
                    self.buffer.clear()
                break
            frames.append(bytes(self.buffer[:end + 2]))
            del self.buffer[:end + 2]
        return frames


def pixel(value, total: int) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('phone_point_invalid') from None
    if not math.isfinite(number) or number < 0 or number > 1:
        raise ValueError('phone_point_invalid')
    return max(0, min(total - 1, int(round(number * (total - 1)))))


class PhoneBridge:
    def __init__(self, serial=None, lease_key=None):
        self._ensure_tools_path()
        self._lock = threading.RLock()
        self._frame_cond = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._serial = ''
        self._config_error = ''
        self._lease_key = lease_key or 'android'
        if serial is None:
            self._load_config()
        elif re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', str(serial)):
            self._serial = str(serial)
        else:
            self._config_error = 'phone_config_invalid'
        self._frame = None
        self._mime = 'image/jpeg'
        self._seq = 0
        self._frame_at = 0.0
        self._frame_size = None
        self._device_size = None
        self._device_size_at = 0.0
        self._mode = 'idle'
        self._quality = 'balanced'
        self._epoch = 0
        self._error_code = self._config_error
        self._subscribers = 0
        self._stream_generation = 0
        self._last_client = 0.0
        self._last_status = 0.0
        self._online_at = 0.0
        self._online_value = False
        self._pipeline = None
        self._control = None
        self._control_started = 0.0
        self._last_input = 0.0
        self._lease_factory = None
        threading.Thread(target=self._watch_control, name='phone-control-watch', daemon=True).start()

    @staticmethod
    def _ensure_tools_path():
        # The launchd service starts with a minimal PATH. The monitor control
        # lease calls `adb` by name, so expose the resolved tool directories for
        # this process without changing any user-wide configuration.
        current = os.environ.get('PATH', '').split(os.pathsep)
        for name, candidates in (('adb', ADB_CANDIDATES), ('ffmpeg', FFMPEG_CANDIDATES)):
            found = binary(name, candidates)
            if not found:
                continue
            folder = str(Path(found).parent)
            if folder not in current:
                current.insert(0, folder)
        os.environ['PATH'] = os.pathsep.join([item for item in current if item])

    def _load_config(self):
        try:
            value = json.loads(CONFIG.read_text())
            serial = str(value.get('android_serial') or '')
        except FileNotFoundError:
            self._config_error = 'phone_not_configured'
            return
        except (OSError, ValueError, TypeError):
            self._config_error = 'phone_config_invalid'
            return
        if not serial:
            self._config_error = 'phone_not_configured'
        elif re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', serial):
            self._serial = serial
        else:
            self._config_error = 'phone_config_invalid'

    def _adb(self) -> str:
        return binary('adb', ADB_CANDIDATES)

    def serial(self):
        return self._serial

    def adb(self):
        return self._adb()

    def quality(self):
        with self._lock:
            return self._quality

    def ready(self):
        with self._lock:
            return bool(self._serial and self._adb())

    def _online(self) -> bool:
        adb = self._adb()
        if not self._serial or not adb:
            return False
        now = time.time()
        if now - self._online_at < 2:
            return self._online_value
        try:
            result = subprocess.run([adb, '-s', self._serial, 'get-state'], capture_output=True, timeout=4)
        except (OSError, subprocess.SubprocessError):
            value = False
        else:
            value = result.returncode == 0 and result.stdout.strip() == b'device'
        self._online_at, self._online_value = now, value
        return value

    def _probe_size(self):
        now = time.time()
        if self._device_size and now - self._device_size_at < 60:
            return self._device_size
        adb = self._adb()
        if not self._serial or not adb:
            return None
        try:
            result = subprocess.run([adb, '-s', self._serial, 'shell', 'wm', 'size'], capture_output=True, timeout=5)
            text = (result.stdout + result.stderr).decode('utf-8', 'replace')
        except (OSError, subprocess.SubprocessError):
            return None
        override = re.search(r'Override size:\s*(\d+)x(\d+)', text)
        physical = re.search(r'Physical size:\s*(\d+)x(\d+)', text)
        match = override or physical
        if not match:
            return None
        self._device_size = (int(match.group(1)), int(match.group(2)))
        self._device_size_at = now
        return self._device_size

    def _display_size(self):
        base = self._probe_size()
        if not base:
            return None
        width, height = base
        frame = self._frame_size
        if frame and frame[0] != frame[1] and (frame[0] > frame[1]) != (width > height):
            width, height = height, width
        return width, height

    def status(self, start_pipeline=True):
        with self._lock:
            self._last_status = time.time()
            online = self._online()
            size = self._probe_size() if online else None
            frame = self._frame_size
            now = time.time()
            controlling = self._control is not None
            if not self._serial:
                error = self._config_error or 'phone_not_configured'
            elif not online:
                error = 'phone_offline'
            else:
                error = self._error_code
            value = {
                'devices': [{
                    'id': 'android',
                    'label': 'Android',
                    'configured': bool(self._serial),
                    'online': online,
                    'mode': self._mode,
                    'quality': self._quality,
                    'width': (frame or size or (0, 0))[0],
                    'height': (frame or size or (0, 0))[1],
                    'device_width': size[0] if size else None,
                    'device_height': size[1] if size else None,
                    'frame_age': round(now - self._frame_at, 1) if self._frame_at else None,
                    'controlling': controlling,
                    'control_remaining': max(0, int(CONTROL_IDLE_SECONDS - (now - self._last_input))) if controlling else 0,
                    'capabilities': {'tap': True, 'swipe': True, 'key': True, 'text': 'ascii', 'multi_touch': False},
                    'error': error,
                }],
                'control_seconds': CONTROL_IDLE_SECONDS,
                'notice': '画面只在本机内存中显示，不录制、不落盘。只读预览不会标记为控制中。',
            }
        if start_pipeline:
            self._ensure_pipeline()
        return value

    def _subscribe(self):
        with self._lock:
            self._subscribers += 1
            self._last_client = time.time()
            self._stream_generation += 1
            generation = self._stream_generation
        self._ensure_pipeline()
        return generation

    def _unsubscribe(self):
        with self._lock:
            self._subscribers = max(0, self._subscribers - 1)
            self._last_client = time.time()

    def _should_run(self):
        with self._lock:
            now = time.time()
            active = self._subscribers > 0 or self._control is not None
            return not self._stop.is_set() and active and (
                self._control is not None
                or now - self._last_status < 10
                or now - self._last_client < STREAM_IDLE_SECONDS
            )

    def _ensure_pipeline(self):
        with self._lock:
            if self._pipeline and self._pipeline.is_alive():
                return
            if not self._serial:
                return
            self._pipeline = threading.Thread(target=self._run_pipeline, name='phone-preview', daemon=True)
            self._pipeline.start()

    def frames(self):
        generation = self._subscribe()
        seen = -1
        try:
            while not self._stop.is_set():
                with self._frame_cond:
                    if generation != self._stream_generation:
                        return
                    if self._seq == seen:
                        self._frame_cond.wait(timeout=5)
                    if generation != self._stream_generation:
                        return
                    if self._seq == seen:
                        if self._control is None and time.time() - self._last_status > 8:
                            return
                        continue
                    seen, frame, mime = self._seq, self._frame, self._mime
                if frame and mime == 'image/jpeg':
                    yield mime, frame
        finally:
            self._unsubscribe()

    def frame(self):
        with self._lock:
            return (self._mime, self._frame) if self._frame else (None, None)

    def snapshot(self):
        with self._lock:
            if self._frame and 0 <= time.time() - self._frame_at < 2.5:
                return self._mime, self._frame
        adb = self._adb()
        if not self._serial or not adb:
            return None, None
        try:
            result = subprocess.run(
                [adb, '-s', self._serial, 'exec-out', 'screencap', '-p'],
                capture_output=True, timeout=12,
            )
        except (OSError, subprocess.SubprocessError):
            return None, None
        if result.returncode or not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
            return None, None
        jpeg = self._png_to_jpeg(result.stdout)
        return ('image/jpeg', jpeg) if jpeg else ('image/png', result.stdout)

    def _publish(self, frame: bytes, mime: str):
        size = jpeg_size(frame) if mime == 'image/jpeg' else png_size(frame)
        with self._frame_cond:
            self._frame, self._mime = frame, mime
            self._seq += 1
            self._frame_at = time.time()
            if size:
                self._frame_size = size
            self._error_code = ''
            self._frame_cond.notify_all()

    def _set_error(self, code: str):
        with self._lock:
            self._error_code = code

    def _png_to_jpeg(self, png: bytes):
        ffmpeg = binary('ffmpeg', FFMPEG_CANDIDATES)
        if not ffmpeg or not png.startswith(b'\x89PNG\r\n\x1a\n'):
            return None
        with self._lock:
            spec = QUALITY[self._quality]
        try:
            result = subprocess.run(
                [ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'image2pipe', '-i', 'pipe:0',
                 '-vf', 'scale=' + str(spec['width']) + ':-2', '-pix_fmt', 'yuvj420p',
                 '-q:v', str(spec['jpeg']), '-f', 'mjpeg', 'pipe:1'],
                input=png, capture_output=True, timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout if result.stdout.startswith(b'\xff\xd8') else None

    def _seed_snapshot(self):
        with self._lock:
            spec_width = QUALITY[self._quality]['width']
            fresh = (self._frame is not None and time.time() - self._frame_at < 30
                     and self._frame_size is not None and self._frame_size[0] == spec_width)
        if fresh:
            return
        adb = self._adb()
        if not adb:
            return
        try:
            result = subprocess.run(
                [adb, '-s', self._serial, 'exec-out', 'screencap', '-p'],
                capture_output=True, timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return
        if result.returncode == 0 and result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
            jpeg = self._png_to_jpeg(result.stdout)
            self._publish(jpeg or result.stdout, 'image/jpeg' if jpeg else 'image/png')

    def _run_pipeline(self):
        failures = 0
        while self._should_run():
            if not self._online():
                self._set_error('phone_offline')
                self._stop.wait(2)
                continue
            self._seed_snapshot()
            before = self._seq
            try:
                if failures >= 3:
                    self._capture_snapshots()
                else:
                    self._capture_video()
            except Exception:
                failures += 1
                self._set_error('phone_preview_failed')
            else:
                failures = 0
            if self._seq == before:
                failures += 1
            self._stop.wait(1)
        with self._lock:
            self._mode = 'idle'

    def _capture_video(self):
        adb, ffmpeg = self._adb(), binary('ffmpeg', FFMPEG_CANDIDATES)
        if not adb or not ffmpeg:
            raise RuntimeError('preview_tools_missing')
        with self._lock:
            epoch = self._epoch
            spec = QUALITY[self._quality]
        adb_process = subprocess.Popen(
            [adb, '-s', self._serial, 'shell', 'screenrecord', '--output-format=h264',
             '--time-limit', '165', '--bit-rate', str(spec['bitrate']), '-'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
        )
        try:
            ffmpeg_process = subprocess.Popen(
                [ffmpeg, '-hide_banner', '-loglevel', 'error', '-use_wallclock_as_timestamps', '1',
                 '-f', 'h264', '-i', 'pipe:0', '-an',
                 '-vf', 'fps=' + str(spec['fps']) + ',scale=' + str(spec['width']) + ':-2',
                 '-pix_fmt', 'yuvj420p', '-q:v', str(spec['jpeg']), '-flush_packets', '1',
                 '-f', 'mpjpeg', 'pipe:1'],
                stdin=adb_process.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            )
        except Exception:
            adb_process.terminate()
            raise
        if adb_process.stdout:
            adb_process.stdout.close()
        with self._lock:
            self._mode = 'video'
        framer = JpegFramer()
        published = 0
        descriptor = ffmpeg_process.stdout.fileno() if ffmpeg_process.stdout else None
        if descriptor is None:
            raise RuntimeError('video_pipeline_failed')
        # A static screen can stop producing bytes for minutes. Never block on
        # the pipe, so an idle panel can close both ffmpeg and screenrecord.
        os.set_blocking(descriptor, False)
        try:
            while self._should_run() and self._epoch == epoch:
                try:
                    ready, _, _ = select.select([descriptor], [], [], 0.5)
                except OSError:
                    break
                if not ready:
                    continue
                try:
                    chunk = os.read(descriptor, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    break
                for frame in framer.feed(chunk):
                    self._publish(frame, 'image/jpeg')
                    published += 1
        finally:
            for process in (ffmpeg_process, adb_process):
                if process.poll() is None:
                    process.terminate()
            for process in (ffmpeg_process, adb_process):
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
        if not published and self._epoch == epoch:
            raise RuntimeError('video_pipeline_failed')

    def _capture_snapshots(self):
        adb = self._adb()
        if not adb:
            raise RuntimeError('preview_tools_missing')
        with self._lock:
            self._mode = 'snapshot'
        while self._should_run():
            try:
                result = subprocess.run(
                    [adb, '-s', self._serial, 'exec-out', 'screencap', '-p'],
                    capture_output=True, timeout=20,
                )
                if result.returncode == 0 and result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
                    jpeg = self._png_to_jpeg(result.stdout)
                    self._publish(jpeg or result.stdout, 'image/jpeg' if jpeg else 'image/png')
                else:
                    self._set_error('phone_preview_failed')
            except (OSError, subprocess.SubprocessError):
                self._set_error('phone_preview_failed')
            self._stop.wait(1.5)

    def _lease(self):
        if self._lease_factory is None:
            path = PROJECT / 'monitor' / 'control.py'
            if not path.is_file():
                raise ValueError('phone_indicator_unavailable')
            spec = importlib.util.spec_from_file_location('phone_lab_monitor_control', path)
            if spec is None or spec.loader is None:
                raise ValueError('phone_indicator_unavailable')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._lease_factory = module.Lease
        return self._lease_factory('android', self._serial, key=self._lease_key)

    def start_control(self):
        with self._lock:
            if self._control is not None:
                return self.status()
            if not self._serial:
                raise ValueError(self._config_error or 'phone_not_configured')
            if not self._online():
                raise ValueError('phone_offline')
            lease = self._lease()
            try:
                lease.__enter__()
            except RuntimeError as exc:
                if 'active controller' in str(exc):
                    raise ValueError('phone_control_busy') from None
                raise ValueError('phone_indicator_unavailable') from None
            self._control = lease
            self._control_started = self._last_input = time.time()
        self._ensure_pipeline()
        return self.status()

    def _release_control(self):
        with self._lock:
            lease, self._control = self._control, None
        if lease is not None:
            try:
                lease.__exit__(None, None, None)
            except Exception:
                pass

    def end_control(self):
        self._release_control()
        return self.status()

    def settings(self, payload):
        quality = str(payload.get('quality') or '')
        if quality not in QUALITY:
            raise ValueError('phone_quality_invalid')
        with self._lock:
            if quality == self._quality:
                return self.status()
            self._quality = quality
            self._epoch += 1
        self._ensure_pipeline()
        return self.status()

    def control(self, payload):
        action = str(payload.get('action') or '')
        if action == 'start':
            return self.start_control()
        if action == 'end':
            return self.end_control()
        raise ValueError('phone_action_invalid')

    def _run_adb(self, adb: str, args):
        try:
            result = subprocess.run([adb, '-s', self._serial] + list(args), capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            raise ValueError('phone_input_failed') from None
        if result.returncode or b'Error' in result.stderr or b'Error' in result.stdout:
            raise ValueError('phone_input_failed')

    def input(self, payload):
        if str(payload.get('device') or 'android') != 'android':
            raise ValueError('phone_device_unknown')
        action = str(payload.get('action') or '')
        with self._lock:
            if self._control is None:
                raise ValueError('phone_control_required')
            size = self._display_size()
            adb = self._adb()
            if not size or not adb:
                raise ValueError('phone_offline')
            self._last_input = time.time()
            if action == 'tap':
                x, y = pixel(payload.get('x'), size[0]), pixel(payload.get('y'), size[1])
                # A zero-distance swipe is a tap that also works on vivo builds that
                # swallow `input tap` until USB simulated clicking is enabled.
                self._run_adb(adb, ['shell', 'input', 'swipe', str(x), str(y), str(x), str(y), '60'])
            elif action == 'swipe':
                x1, y1 = pixel(payload.get('x1'), size[0]), pixel(payload.get('y1'), size[1])
                x2, y2 = pixel(payload.get('x2'), size[0]), pixel(payload.get('y2'), size[1])
                try:
                    duration = int(payload.get('duration') or 300)
                except (TypeError, ValueError):
                    raise ValueError('phone_duration_invalid') from None
                duration = max(80, min(2000, duration))
                self._run_adb(adb, ['shell', 'input', 'swipe', str(x1), str(y1), str(x2), str(y2), str(duration)])
            elif action == 'key':
                code = KEYS.get(str(payload.get('key') or ''))
                if code is None:
                    raise ValueError('phone_key_unknown')
                self._run_adb(adb, ['shell', 'input', 'keyevent', str(code)])
            elif action == 'text':
                text = str(payload.get('text') or '')
                if not text or len(text) > MAX_TEXT:
                    raise ValueError('phone_text_invalid')
                if any(ord(character) < 32 or ord(character) > 126 for character in text):
                    raise ValueError('phone_text_ascii_only')
                remote = 'input text ' + shlex.quote(text.replace(' ', '%s'))
                self._run_adb(adb, ['shell', remote])
            else:
                raise ValueError('phone_action_invalid')
            return {'ok': True, 'action': action, 'at': time.time()}

    def _watch_control(self):
        while not self._stop.wait(3):
            with self._lock:
                expired = self._control is not None and time.time() - self._last_input > CONTROL_IDLE_SECONDS
            if expired:
                self._release_control()

    def stop(self):
        self._stop.set()
        with self._frame_cond:
            self._frame_cond.notify_all()
        self._release_control()
        thread = self._pipeline
        if thread is not None:
            thread.join(timeout=6)
