"""Bounded media retrieval and verification without job or database state."""
import base64
import binascii
import errno
import hashlib
import math
import os
from pathlib import Path
import stat

from research import canonical, digest
from media_providers.transport import request


_STORAGE_ERROR = 'media_provider_unsafe_result_storage'


def _private_folder(folder):
    """Pin each directory before descending; never follow user-controlled links."""
    folder = Path(os.path.abspath(folder))
    flags = os.O_RDONLY | os.O_DIRECTORY
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(folder.anchor, flags)
    try:
        parts = folder.parts[1:]
        if not parts: raise ValueError(_STORAGE_ERROR)
        for index, part in enumerate(parts):
            try:
                child = os.open(part, flags | nofollow, dir_fd=descriptor)
            except FileNotFoundError:
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
                child = os.open(part, flags | nofollow, dir_fd=descriptor)
            except OSError as error:
                # macOS /var and /tmp are root-owned aliases. Only immutable,
                # root-owned ancestors may resolve this way; never the output dir.
                parent = os.fstat(descriptor)
                link = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                if (error.errno not in (errno.ELOOP, errno.ENOTDIR) or index == len(parts) - 1
                        or not stat.S_ISLNK(link.st_mode) or link.st_uid != 0
                        or parent.st_uid != 0 or parent.st_mode & 0o022):
                    raise ValueError(_STORAGE_ERROR) from None
                child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor); descriptor = child
        os.fchmod(descriptor, 0o700)
        return folder, descriptor
    except (OSError, ValueError):
        os.close(descriptor)
        raise ValueError(_STORAGE_ERROR) from None


def retrieve(studio, folder, media_kind, outputs, *, config, max_output_bytes=33554432,
             max_outputs=8, duration_seconds=None, api_key='', cancelled=lambda: False):
    """Return verified private artifacts; acceptance and adoption belong to callers.

    A cancelled retrieval raises ValueError and never returns a success receipt.
    Already staged bytes may remain private for caller-managed cleanup/recovery.
    """
    def check_cancelled():
        if cancelled(): raise ValueError('media_provider_cancelled_before_adoption')

    check_cancelled()
    if (type(max_output_bytes) is not int or max_output_bytes <= 0
            or type(max_outputs) is not int or max_outputs <= 0
            or not isinstance(outputs, list) or not outputs or len(outputs) > max_outputs):
        raise ValueError('media_provider_no_valid_output_or_output_limit')
    if media_kind not in ('image', 'video'): raise ValueError('media_provider_output_media_format_unsupported')
    if duration_seconds is not None and (isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, (int, float)) or not math.isfinite(duration_seconds) or duration_seconds <= 0):
        raise ValueError('media_provider_output_duration_mismatch')
    folder, directory = _private_folder(folder)
    artifacts = []; total = 0
    try:
        for index, output in enumerate(outputs):
            check_cancelled()
            if not isinstance(output, dict): raise ValueError('media_provider_no_valid_output')
            if 'base64' in output:
                if not isinstance(output['base64'], str) or len(output['base64']) > (max_output_bytes * 4 // 3 + 8):
                    raise ValueError('media_provider_output_too_large')
                try: raw = base64.b64decode(output['base64'], validate=True)
                except (ValueError, binascii.Error): raise ValueError('media_provider_invalid_base64_output') from None
            elif output.get('url'):
                raw = request(config, 'GET', url=output['url'], limit=max_output_bytes, api_key=api_key)
            else: raise ValueError('media_provider_no_valid_output')
            check_cancelled()
            total += len(raw)
            if not raw or total > max_output_bytes: raise ValueError('media_provider_output_too_large')
            image = media_kind == 'image'
            suffix = '.png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else '.jpg' if raw.startswith(b'\xff\xd8\xff') else '.mp4' if raw[4:8] == b'ftyp' else '.webm' if raw.startswith(b'\x1aE\xdf\xa3') else None
            if suffix is None or (image and suffix not in ('.png', '.jpg')) or (not image and suffix not in ('.mp4', '.webm')):
                raise ValueError('media_provider_output_media_format_unsupported')
            path = folder / (str(index) + suffix)
            check_cancelled()
            try:
                pinned = os.fstat(directory); current = folder.stat()
                if folder.is_symlink() or (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
                    raise ValueError(_STORAGE_ERROR)
                fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0), 0o600, dir_fd=directory)
                with os.fdopen(fd, 'wb') as file:
                    info = os.fstat(file.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise ValueError(_STORAGE_ERROR)
                    os.fchmod(file.fileno(), 0o600)
                    os.ftruncate(file.fileno(), 0)
                    file.write(raw)
            except OSError: raise ValueError(_STORAGE_ERROR) from None
            check_cancelled()
            media = studio.probe(path)
            check_cancelled()
            try:
                current = folder.stat(); written = path.lstat()
                if (folder.is_symlink() or (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino)
                        or (written.st_dev, written.st_ino) != (info.st_dev, info.st_ino)
                        or not stat.S_ISREG(written.st_mode) or written.st_nlink != 1):
                    raise ValueError(_STORAGE_ERROR)
            except OSError: raise ValueError(_STORAGE_ERROR) from None
            if media['width'] <= 0 or media['height'] <= 0 or (not image and media['duration_seconds'] <= 0):
                raise ValueError('media_provider_output_not_valid_media')
            if not image and duration_seconds is not None and abs(media['duration_seconds'] - duration_seconds) > .35:
                raise ValueError('media_provider_output_duration_mismatch')
            # Container headers can retain plausible dimensions/duration after all
            # encoded frames are removed. Decode every stream before accepting it.
            # Null output, one decoder/filter thread, pixel/allocation limits and
            # a wall-clock timeout keep verification bounded and avoid new files.
            check_cancelled()
            try:
                studio.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-err_detect', 'explode',
                            '-max_alloc', '67108864', '-max_pixels', '16777216', '-threads', '1',
                            '-filter_threads', '1', '-protocol_whitelist', 'file', '-i', path,
                            '-map', '0:v:0', '-map', '0:a?', '-sn', '-dn', '-abort_on', 'empty_output',
                            '-threads', '1', '-f', 'null', '-'], timeout=20)
            finally:
                check_cancelled()
            try:
                current = folder.stat(); written = path.lstat()
                if (folder.is_symlink() or (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino)
                        or (written.st_dev, written.st_ino) != (info.st_dev, info.st_ino)
                        or not stat.S_ISREG(written.st_mode) or written.st_nlink != 1):
                    raise ValueError(_STORAGE_ERROR)
            except OSError: raise ValueError(_STORAGE_ERROR) from None
            artifacts.append({'filename': path.name, 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw), 'media': media, 'index': index})
        check_cancelled()
        return {'artifacts': artifacts, 'result_sha256': digest(canonical(artifacts))}
    finally:
        os.close(directory)
