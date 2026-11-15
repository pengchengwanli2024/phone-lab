"""Optional scrcpy-server H.264 preview for the local workbench.

This is an experimental low-latency path next to the MJPEG fallback. It keeps
the existing ADB control lease and only reads video. The server jar is not
committed; set COMMERCE_SCRCPY_SERVER or place scrcpy-server-v5.0.1 under
.local/scrcpy-spike/. Frames stay in memory and are never recorded.
"""
from __future__ import annotations

import json
import os
import random
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
DEFAULT_JAR = PROJECT / '.local' / 'scrcpy-spike' / 'scrcpy-server-v5.0.1'
VERSION = '5.0.1'
QUALITY = {
    'fast': {'max_size': 480, 'max_fps': 10, 'bitrate': 3_000_000},
    'balanced': {'max_size': 720, 'max_fps': 20, 'bitrate': 8_000_000},
    'sharp': {'max_size': 1080, 'max_fps': 30, 'bitrate': 12_000_000},
}
MAX_SIZE = 16 * 1024 * 1024


def _jar_path():
    explicit = os.environ.get('COMMERCE_SCRCPY_SERVER', '')
    candidates = [Path(explicit)] if explicit else []
    candidates += [DEFAULT_JAR, PROJECT / '.local' / 'scrcpy' / 'scrcpy-server', PROJECT / '.local' / 'scrcpy' / 'scrcpy-server.jar']
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def codec_string(config: bytes):
    for marker in (b'\x00\x00\x00\x01\x67', b'\x00\x00\x01\x67'):
        index = config.find(marker)
        if index >= 0:
            nal = index + len(marker) - 1
            if len(config) >= nal + 4:
                return 'avc1.' + ''.join(f'{byte:02X}' for byte in config[nal + 1:nal + 4])
    return 'avc1.42E01E'


class ScrcpyBridge:
    def __init__(self, phone):
        self.phone = phone
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._thread = None
        self._proc = None
        self._socket = None
        self._forward_port = None
        self._scid = None
        self._meta = None
        self._size = (0, 0)
        self._meta_version = 0
        self._config = b''
        self._payload = None
        self._pts = 0
        self._key = False
        self._seq = 0
        self._frame_at = 0.0
        self._subs = 0
        self._generation = 0
        self._last_status = time.time()
        self._last_client = 0.0
        self._error = ''
        self._jar = _jar_path()

    def available(self):
        return bool(self._jar and self.phone.serial() and self.phone.adb())

    def touch(self):
        with self._lock:
            self._last_status = time.time()

    def status(self):
        with self._lock:
            self._last_status = time.time()
            meta = dict(self._meta) if self._meta else {}
            return {
                'available': self.available(),
                'streaming': bool(self._thread and self._thread.is_alive()),
                'width': meta.get('width'),
                'height': meta.get('height'),
                'codec': meta.get('codec'),
                'error': self._error,
            }

    def _subscribe(self):
        with self._lock:
            self._subs += 1
            self._last_client = time.time()
            self._generation += 1
            generation = self._generation
        self._ensure()
        return generation

    def _unsubscribe(self):
        with self._lock:
            self._subs = max(0, self._subs - 1)
            self._last_client = time.time()

    def _should_run(self):
        with self._lock:
            return not self._stop.is_set() and self._subs > 0 and (
                time.time() - self._last_status < 10 or time.time() - self._last_client < 20
            )

    def _ensure(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name='phone-scrcpy', daemon=True)
            self._thread.start()

    def frames(self):
        generation = self._subscribe()
        seen = -1
        seen_meta = -1
        try:
            while not self._stop.is_set():
                meta = None
                frame = None
                with self._cond:
                    if generation != self._generation:
                        return
                    if self._meta and self._meta_version != seen_meta:
                        seen_meta = self._meta_version
                        meta = dict(self._meta)
                    if self._seq == seen and meta is None:
                        self._cond.wait(timeout=5)
                    if generation != self._generation:
                        return
                    if self._seq == seen and meta is None:
                        if time.time() - self._last_status > 8:
                            return
                        continue
                    if self._seq != seen and self._payload is not None:
                        seen = self._seq
                        frame = (self._key, self._pts, self._payload)
                if meta:
                    yield 0, 0, json.dumps(meta, separators=(',', ':')).encode()
                if frame:
                    yield (1 if frame[0] else 2), frame[1], frame[2]
        finally:
            self._unsubscribe()

    def _publish(self, payload: bytes, pts: int, key: bool):
        with self._cond:
            self._payload = payload
            self._pts = pts
            self._key = key
            self._seq += 1
            self._frame_at = time.time()
            self._error = ''
            self._cond.notify_all()

    def _set_meta(self, width, height):
        self._size = (int(width), int(height))
        if not self._config:
            return
        with self._cond:
            self._meta = {'codec': codec_string(self._config),
                          'width': int(width), 'height': int(height)}
            self._meta_version += 1
            self._cond.notify_all()

    def _run(self):
        while self._should_run():
            try:
                self._capture()
            except Exception:
                self._error = 'scrcpy_unavailable'
            finally:
                self._cleanup()
            self._stop.wait(2)
        with self._lock:
            self._payload = None
            self._error = '' if self._stop.is_set() else self._error

    def _capture(self):
        adb = self.phone.adb()
        serial = self.phone.serial()
        jar = self._jar
        if not adb or not serial or not jar:
            raise RuntimeError('scrcpy_unavailable')
        quality = QUALITY.get(self.phone.quality(), QUALITY['balanced'])
        scid = random.randint(1, 0x7FFFFFFF)
        self._scid = scid
        name = 'scrcpy_%08x' % scid
        port = self._free_port()
        self._forward_port = port
        self._push(adb, serial, jar)
        self._forward(adb, serial, port, name)
        command = (
            'CLASSPATH=/data/local/tmp/scrcpy-server.jar app_process / com.genymobile.scrcpy.Server '
            + VERSION
            + ' scid=%x log_level=error video=true audio=false control=false '
            % scid
            + 'send_device_meta=true send_stream_meta=true send_frame_meta=true send_dummy_byte=true '
            + 'tunnel_forward=true cleanup=false video_codec=h264 '
            + 'max_size=%d max_fps=%d video_bit_rate=%d' % (quality['max_size'], quality['max_fps'], quality['bitrate'])
        )
        self._proc = subprocess.Popen(
            [adb, '-s', serial, 'shell', command],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        time.sleep(1.5)
        candidate = socket.create_connection(('127.0.0.1', port), timeout=5)
        candidate.settimeout(8)
        if self._readn(candidate, 1) != b'\x00':
            raise EOFError
        self._readn(candidate, 64)  # device name
        codec = struct.unpack('>I', self._readn(candidate, 4))[0]
        if codec != 0x68323634:
            raise RuntimeError('scrcpy_codec_mismatch')
        _flags, width, height = struct.unpack('>III', self._readn(candidate, 12))
        sock = candidate
        self._socket = sock
        sock.settimeout(15)
        self._set_meta(width, height)
        with self._lock:
            self._error = ''
        while self._should_run():
            header = self._readn(sock, 12)
            pts_flags, size = struct.unpack('>QI', header)
            if size <= 0 or size > MAX_SIZE:
                raise RuntimeError('scrcpy_frame_invalid')
            payload = self._readn(sock, size)
            if pts_flags & (1 << 62):
                self._config = payload
                self._set_meta(width, height)
                continue
            key = bool(pts_flags & (1 << 61))
            pts = pts_flags & ((1 << 61) - 1)
            self._publish((self._config + payload) if key else payload, pts, key)

    def _readn(self, sock, size):
        data = b''
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise EOFError
            data += chunk
        return data

    @staticmethod
    def _free_port():
        probe = socket.socket()
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
        probe.close()
        return port

    @staticmethod
    def _push(adb, serial, jar):
        result = subprocess.run([adb, '-s', serial, 'push', str(jar), '/data/local/tmp/scrcpy-server.jar'],
                                capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError('scrcpy_push_failed')

    @staticmethod
    def _forward(adb, serial, port, name):
        subprocess.run([adb, '-s', serial, 'forward', '--remove', 'tcp:%d' % port], capture_output=True, timeout=5)
        result = subprocess.run([adb, '-s', serial, 'forward', 'tcp:%d' % port, 'localabstract:' + name],
                                capture_output=True, timeout=5)
        if result.returncode:
            raise RuntimeError('scrcpy_forward_failed')

    def _cleanup(self, adb=None, serial=None, port=None):
        sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        adb = adb or self.phone.adb()
        serial = serial or self.phone.serial()
        if adb and serial and self._scid is not None:
            subprocess.run([adb, '-s', serial, 'shell', 'pkill', '-f', 'scid=%x' % self._scid],
                           capture_output=True, timeout=5)
        port = port or self._forward_port
        if adb and serial and port:
            subprocess.run([adb, '-s', serial, 'forward', '--remove', 'tcp:%d' % port],
                           capture_output=True, timeout=5)
        self._forward_port = None
        self._scid = None

    def stop(self):
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        self._cleanup()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=6)
