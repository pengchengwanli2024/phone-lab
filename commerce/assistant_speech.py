"""Explicit local rendering of one hash-bound, completed copilot answer.

No playback, arbitrary text, executable, path, voice installation, or cloud API
is exposed. The shared client owns playback after the user requests rendering.
"""
from pathlib import Path
import base64
import hashlib
import io
import json
import os
import platform
import re
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import threading
import time
import wave

TIMEOUT_SECONDS = 30
MAX_TEXT_CHARACTERS = 2000
MAX_TEXT_BYTES = 8000
MAX_AUDIO_BYTES = 6 * 1024 * 1024
MAX_INTERMEDIATE_BYTES = 32 * 1024 * 1024
MAX_DURATION_SECONDS = 120
_RENDER_LOCK = threading.Lock()
_ARGUMENTS = {'thread_id', 'run_id', 'expected_text_sha256'}


def definitions(schema, string):
    return [('commerce_assistant_speech',
             '用户明确请求时，将本对话已完成且文本哈希一致的回答在本机生成音频；不播放、不调用云服务',
             schema({'thread_id': string, 'run_id': string,
                     'expected_text_sha256': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}},
                    ['thread_id', 'run_id', 'expected_text_sha256']))]


class _RenderFailure(Exception):
    def __init__(self, reason, status='failed'):
        self.reason, self.status = reason, status


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise _RenderFailure('render_cancelled', 'cancelled')


def _stop_group(process):
    # The caller creates a new session. Kill its descendants as well as the
    # direct child; terminating only say/ffmpeg can leave inherited work alive.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Darwin can report EPERM while an exited group is being reaped.
            # If the direct child is still alive, retain the normal fallback.
            if process.poll() is None:
                try:
                    process.send_signal(sig)
                except ProcessLookupError:
                    pass
        try:
            process.wait(timeout=.25)
        except subprocess.TimeoutExpired:
            continue
        if sig == signal.SIGTERM:
            # A direct child can exit before a descendant handles termination.
            continue
        break


def _run(argv, deadline, cancel_event, *, stdout=None, limits=()):
    _check_cancel(cancel_event)
    if time.monotonic() >= deadline:
        raise _RenderFailure('render_timeout')
    process = None
    completed = False
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                   stdout=stdout if stdout is not None else subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        while True:
            _check_cancel(cancel_event)
            if time.monotonic() >= deadline:
                raise _RenderFailure('render_timeout')
            for target, maximum, reason in limits:
                size = os.fstat(target.fileno()).st_size if hasattr(target, 'fileno') else target.stat().st_size
                if size > maximum:
                    raise _RenderFailure(reason)
            code = process.poll()
            if code is not None:
                if code != 0:
                    raise _RenderFailure('local_render_failed')
                completed = True
                return
            time.sleep(.025)
    finally:
        if process is not None and (not completed or process.poll() is None):
            _stop_group(process)


def _voice(text, listing):
    if re.search('[\u3040-\u30ff]', text):
        locales = ('ja_JP',)
    elif re.search('[\uac00-\ud7af]', text):
        locales = ('ko_KR',)
    elif re.search('[\u3400-\u9fff]', text):
        locales = ('zh_CN', 'zh_TW', 'zh_HK')
    elif re.search('[\u0400-\u052f]', text):
        locales = ('ru_RU',)
    else:
        locales = ('en_US', 'en_GB')
    voices = []
    preferred = ('Tingting', 'Meijia', 'Sinji', 'Samantha', 'Alex', 'Daniel', 'Milena', 'Kyoko', 'Yuna')
    for line in listing.splitlines():
        match = re.fullmatch(r'\s*(.{1,100}?)\s+([a-z]{2,3}_[A-Z]{2})\s+#.*', line)
        if not match:
            continue
        name, locale = match.groups()
        if locale not in locales or any(ord(char) < 32 for char in name):
            continue
        base = name.split(' (', 1)[0]
        rank = preferred.index(base) if base in preferred else len(preferred)
        voices.append((locales.index(locale), rank, name, locale))
    if not voices:
        raise _RenderFailure('suitable_voice_unavailable', 'unavailable')
    _, _, name, locale = min(voices)
    return name, locale


def _private_file(path, contents=b''):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as target:
        target.write(contents)


def _audio(path):
    if path.stat().st_size > MAX_AUDIO_BYTES:
        raise _RenderFailure('audio_too_large')
    with path.open('rb') as source:
        data = source.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise _RenderFailure('audio_too_large')
    try:
        with wave.open(io.BytesIO(data), 'rb') as source:
            frames = source.getnframes()
            if (source.getnchannels() != 1 or source.getsampwidth() != 2
                    or source.getframerate() != 22050 or source.getcomptype() != 'NONE'
                    or not 0 < frames <= 22050 * MAX_DURATION_SECONDS
                    or len(source.readframes(frames + 1)) != frames * 2):
                raise _RenderFailure('invalid_audio')
    except (wave.Error, EOFError, ValueError):
        raise _RenderFailure('invalid_audio') from None
    return data, frames / 22050


class SpeechReader:
    def __init__(self, service):
        self.core = service.core

    def invoke(self, name, args):
        if name != 'commerce_assistant_speech':
            raise ValueError('unknown_tool')
        if not isinstance(args, dict) or set(args) != _ARGUMENTS:
            raise ValueError('assistant_speech_invalid_arguments')
        return self.render(**args)

    def _answer(self, thread_id, run_id, expected_text_sha256):
        for value in (thread_id, run_id):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}', value):
                raise ValueError('assistant_speech_invalid_arguments')
        if not isinstance(expected_text_sha256, str) or not re.fullmatch('[a-f0-9]{64}', expected_text_sha256):
            raise ValueError('assistant_speech_invalid_arguments')
        try:
            with self.core.db() as db:
                row = db.execute('''SELECT r.status, length(r.result),
                    CASE WHEN length(r.result)<=262144 THEN r.result ELSE NULL END
                    FROM copilot_turns t JOIN agent_runs r ON r.id=t.run_id
                    WHERE t.thread_id=? AND t.run_id=?''', (thread_id, run_id)).fetchone()
                if row is None and db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('market_research_runs','market_research_jobs')").fetchone()[0] == 2:
                    # Explicit research recovery keeps the original human turn;
                    # its authoritative successor belongs to that same task and
                    # thread, rather than to a fabricated duplicate turn.
                    row = db.execute('''SELECT r.status, length(r.result),
                        CASE WHEN length(r.result)<=262144 THEN r.result ELSE NULL END
                        FROM agent_runs r JOIN market_research_runs m ON m.run_id=r.id
                        JOIN market_research_jobs j ON j.task_id=m.task_id
                        WHERE r.id=? AND json_extract(j.document,'$.thread_id')=?
                        AND json_extract(j.document,'$.run_id')=r.id''', (run_id, thread_id)).fetchone()
        except sqlite3.Error:
            raise ValueError('assistant_speech_answer_unavailable') from None
        if not row:
            raise ValueError('assistant_speech_run_not_found')
        if row[0] != 'completed':
            raise ValueError('assistant_speech_answer_not_completed')
        if row[1] is not None and row[1] > 262144:
            raise ValueError('assistant_speech_answer_too_large')
        try:
            result = json.loads(row[2])
            text = result.get('answer') if isinstance(result, dict) else None
            if not isinstance(text, str) or not text.strip() or any(ord(char) < 32 and char not in '\t\n\r' for char in text):
                raise ValueError()
            encoded = text.encode('utf-8')
        except (TypeError, ValueError, UnicodeError):
            raise ValueError('assistant_speech_answer_unavailable') from None
        if len(text) > MAX_TEXT_CHARACTERS or len(encoded) > MAX_TEXT_BYTES:
            raise ValueError('assistant_speech_answer_too_large')
        if hashlib.sha256(encoded).hexdigest() != expected_text_sha256:
            raise ValueError('assistant_speech_answer_changed')
        return text

    def render(self, thread_id, run_id, expected_text_sha256, *, cancel_event=None):
        """The optional cancellation event is a trusted in-process hook only."""
        text = self._answer(thread_id, run_id, expected_text_sha256)
        if not _RENDER_LOCK.acquire(blocking=False):
            return {'status': 'failed', 'reason': 'render_busy', 'setup_required': False}
        try:
            _check_cancel(cancel_event)
            if platform.system() != 'Darwin':
                raise _RenderFailure('unsupported_platform', 'unavailable')
            say, ffmpeg = shutil.which('say'), shutil.which('ffmpeg')
            if not say or not ffmpeg:
                raise _RenderFailure('local_dependencies_missing', 'unavailable')
            deadline = time.monotonic() + TIMEOUT_SECONDS
            with tempfile.TemporaryFile() as listing:
                _run([say, '-v', '?'], deadline, cancel_event, stdout=listing,
                     limits=((listing, 65536, 'voice_listing_too_large'),))
                listing.seek(0)
                voice, locale = _voice(text, listing.read(65536).decode('utf-8', errors='replace'))
            with tempfile.TemporaryDirectory(prefix='commerce-speech-') as directory:
                root = Path(directory)
                root.chmod(0o700)
                source, intermediate, target = root/'answer.txt', root/'speech.aiff', root/'speech.wav'
                # macOS speech commands use [[...]]. Preserve the answer hash,
                # but read these delimiters literally instead of honoring them.
                plain = re.sub(r'(?<=\[)(?=\[)|(?<=\])(?=\])', ' ', text)
                _private_file(source, plain.encode('utf-8'))
                _private_file(intermediate)
                _private_file(target)
                _run([say, '-v', voice, '-r', '180', '-f', str(source), '-o', str(intermediate),
                      '--file-format=AIFF'], deadline, cancel_event,
                     limits=((intermediate, MAX_INTERMEDIATE_BYTES, 'audio_too_large'),))
                _run([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                      '-protocol_whitelist', 'file,pipe', '-i', str(intermediate),
                      '-vn', '-ac', '1', '-ar', '22050', '-c:a', 'pcm_s16le', '-threads', '1',
                      '-f', 'wav', str(target)], deadline, cancel_event,
                     limits=((target, MAX_AUDIO_BYTES, 'audio_too_large'),))
                audio, duration = _audio(target)
                _check_cancel(cancel_event)
                # A concurrently changed ledger must not return an old answer's
                # audio under a current client binding.
                self._answer(thread_id, run_id, expected_text_sha256)
                return {'status': 'ready', 'mime_type': 'audio/wav',
                        'audio_data_url': 'data:audio/wav;base64,' + base64.b64encode(audio).decode('ascii'),
                        'text_sha256': expected_text_sha256,
                        'audio_sha256': hashlib.sha256(audio).hexdigest(),
                        'byte_length': len(audio), 'duration_seconds': duration,
                        'sample_rate': 22050, 'channels': 1, 'engine': 'macos_say',
                        'voice': voice, 'voice_locale': locale}
        except _RenderFailure as error:
            return {'status': error.status, 'reason': error.reason,
                    'setup_required': error.status == 'unavailable'}
        except (OSError, subprocess.SubprocessError):
            return {'status': 'failed', 'reason': 'local_render_failed', 'setup_required': False}
        finally:
            _RENDER_LOCK.release()
