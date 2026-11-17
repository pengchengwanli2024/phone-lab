"""Bounded content-addressed reuse of local FFmpeg clips, never provider calls."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import re
import uuid

import creative_tools
from research import canonical, digest

MAX_CLIP = 32 * 1024 * 1024
MAX_ENTRIES = 256


class ShotCache:
    def __init__(self, studio):
        self.studio = studio
        self.base = studio.root / '.shot-cache'
        try:
            budget = int(os.environ.get('COMMERCE_CREATIVE_SHOT_CACHE_MB', '128'))
            self.limit = min(512, max(0, budget)) * 1024 * 1024
        except ValueError:
            self.limit = 0
        self.tool_hash = None

    def key(self, project, recipe):
        if not self.limit: return ''
        if self.tool_hash is None:
            try:
                hasher = hashlib.sha256()
                with open(creative_tools.command('ffmpeg'), 'rb') as tool:
                    while data := tool.read(1024 * 1024): hasher.update(data)
                self.tool_hash = hasher.hexdigest()
            except (OSError, ValueError):
                self.limit = 0; return ''
        return digest(canonical({'schema': 'local-shot-v1', 'project_id': project,
                                 'ffmpeg_binary_sha256': self.tool_hash, 'recipe': recipe}))

    @contextmanager
    def _locked(self):
        if not self.limit or self.base.is_symlink(): raise OSError('cache_unavailable')
        self.base.mkdir(mode=0o700, exist_ok=True)
        if self.base.is_symlink(): raise OSError('cache_unavailable')
        fd = os.open(self.base / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def _read(self, path, limit):
        if path.is_symlink() or not 0 < path.stat().st_size <= limit: raise OSError('cache_unavailable')
        with path.open('rb') as file: data = file.read(limit + 1)
        if len(data) > limit: raise OSError('cache_unavailable')
        return data

    def restore(self, project, key, destination, expected):
        if not re.fullmatch('[0-9a-f]{64}', key): return None
        copied = False
        try:
            with self._locked():
                record = json.loads(self._read(self.base / (key + '.json'), 4096))
                if record.get('project_id') != project or record.get('key') != key: return None
                data = self._read(self.base / (key + '.mp4'), MAX_CLIP)
                if len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['clip_sha256']: return None
                if destination.is_symlink() or not destination.resolve().is_relative_to(self.studio.folder(project).resolve()): return None
                destination.write_bytes(data); destination.chmod(0o600); copied = True
                observed = self.studio.probe(destination)
                if any(observed[k] != expected[k] for k in ('width', 'height', 'has_audio')) or abs(observed['duration_seconds'] - expected['duration_seconds']) > .1:
                    raise ValueError('cache_media_mismatch')
                os.utime(self.base / (key + '.mp4'), None)
                return {'key': key, 'clip_sha256': record['clip_sha256'],
                        'origin_job_id': record['job_id']}
        except (OSError, ValueError, KeyError, TypeError):
            if copied: destination.unlink(missing_ok=True)
            return None

    def store(self, project, key, source, job_id):
        if not re.fullmatch('[0-9a-f]{64}', key): return False
        temporary = []
        try:
            data = self._read(source, MAX_CLIP)
            if len(data) > self.limit: return False
            with self._locked():
                clips = [p for p in self.base.glob('*.mp4') if re.fullmatch(r'[0-9a-f]{64}\.mp4', p.name) and not p.is_symlink() and p.stem != key]
                clips.sort(key=lambda p: p.stat().st_mtime_ns)
                total = sum(p.stat().st_size for p in clips)
                while clips and (total + len(data) > self.limit or len(clips) >= MAX_ENTRIES):
                    oldest = clips.pop(0); total -= oldest.stat().st_size
                    oldest.unlink(); oldest.with_suffix('.json').unlink(missing_ok=True)
                record = {'key': key, 'project_id': project, 'job_id': job_id,
                          'clip_sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
                for extension, content in (('.mp4', data), ('.json', canonical(record).encode())):
                    tmp = self.base / ('.tmp-' + uuid.uuid4().hex)
                    temporary.append(tmp); tmp.write_bytes(content); tmp.chmod(0o600)
                    os.replace(tmp, self.base / (key + extension))
                return True
        except (OSError, ValueError, TypeError):
            return False
        finally:
            for path in temporary: path.unlink(missing_ok=True)
