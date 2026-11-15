"""Real synthetic bytes, localhost HTTP and ffprobe; never cloud or daily data."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from creative_studio import CreativeStudio


class MediaOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = tempfile.TemporaryDirectory()
        cls.formats = {}
        for suffix in ('png', 'jpg', 'mp4', 'webm'):
            path = Path(cls.fixtures.name) / ('synthetic.' + suffix)
            args = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=blue:size=64x64:rate=10']
            args += ['-frames:v', '1', '-update', '1'] if suffix in ('png', 'jpg') else ['-t', '1', '-c:v', 'libx264' if suffix == 'mp4' else 'libvpx']
            subprocess.run(args + [str(path)], capture_output=True, timeout=15, check=True)
            cls.formats[suffix] = path.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.fixtures.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'private' / 'output'
        self.studio = CreativeStudio.__new__(CreativeStudio)
        self.on_get = None
        self.hits = []
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                outer.hits.append((self.path, dict(self.headers)))
                if outer.on_get: outer.on_get()
                raw = outer.formats['png']
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers(); self.wfile.write(raw)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.config = {'provider': 'local', 'base_url': self.url}

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.worker.join(2)
        self.tmp.cleanup()

    def retrieve(self, outputs, kind='image', **kwargs):
        from media_outputs import retrieve
        return retrieve(self.studio, self.folder, kind, outputs, config=self.config, **kwargs)

    def encoded(self, suffix='png'):
        return {'base64': base64.b64encode(self.formats[suffix]).decode()}

    def test_real_formats_produce_exact_bytes_hashes_and_private_files(self):
        for suffix, kind in [('png', 'image'), ('jpg', 'image'), ('mp4', 'video'), ('webm', 'video')]:
            with self.subTest(suffix=suffix):
                result = self.retrieve([self.encoded(suffix)], kind, duration_seconds=1 if kind == 'video' else None)
                artifact = result['artifacts'][0]
                path = self.folder / artifact['filename']
                self.assertEqual(path.read_bytes(), self.formats[suffix])
                self.assertEqual(artifact['sha256'], hashlib.sha256(self.formats[suffix]).hexdigest())
                self.assertEqual(artifact['size'], len(self.formats[suffix]))
                self.assertEqual(artifact['media']['width'], 64)
                self.assertEqual(artifact['media']['height'], 64)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(self.folder.stat().st_mode), 0o700)
                canonical = json.dumps(result['artifacts'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                self.assertEqual(result['result_sha256'], hashlib.sha256(canonical.encode()).hexdigest())

    def test_http_download_uses_real_bounded_transport_without_ambient_auth(self):
        result = self.retrieve([{'url': self.url + '/synthetic.png'}])
        self.assertEqual((self.folder / result['artifacts'][0]['filename']).read_bytes(), self.formats['png'])
        self.assertNotIn('Authorization', self.hits[0][1])
        self.assertNotIn('Cookie', self.hits[0][1])

    def test_cancellation_during_http_download_writes_no_output(self):
        cancelled = threading.Event()
        self.on_get = cancelled.set
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            self.retrieve([{'url': self.url + '/synthetic.png'}], cancelled=cancelled.is_set)
        self.assertEqual(len(self.hits), 1)
        self.assertFalse(list(self.folder.glob('*')))

    def test_cancellation_before_retrieval_performs_no_http_or_file_write(self):
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            self.retrieve([{'url': self.url + '/synthetic.png'}], cancelled=lambda: True)
        self.assertEqual(self.hits, [])
        self.assertFalse(self.folder.exists())

    def test_cancellation_during_probe_does_not_return_success(self):
        cancelled = threading.Event()
        real_probe = self.studio.probe
        def probe(path):
            media = real_probe(path); cancelled.set(); return media
        self.studio.probe = probe
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            self.retrieve([self.encoded()], cancelled=cancelled.is_set)

    def test_cancellation_during_actual_decode_does_not_return_success(self):
        cancelled = threading.Event()
        real_run = self.studio.run
        def run(argv, timeout=40):
            result = real_run(argv, timeout)
            if argv[0] == 'ffmpeg': cancelled.set()
            return result
        self.studio.run = run
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            self.retrieve([self.encoded('mp4')], 'video', cancelled=cancelled.is_set)

    def test_output_limit_applies_to_combined_bytes(self):
        with self.assertRaisesRegex(ValueError, 'output_too_large'):
            self.retrieve([self.encoded(), self.encoded()], max_output_bytes=len(self.formats['png']) * 2 - 1)

    def test_http_output_exceeding_limit_does_not_write_files(self):
        with self.assertRaisesRegex(ValueError, 'response_too_large'):
            self.retrieve([{'url': self.url + '/synthetic.png'}], max_output_bytes=len(self.formats['png']) - 1)
        self.assertFalse(list(self.folder.glob('*')))

    def test_missing_and_excess_outputs_are_rejected(self):
        for outputs in ([], [self.encoded(), self.encoded()]):
            with self.subTest(count=len(outputs)), self.assertRaisesRegex(ValueError, 'no_valid_output_or_output_limit'):
                self.retrieve(outputs, max_outputs=1)

    def test_response_metadata_and_magic_bytes_do_not_prove_valid_media(self):
        for output in ({'url': ''}, {'base64': 'not base64!'}, {'base64': base64.b64encode(b'\x89PNG\r\n\x1a\ninvalid').decode()}, {'base64': base64.b64encode(b'<html>success</html>').decode()}):
            with self.subTest(output=output), self.assertRaises(ValueError):
                self.retrieve([output])

    def test_mp4_metadata_without_encoded_frames_is_not_valid_output(self):
        source = self.formats['mp4']; kept = []; offset = 0; removed = 0
        while offset < len(source):
            size = int.from_bytes(source[offset:offset + 4], 'big')
            self.assertGreaterEqual(size, 8)
            box = source[offset:offset + size]
            if box[4:8] == b'mdat': removed += 1
            else: kept.append(box)
            offset += size
        self.assertEqual(removed, 1)
        corrupt = b''.join(kept)
        path = self.root / 'metadata-only.mp4'; path.write_bytes(corrupt)
        media = self.studio.probe(path)
        self.assertEqual((media['width'], media['height'], media['duration_seconds']), (64, 64, 1.0))
        with self.assertRaises(ValueError):
            self.retrieve([{'base64': base64.b64encode(corrupt).decode()}], 'video')

    def test_wrong_media_kind_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'media_format_unsupported'):
            self.retrieve([self.encoded('mp4')])

    def test_video_duration_is_optional_but_enforced_when_provided(self):
        self.retrieve([self.encoded('mp4')], 'video')
        self.retrieve([self.encoded('mp4')], 'video', duration_seconds=.66)
        self.retrieve([self.encoded('mp4')], 'video', duration_seconds=1.34)
        for duration in (.64, 1.36):
            with self.subTest(duration=duration), self.assertRaisesRegex(ValueError, 'duration_mismatch'):
                self.retrieve([self.encoded('mp4')], 'video', duration_seconds=duration)

    def test_symlink_folder_and_parent_cannot_redirect_private_writes(self):
        outside = self.root / 'outside'; outside.mkdir()
        for link in (self.folder, self.folder.parent):
            with self.subTest(link=link):
                link.parent.mkdir(exist_ok=True)
                link.symlink_to(outside, target_is_directory=True)
                try:
                    with self.assertRaisesRegex(ValueError, 'unsafe_result_storage'):
                        self.retrieve([self.encoded()])
                    self.assertEqual(list(outside.iterdir()), [])
                finally:
                    link.unlink()
                    if link == self.folder: link.parent.rmdir()

    def test_existing_output_symlink_cannot_overwrite_target(self):
        self.folder.mkdir(parents=True)
        target = self.root / 'untouched'; target.write_bytes(b'private sentinel')
        (self.folder / '0.png').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'unsafe_result_storage'):
            self.retrieve([self.encoded()])
        self.assertEqual(target.read_bytes(), b'private sentinel')

    def test_folder_replaced_during_download_cannot_claim_verified_output(self):
        outside = self.root / 'outside'; outside.mkdir()
        (outside / '0.png').write_bytes(self.formats['png'])
        def replace_folder():
            self.folder.rename(self.root / 'original-private-output')
            self.folder.symlink_to(outside, target_is_directory=True)
        self.on_get = replace_folder
        with self.assertRaisesRegex(ValueError, 'unsafe_result_storage'):
            self.retrieve([{'url': self.url + '/synthetic.png'}])
        self.assertEqual((outside / '0.png').read_bytes(), self.formats['png'])

    def test_existing_output_hardlink_cannot_overwrite_private_target(self):
        self.folder.mkdir(parents=True)
        target = self.root / 'untouched'; target.write_bytes(b'private sentinel')
        os.link(target, self.folder / '0.png')
        with self.assertRaisesRegex(ValueError, 'unsafe_result_storage'):
            self.retrieve([self.encoded()])
        self.assertEqual(target.read_bytes(), b'private sentinel')

    def test_preexisting_public_modes_are_tightened(self):
        self.folder.mkdir(parents=True, mode=0o755)
        path = self.folder / '0.png'; path.write_bytes(b'old'); path.chmod(0o644)
        self.retrieve([self.encoded()])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.folder.stat().st_mode), 0o700)


if __name__ == '__main__': unittest.main()
