"""Synthetic local HTTP acceptance; never calls a paid provider or daily state."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from creative_studio import CreativeStudio
from creative_workflow import CreativeWorkflow
from creative_direction import DIRECTION_FIELDS


class MediaProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.requests = []
        self.mode = 'ok'
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                outer.requests.append(('GET', self.path, dict(self.headers), None))
                if self.path == '/health': return self.reply({'ok': True})
                if self.path == '/system_stats': return self.reply({'system': {'os': 'synthetic'}})
                if self.path.startswith('/view?') or self.path == '/result.png':
                    if outer.mode == 'block_result':
                        outer.entered.set(); outer.release.wait(5)
                    if getattr(outer, 'on_result', None):
                        callback = outer.on_result; outer.on_result = None; callback()
                    self.send_response(200); self.end_headers(); self.wfile.write(outer.image); return
                if self.path == '/result.mp4':
                    self.send_response(200); self.end_headers(); self.wfile.write(outer.video); return
                if self.path == '/contents/generations/tasks/remote-1':
                    return self.reply({'id': 'remote-1', 'status': 'succeeded', 'content': {'video_url': outer.url + '/result.mp4'}})
                if self.path == '/api/v1/tasks/remote-1':
                    return self.reply({'output': {'task_id': 'remote-1', 'task_status': 'SUCCEEDED', 'video_url': outer.url + '/result.mp4'}})
                if self.path == '/v2/query/video_generation/remote-1':
                    return self.reply({'task': {'task_id': 'remote-1', 'status': 'succeeded', 'content': {'url': outer.url + '/result.mp4'}}})
                if self.path.startswith('/history/'):
                    return self.reply({'remote-1': {'status': {'completed': True, 'status_str': 'success'}, 'outputs': {'9': {'images': [{'filename': 'synthetic.png', 'subfolder': '', 'type': 'output'}]}}}})
                if self.path == '/jobs/remote-1':
                    if outer.mode == 'pending': return self.reply({'id': 'remote-1', 'status': 'running'})
                    if outer.mode == 'fake': return self.reply({'id': 'remote-1', 'status': 'succeeded', 'outputs': []})
                    if outer.mode == 'video': return self.reply({'id': 'remote-1', 'status': 'succeeded', 'outputs': [{'url': outer.url + '/result.mp4'}]})
                    return self.reply({'id': 'remote-1', 'status': 'succeeded', 'outputs': [{'url': outer.url + '/result.png'}]})
                self.send_response(404); self.end_headers()

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                data = json.loads(body) if self.headers.get('Content-Type', '').startswith('application/json') else body
                outer.requests.append(('POST', self.path, dict(self.headers), data))
                if self.path == '/upload/image': return self.reply({'name': 'input.png', 'subfolder': '', 'type': 'input'})
                if self.path == '/prompt': return self.reply({'prompt_id': 'remote-1', 'number': 0, 'node_errors': {}})
                if self.path == '/jobs':
                    if outer.mode == 'block_submit' and len([r for r in outer.requests if r[:2] == ('POST', '/jobs')]) == 1:
                        outer.entered.set(); outer.release.wait(5)
                    if outer.mode == 'disconnect': self.connection.close(); return
                    if outer.mode == 'sync': return self.reply({'status': 'succeeded', 'outputs': [{'base64': base64.b64encode(outer.image).decode()}]})
                    return self.reply({'id': 'remote-1', 'status': 'pending'})
                if self.path == '/images/generations': return self.reply({'data': [{'b64_json': base64.b64encode(outer.image).decode()}]})
                if self.path == '/contents/generations/tasks': return self.reply({'id': 'remote-1'})
                if self.path == '/api/v1/services/aigc/video-generation/video-synthesis': return self.reply({'output': {'task_id': 'remote-1', 'task_status': 'PENDING'}})
                if self.path == '/v2/video_generation': return self.reply({'task_id': 'remote-1'})
                self.send_response(404); self.end_headers()

            def reply(self, data):
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps(data).encode())

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.service = SimpleNamespace(core=Core(self.root / 'state.sqlite'), state=self.root)
        self.service.creative = CreativeStudio(self.service.core, self.root)
        self.service.media = CreativeWorkflow(self.service)
        self.studio = self.service.creative
        self.project = self.studio.create({'synthetic': True, 'product': {'name': '合成商品', 'verified_facts': [{'id': 'f1', 'text': '合成规格', 'evidence_ref': 'synthetic:spec'}]}}, 'synthetic')
        path = self.root / 'fixture.png'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=blue:size=64x64', '-frames:v', '1', '-update', '1', str(path)], capture_output=True, timeout=15, check=True)
        self.image = path.read_bytes()
        self.asset = self.studio.register(self.project['id'], 'product_image', path, {'origin': 'synthetic_test', 'media': self.studio.probe(path)})['id']
        path = self.root / 'reference.png'; path.write_bytes(self.image)
        reference = self.studio.register(self.project['id'], 'reference_image', path, {'origin': 'synthetic_test', 'media': self.studio.probe(path)})['id']
        self.project = self.service.media.direction_save(self.project['id'], '1', {k: '合成参考拆解' for k in DIRECTION_FIELDS}, [reference])
        self.request = self.service.media.request_create(self.project['id'], self.project['revision'], 'product_main', 'request')

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2); self.tmp.cleanup()

    def providers(self):
        from media_providers import MediaProviders
        if not hasattr(self, 'registry'): self.registry = MediaProviders(self.service)
        return self.registry

    def config(self, **changes):
        return {'label': 'Synthetic local', 'provider': 'local', 'adapter': 'generic_json_async', 'base_url': self.url,
                'model': 'synthetic-image', 'media_kind': 'image', 'enabled': True, 'capabilities': {'image_input': True},
                'protocol': {'probe_path': '/health', 'submit_path': '/jobs', 'poll_path': '/jobs/{{task_id}}',
                             'submit_body': {'model': '{{model}}', 'prompt': '{{prompt}}', 'images': '{{images}}'},
                             'task_id_path': 'id', 'status_path': 'status', 'outputs_path': 'outputs', 'output_url_path': 'url'}, **changes}

    def configured(self, **changes):
        p = self.providers().configure(self.config(**changes))
        return self.providers().test_profile(p['id'], p['revision'])

    def generate(self, profile, **changes):
        return self.providers().generate(self.request['id'], profile['id'], profile['revision'], [self.asset], 'generate', **changes)

    def test_feature_has_configurable_real_provider_layer(self):
        try:
            from media_providers import MediaProviders
        except ImportError:
            self.fail('Configurable MediaProviders service is missing')
        self.assertTrue(callable(MediaProviders))

    def test_generic_real_http_registers_verified_asset_and_attaches_request(self):
        p = self.configured(); job = self.generate(p)
        self.assertEqual(job['status'], 'pending'); self.assertFalse(job['external_generation_submitted'])
        self.providers().tick(); self.providers().tick(at=job['created_at'] + 60)
        done = self.providers().get(job['id'])
        self.assertEqual(done['status'], 'succeeded', done)
        self.assertEqual(done['review_status'], 'awaiting_review'); self.assertEqual(len(done['assets']), 1)
        self.assertEqual(self.service.media.request_get(self.request['id'])['status'], 'awaiting_review')
        asset = done['assets'][0]; self.assertEqual(asset['kind'], 'generated_image')
        self.assertEqual(asset['sha256'], hashlib.sha256(self.image).hexdigest())
        submit = next(r for r in self.requests if r[:2] == ('POST', '/jobs'))
        self.assertTrue(submit[3]['images'][0]['data_uri'].startswith('data:image/png;base64,'))
        self.assertIn('产品：合成商品', submit[3]['prompt'])
        self.assertEqual(self.generate(p)['id'], job['id'])
        self.providers().tick(at=job['created_at'] + 120)
        self.assertEqual(len([r for r in self.requests if r[:2] == ('POST', '/jobs')]), 1)

    def test_submit_disconnect_becomes_unknown_and_never_retries(self):
        p = self.configured(); self.mode = 'disconnect'; job = self.generate(p)
        self.providers().tick(); self.providers().recover(); self.providers().tick(at=job['created_at'] + 60)
        self.assertEqual(self.providers().get(job['id'])['status'], 'unknown')
        self.assertEqual(len([r for r in self.requests if r[:2] == ('POST', '/jobs')]), 1)

    def test_completion_without_real_files_does_not_claim_success(self):
        p = self.configured(); self.mode = 'fake'; job = self.generate(p)
        self.providers().tick(); self.providers().tick(at=job['created_at'] + 60)
        done = self.providers().get(job['id']); self.assertEqual(done['status'], 'failed'); self.assertEqual(done['assets'], [])
        self.assertEqual(self.service.media.request_get(self.request['id'])['status'], 'awaiting_media')

    def test_profile_revision_change_blocks_unsubmitted_work(self):
        p = self.configured(); job = self.generate(p)
        self.providers().configure(self.config(id=p['id'], expected_revision=p['revision'], label='Changed'))
        self.providers().tick()
        self.assertEqual(self.providers().get(job['id'])['stage'], 'blocked')
        self.assertFalse(any(r[0] == 'POST' for r in self.requests))

    def test_stale_direction_blocks_execution(self):
        p = self.configured(); job = self.generate(p)
        current = self.studio.get(self.project['id']); brief = current['brief']; brief['target'] = {'country': 'changed'}
        self.studio.save(current['id'], brief, current['revision'], allow_direction=True)
        self.providers().tick(); self.assertEqual(self.providers().get(job['id'])['stage'], 'blocked')
        self.assertFalse(any(r[0] == 'POST' for r in self.requests))

    def test_get_probes_are_read_only_and_secret_is_redacted(self):
        p = self.configured(api_key='synthetic-secret-do-not-use')
        self.assertNotIn('synthetic-secret', json.dumps(p)); self.assertTrue(p['key_configured'])
        self.assertTrue(all(r[0] == 'GET' for r in self.requests))
        secret_files = list((self.root / 'media-provider-credentials').glob('*.json'))
        self.assertEqual(secret_files[0].stat().st_mode & 0o777, 0o600)
        self.assertNotIn('synthetic-secret', json.dumps(self.providers().catalog()))

    def test_comfyui_injects_prompt_and_uploads_product_image(self):
        workflow = {'6': {'class_type': 'CLIPTextEncode', 'inputs': {'text': ''}}, '10': {'class_type': 'LoadImage', 'inputs': {'image': ''}}}
        p = self.configured(adapter='comfyui', protocol={}, workflow=workflow, bindings={'prompt': '6.inputs.text', 'image': '10.inputs.image'}, output_nodes=['9'])
        job = self.generate(p); self.providers().tick(); self.providers().tick(at=job['created_at'] + 60)
        done = self.providers().get(job['id']); self.assertEqual(done['status'], 'succeeded', done)
        prompt = next(r for r in self.requests if r[:2] == ('POST', '/prompt'))[3]['prompt']
        self.assertIn('产品：合成商品', prompt['6']['inputs']['text']); self.assertEqual(prompt['10']['inputs']['image'], 'input.png')
        self.assertTrue(any(r[:2] == ('POST', '/upload/image') for r in self.requests))

    def video_request(self, seconds=4):
        target = self.root / 'fixture.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=blue:size=64x64:rate=5', '-t', str(seconds), '-c:v', 'libx264', str(target)], capture_output=True, timeout=15, check=True)
        self.video = target.read_bytes(); self.mode = 'video'
        self.request = self.service.media.request_create(self.project['id'], self.project['revision'], 'ugc_video', 'video-request')

    def test_short_video_profile_rejects_whole_production_before_submit(self):
        self.video_request()
        p = self.configured(media_kind='video', capabilities={'image_input': True, 'max_duration_seconds': 8})
        with self.assertRaisesRegex(ValueError, 'duration_unsupported'): self.generate(p)
        self.assertFalse(any(r[0] == 'POST' for r in self.requests))

    def test_individual_shot_is_verified_clip_and_never_attached_as_whole_video(self):
        self.video_request()
        p = self.configured(media_kind='video', capabilities={'image_input': True, 'durations_seconds': [4, 6]})
        job = self.generate(p, shot_index=0); self.providers().tick(); self.providers().tick(at=job['created_at'] + 60)
        done = self.providers().get(job['id']); self.assertEqual(done['status'], 'succeeded', done)
        self.assertFalse(done['complete_request_output']); self.assertEqual(done['assets'][0]['shot_index'], 0)
        self.assertAlmostEqual(done['assets'][0]['media']['duration_seconds'], 4, delta=.1)
        self.assertEqual(self.service.media.request_get(self.request['id'])['status'], 'awaiting_media')

    def test_shorter_returned_video_is_failed_not_thirty_second_success(self):
        self.video_request(seconds=2)
        p = self.configured(media_kind='video', capabilities={'image_input': True, 'max_duration_seconds': 30})
        job = self.generate(p); self.providers().tick(); self.providers().tick(at=job['created_at'] + 60)
        done = self.providers().get(job['id']); self.assertEqual(done['status'], 'failed'); self.assertEqual(done['assets'], [])
        self.assertIn('duration_mismatch', done['error'])

    def test_cancel_never_sends_global_comfy_interrupt_or_claims_remote_cancel(self):
        p = self.configured(); job = self.generate(p); self.providers().tick()
        done = self.providers().cancel(job['id']); self.providers().tick(at=job['created_at'] + 60)
        self.assertEqual(done['status'], 'cancelled'); self.assertEqual(done['remote_cancel_status'], 'not_available')
        self.assertEqual(done['cancel_scope'], 'local_result_adoption'); self.assertEqual(done['assets'], [])
        self.assertEqual(len([r for r in self.requests if r[0] == 'POST']), 1)

    def test_recovery_during_submit_is_unknown_without_resubmission(self):
        p = self.configured(); job = self.generate(p)
        with self.service.core.db() as db:
            doc = json.loads(db.execute('SELECT document FROM media_provider_jobs WHERE id=?', (job['id'],)).fetchone()[0])
            doc.update(stage='submitting', status='submitted', external_generation_submitted=True)
            db.execute('UPDATE media_provider_jobs SET document=? WHERE id=?', (json.dumps(doc), job['id']))
        self.providers().recover(); self.providers().tick(at=job['created_at'] + 60)
        self.assertEqual(self.providers().get(job['id'])['status'], 'unknown'); self.assertFalse(any(r[0] == 'POST' for r in self.requests))

    def test_revision_change_after_submit_prevents_result_adoption(self):
        p = self.configured(); job = self.generate(p); self.providers().tick()
        self.providers().configure(self.config(id=p['id'], expected_revision=p['revision'], enabled=False))
        self.providers().tick(at=job['created_at'] + 60)
        done = self.providers().get(job['id']); self.assertEqual(done['stage'], 'blocked'); self.assertEqual(done['assets'], [])

    def test_openai_retired_video_is_rejected_and_lovart_has_no_fabricated_native_endpoint(self):
        with self.assertRaisesRegex(ValueError, 'openai_video_api_unavailable'):
            self.providers().configure(self.config(provider='openai', media_kind='video', base_url='https://api.openai.com/v1', capabilities={'max_duration_seconds': 30}))
        lovart = next(p for p in self.providers().catalog()['providers'] if p['id'] == 'lovart')
        self.assertEqual(lovart['native_adapters'], [])

    def test_native_protocols_use_documented_paths_and_parse_real_http_responses(self):
        from media_providers import adapters
        context = {'model': 'operator-supplied', 'prompt': 'synthetic prompt', 'images': [], 'image_data_uris': ['data:image/png;base64,AAAA'], 'image_data_uri_0': 'data:image/png;base64,AAAA', 'duration_seconds': 4, 'width': 720, 'height': 1280}
        for adapter, submit_path in [('bytedance_ark_image', '/images/generations'), ('bytedance_ark_video', '/contents/generations/tasks'), ('dashscope_wan26_video', '/api/v1/services/aigc/video-generation/video-synthesis'), ('minimax_video_v2', '/v2/video_generation')]:
            with self.subTest(adapter=adapter):
                # Synthetic loopback stand-in exercises the real transport, no cloud request.
                config = {'provider': 'local', 'base_url': self.url, 'adapter': adapter, 'parameters': {}}
                result = adapters.submit(config, context, '')
                if adapter.endswith('_image'):
                    self.assertEqual(result['status'], 'succeeded'); self.assertEqual(base64.b64decode(result['outputs'][0]['base64']), self.image)
                else:
                    self.assertEqual(result['remote_task_id'], 'remote-1')
                    result = adapters.poll(config, 'remote-1', '')
                    self.assertEqual(result['status'], 'succeeded'); self.assertEqual(result['outputs'][0]['url'], self.url + '/result.mp4')
                sent = next(r for r in reversed(self.requests) if r[:2] == ('POST', submit_path))
                self.assertEqual(sent[3]['model'], 'operator-supplied')
                if adapter == 'dashscope_wan26_video':
                    self.assertEqual(sent[2]['X-DashScope-Async'], 'enable'); self.assertEqual(sent[3]['input']['img_url'], 'data:image/png;base64,AAAA')
                if adapter == 'minimax_video_v2': self.assertEqual(sent[3]['response_format'], 'task')

    def test_foreign_local_result_host_is_rejected_before_forwarding_secret(self):
        from media_providers.transport import request
        with self.assertRaisesRegex(ValueError, 'result_url_rejected'):
            request({'provider': 'local', 'base_url': self.url}, 'GET', url='http://127.0.0.1:1/private', api_key='synthetic-secret')

    def test_public_result_fetch_does_not_forward_authorization(self):
        from media_providers.transport import request
        captured = {}
        class Response:
            status = 200
            def __init__(self): self.stream = io.BytesIO(b'actual bytes')
            def getheader(self, name): return None
            def read(self, size): return self.stream.read(size)
        class Connection:
            def __init__(self, *args): pass
            def request(self, method, path, body=None, headers=None): captured.update(headers)
            def getresponse(self): return Response()
            def close(self): pass
        with patch('media_providers.transport.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), patch('media_providers.transport._HTTPS', Connection):
            result = request({'provider': 'custom', 'base_url': 'https://api.example.invalid'}, 'GET', url='https://cdn.example.invalid/image.png', api_key='synthetic-secret')
        self.assertEqual(result, b'actual bytes'); self.assertNotIn('Authorization', captured)

    def test_mixed_public_private_dns_cannot_rebind_to_local_services(self):
        from media_providers.transport import request
        with patch('media_providers.transport.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443)), (2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaisesRegex(ValueError, 'address_rejected'):
                request({'provider': 'custom', 'base_url': 'https://api.example.invalid'}, 'GET', '/health')

    def test_persistent_scoped_job_list_survives_new_registry(self):
        from media_providers import MediaProviders
        p = self.configured(); job = self.generate(p)
        restored = MediaProviders(self.service)
        self.assertEqual([j['id'] for j in restored.jobs(request_id=self.request['id'])['jobs']], [job['id']])
        self.assertEqual(restored.jobs(project_id=self.project['id'])['jobs'][0]['request_id'], self.request['id'])
        with self.assertRaisesRegex(ValueError, 'scope_required'): restored.jobs()

    def test_last_three_second_shot_uses_model_minimum_then_local_composition_can_trim(self):
        self.video_request(seconds=4)
        p = self.configured(media_kind='video', capabilities={'image_input': True, 'min_duration_seconds': 4, 'max_duration_seconds': 8, 'durations_seconds': [4, 6, 8]})
        job = self.generate(p, shot_index=4)
        self.assertEqual(job['requested_duration_seconds'], 3); self.assertEqual(job['submitted_duration_seconds'], 4)
        self.providers().tick(); self.providers().tick(at=job['created_at'] + 60)
        done = self.providers().get(job['id']); self.assertEqual(done['status'], 'succeeded', done)
        self.assertEqual(done['assets'][0]['requested_duration_seconds'], 3)
        self.assertEqual(done['assets'][0]['submitted_duration_seconds'], 4)
        self.assertEqual(self.service.media.request_get(self.request['id'])['status'], 'awaiting_media')

    def test_profile_concurrency_limit_keeps_second_generation_local_until_capacity_frees(self):
        p = self.configured(capabilities={'image_input': True, 'max_concurrent_jobs': 1}); self.mode = 'pending'
        first = self.generate(p)
        second = self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset], 'second-generation')
        self.providers().tick()
        self.assertEqual(len([r for r in self.requests if r[:2] == ('POST', '/jobs')]), 1)
        self.assertFalse(self.providers().get(second['id'])['external_generation_submitted'])
        self.mode = 'ok'; self.providers().tick(at=first['created_at'] + 60)
        self.assertEqual(self.providers().get(first['id'])['status'], 'succeeded')
        self.assertEqual(len([r for r in self.requests if r[:2] == ('POST', '/jobs')]), 2)

    def test_restart_after_synchronous_receipt_recovers_files_without_resubmit(self):
        from media_providers import MediaProviders
        p = self.configured(); self.mode = 'sync'; job = self.generate(p)
        with patch.object(self.providers(), '_download', side_effect=RuntimeError('synthetic abrupt shutdown')):
            with self.assertRaisesRegex(RuntimeError, 'abrupt shutdown'): self.providers().tick()
        restored = MediaProviders(self.service); restored.tick(at=job['created_at'] + 60)
        done = restored.get(job['id']); self.assertEqual(done['status'], 'succeeded'); self.assertEqual(len(done['assets']), 1)
        self.assertEqual(len([r for r in self.requests if r[:2] == ('POST', '/jobs')]), 1)

    def test_native_parameters_cannot_override_frozen_product_or_duration(self):
        with self.assertRaisesRegex(ValueError, 'reserved_parameter'):
            self.providers().configure(self.config(provider='bytedance', adapter='bytedance_ark_video', base_url='https://ark.cn-beijing.volces.com/api/v3', media_kind='video', protocol={}, capabilities={'max_duration_seconds': 15}, parameters={'content': [{'type': 'text', 'text': 'unbound'}]}))

    def test_declared_product_image_support_requires_actual_body_binding(self):
        protocol = self.config()['protocol']; protocol['submit_body'] = {'model': '{{model}}', 'prompt': '{{prompt}}'}
        with self.assertRaisesRegex(ValueError, 'product_image_binding_required'):
            self.providers().configure(self.config(protocol=protocol))

    def test_direction_changed_during_download_holds_bytes_until_explicit_current_reattach(self):
        p = self.configured(); job = self.generate(p); self.providers().tick()
        def change_direction():
            current = self.studio.get(self.project['id']); brief = current['brief']; brief['target'] = {'country': 'new synthetic target'}
            refs = [a['asset_id'] for a in brief['design_direction']['references']]
            saved = self.studio.save(current['id'], brief, current['revision'], allow_direction=True)
            saved = self.service.media.direction_save(saved['id'], saved['revision'], {k: '更新的合成拆解' for k in DIRECTION_FIELDS}, refs)
            self.new_request = self.service.media.request_create(saved['id'], saved['revision'], 'product_main', 'new-current-request')
            self.new_revision = saved['revision']
        self.on_result = change_direction
        self.providers().tick(at=job['created_at'] + 60)
        held = self.providers().get(job['id']); self.assertEqual(held['stage'], 'result_held'); self.assertEqual(held['assets'], [])
        self.assertEqual(self.service.media.request_get(self.request['id'])['assets'], [])
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.providers().reattach(job['id'], self.request['id'], self.new_revision)
        adopted = self.providers().reattach(job['id'], self.new_request['id'], self.new_revision)
        self.assertEqual(adopted['stage'], 'awaiting_review'); self.assertEqual(len(adopted['assets']), 1)
        self.assertEqual(self.service.media.request_get(self.new_request['id'])['status'], 'awaiting_review')
        self.assertEqual(adopted['assets'][0]['creative_request_id'], self.request['id'])

    def test_asset_content_change_after_queue_blocks_paid_submission(self):
        p = self.configured(); job = self.generate(p)
        path, meta, _ = self.studio.asset(self.project['id'], self.asset); path.write_bytes(b'changed bytes')
        self.providers().tick(); done = self.providers().get(job['id'])
        self.assertEqual(done['stage'], 'blocked'); self.assertEqual(done['error'], 'creative_asset_changed')
        self.assertFalse(any(r[0] == 'POST' for r in self.requests))

    def test_unknown_submission_reserves_capacity_without_automatic_second_charge(self):
        p = self.configured(); self.mode = 'disconnect'; first = self.generate(p)
        second = self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset], 'second-after-unknown')
        self.providers().tick(); self.providers().tick(at=first['created_at'] + 60)
        self.assertEqual(self.providers().get(first['id'])['status'], 'unknown')
        self.assertFalse(self.providers().get(second['id'])['external_generation_submitted'])
        self.assertEqual(self.providers().catalog()['profiles'][0]['unresolved_jobs'], 1)
        self.assertEqual(len([r for r in self.requests if r[:2] == ('POST', '/jobs')]), 1)

    def test_missing_private_credential_before_submission_is_failed_without_charge(self):
        p = self.configured(api_key='synthetic-only'); job = self.generate(p)
        next((self.root / 'media-provider-credentials').glob('*.json')).unlink()
        self.providers().tick(); done = self.providers().get(job['id'])
        self.assertEqual(done['status'], 'failed'); self.assertFalse(done['external_generation_submitted'])
        self.assertFalse(any(r[0] == 'POST' for r in self.requests))

    def second_image(self):
        path = self.root / 'second-product.png'; path.write_bytes(self.image)
        return self.studio.register(self.project['id'], 'product_image', path, {'origin': 'synthetic_test', 'media': self.studio.probe(path)})['id']

    def test_default_single_image_limit_rejects_multiple_inputs_before_submission(self):
        p = self.configured(); second = self.second_image()
        with self.assertRaisesRegex(ValueError, 'input_image_limit_exceeded'):
            self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset, second], 'two-inputs')
        self.assertFalse(any(r[0] == 'POST' for r in self.requests))

    def test_generic_explicit_two_image_cap_sends_both_actual_inputs(self):
        p = self.configured(capabilities={'image_input': True, 'max_input_images': 2}); second = self.second_image()
        job = self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset, second], 'two-inputs')
        self.providers().tick()
        body = next(r[3] for r in self.requests if r[:2] == ('POST', '/jobs'))
        self.assertEqual([image['asset_id'] for image in body['images']], [self.asset, second])
        self.assertTrue(self.providers().get(job['id'])['external_generation_submitted'])

    def test_native_video_caps_cannot_claim_multiple_image_support(self):
        for provider, adapter, base in [('bytedance', 'bytedance_ark_video', 'https://ark.cn-beijing.volces.com/api/v3'), ('alibaba', 'dashscope_wan26_video', 'https://workspace.example.invalid'), ('minimax', 'minimax_video_v2', 'https://api.minimax.io')]:
            with self.subTest(adapter=adapter):
                with self.assertRaisesRegex(ValueError, 'adapter_input_image_limit'):
                    self.providers().configure(self.config(provider=provider, adapter=adapter, base_url=base, media_kind='video', protocol={}, capabilities={'max_duration_seconds': 15, 'max_input_images': 2}))

    def test_native_video_rejects_two_images_instead_of_silently_using_first(self):
        self.video_request(); second = self.second_image()
        for provider, adapter, base in [('bytedance', 'bytedance_ark_video', 'https://ark.cn-beijing.volces.com/api/v3'), ('alibaba', 'dashscope_wan26_video', 'https://workspace.example.invalid'), ('minimax', 'minimax_video_v2', 'https://api.minimax.io')]:
            with self.subTest(adapter=adapter):
                p = self.configured(provider=provider, adapter=adapter, base_url=base, media_kind='video', protocol={}, capabilities={'max_duration_seconds': 15})
                self.assertEqual(p['capabilities']['max_input_images'], 1)
                with self.assertRaisesRegex(ValueError, 'input_image_limit_exceeded'):
                    self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset, second], 'two-' + adapter, shot_index=0)
        self.assertFalse(any(r[0] == 'POST' for r in self.requests))

    def test_comfyui_rejects_two_images_with_declared_single_input_cap(self):
        workflow = {'6': {'class_type': 'CLIPTextEncode', 'inputs': {'text': ''}}, '10': {'class_type': 'LoadImage', 'inputs': {'image': ''}}}
        p = self.configured(adapter='comfyui', protocol={}, workflow=workflow, bindings={'prompt': '6.inputs.text', 'image': '10.inputs.image'}, output_nodes=['9'])
        self.assertEqual(p['capabilities']['max_input_images'], 1)
        with self.assertRaisesRegex(ValueError, 'input_image_limit_exceeded'):
            self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset, self.second_image()], 'two-comfy')
        self.assertFalse(any(r[0] == 'POST' for r in self.requests))

    def test_generic_multi_image_cap_requires_actual_mapping_for_every_image(self):
        protocol = self.config()['protocol']; protocol['submit_body']['images'] = '{{image_data_uri_0}}'
        with self.assertRaisesRegex(ValueError, 'product_image_binding_required'):
            self.providers().configure(self.config(protocol=protocol, capabilities={'image_input': True, 'max_input_images': 2}))

    def test_native_image_adapter_accepts_multiple_images_with_truthful_catalog_cap(self):
        p = self.configured(provider='bytedance', adapter='bytedance_ark_image', base_url='https://ark.cn-beijing.volces.com/api/v3', protocol={}, capabilities={'max_input_images': 2})
        job = self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset, self.second_image()], 'two-ark-images')
        self.assertEqual(len(job['source_assets']), 2)
        catalog = self.providers().catalog()
        self.assertEqual(catalog['profiles'][0]['capabilities']['max_input_images'], 2)
        examples = {a['id']: a['configuration_example']['capabilities']['max_input_images'] for a in catalog['adapters']}
        self.assertEqual(examples['bytedance_ark_image'], 8)
        self.assertEqual(examples['comfyui'], 1); self.assertEqual(examples['minimax_video_v2'], 1)

    def test_cancel_of_queued_job_is_persisted_while_another_submit_is_in_flight(self):
        p = self.configured(capabilities={'max_concurrent_jobs': 2}); first = self.generate(p)
        second = self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset], 'cancel-queued')
        self.mode = 'block_submit'; self.entered = threading.Event(); self.release = threading.Event(); cancelled = threading.Event()
        worker = threading.Thread(target=self.providers().tick); worker.start()
        canceller = None
        try:
            self.assertTrue(self.entered.wait(2))
            def cancel():
                self.providers().cancel(second['id']); cancelled.set()
            canceller = threading.Thread(target=cancel); canceller.start()
            self.assertTrue(cancelled.wait(.5), 'Cancellation must not wait for another job network call')
        finally:
            self.release.set(); worker.join(5)
            if canceller: canceller.join(5)
        self.assertEqual(self.providers().get(second['id'])['status'], 'cancelled')
        self.assertEqual(len([r for r in self.requests if r[:2] == ('POST', '/jobs')]), 1)

    def test_stop_during_result_download_keeps_files_pending_until_restart_without_attachment(self):
        from media_providers import MediaProviders
        p = self.configured(); job = self.generate(p); self.providers().tick()
        self.mode = 'block_result'; self.entered = threading.Event(); self.release = threading.Event()
        worker = threading.Thread(target=lambda: self.providers().tick(at=job['created_at'] + 60)); worker.start()
        try:
            self.assertTrue(self.entered.wait(2)); self.providers().stop()
        finally:
            self.release.set(); worker.join(5)
        stopped = self.providers().get(job['id'])
        self.assertEqual(stopped['status'], 'pending'); self.assertEqual(stopped['stage'], 'output_ready'); self.assertEqual(stopped['assets'], [])
        self.assertEqual(self.service.media.request_get(self.request['id'])['status'], 'awaiting_media')
        restarted = MediaProviders(self.service)
        self.assertEqual(restarted.get(job['id'])['stage'], 'awaiting_review')
        self.assertEqual(len([r for r in self.requests if r[:2] == ('POST', '/jobs')]), 1)

    def test_cancel_during_result_download_is_sticky_and_prevents_adoption(self):
        from media_providers import MediaProviders
        p = self.configured(); job = self.generate(p); self.providers().tick()
        self.mode = 'block_result'; self.entered = threading.Event(); self.release = threading.Event(); cancelled = threading.Event()
        worker = threading.Thread(target=lambda: self.providers().tick(at=job['created_at'] + 60)); worker.start(); canceller = None
        try:
            self.assertTrue(self.entered.wait(2))
            def cancel():
                self.providers().cancel(job['id']); cancelled.set()
            canceller = threading.Thread(target=cancel); canceller.start()
            self.assertTrue(cancelled.wait(.5), 'Cancellation intent must persist before download completes')
        finally:
            self.release.set(); worker.join(5)
            if canceller: canceller.join(5)
        done = self.providers().get(job['id']); self.assertEqual(done['status'], 'cancelled'); self.assertEqual(done['assets'], [])
        self.assertEqual(self.service.media.request_get(self.request['id'])['status'], 'awaiting_media')
        self.assertEqual(MediaProviders(self.service).get(job['id'])['status'], 'cancelled')

    def owner_run(self):
        """Actual owning tables, with a synthetic authorized run and pinned version."""
        task=self.service.core.invoke('commerce_task_create',{'kind':'analysis','input':{'synthetic':True},'idempotency_key':'synthetic-owner-task'})
        owner = {'task_id': task['id'],'id': 'synthetic-owner', 'version': 1, 'status': 'running', 'test': False, 'pins': {'synthetic-extension': {'version': 1}},
                 'schedule_id': 'synthetic-schedule', 'schedule_revision': 1, 'usage': {'seconds': 0}, 'budget': {'max_seconds': 60}, 'inflight': {'deadline_at': time.time() + 60}}
        with self.service.core.db() as db:
            db.execute('CREATE TABLE extension_runs(id TEXT PRIMARY KEY,idem TEXT,extension_id TEXT,status TEXT,document TEXT,created REAL)')
            db.execute('CREATE TABLE extension_registry(id TEXT PRIMARY KEY,current_version INTEGER,enabled INTEGER)')
            db.execute('CREATE TABLE extension_schedules(id TEXT PRIMARY KEY,revision INTEGER,enabled INTEGER,document TEXT)')
            db.execute('INSERT INTO extension_registry VALUES(?,?,?)', ('synthetic-extension', 1, 1))
            db.execute('INSERT INTO extension_schedules VALUES(?,?,?,?)', ('synthetic-schedule', 1, 1, '{}'))
            db.execute('INSERT INTO extension_runs VALUES(?,?,?,?,?,?)', (owner['id'], 'owner-idem', 'synthetic-extension', 'running', json.dumps(owner), time.time()))
        return owner

    def test_internal_owner_is_persisted_and_parent_revocation_before_dispatch_prevents_charge(self):
        p = self.configured(); owner = self.owner_run()
        job = self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset], 'owned', owner_run_id=owner['id'])
        self.assertEqual(job['owner_run_id'], owner['id'])
        owner['status'] = 'cancelled'
        with self.service.core.db() as db: db.execute('UPDATE extension_runs SET status=?,document=? WHERE id=?', ('cancelled', json.dumps(owner), owner['id']))
        self.providers().tick(); done = self.providers().get(job['id'])
        self.assertEqual(done['status'], 'failed'); self.assertFalse(done['external_generation_submitted'])
        self.assertEqual(done['error'], 'extension_media_owner_inactive'); self.assertFalse(any(r[0] == 'POST' for r in self.requests))

    def test_owner_version_and_schedule_are_checked_at_creation_and_claim(self):
        p = self.configured(); owner = self.owner_run()
        with self.service.core.db() as db: db.execute('UPDATE extension_registry SET current_version=2')
        with self.assertRaisesRegex(ValueError, 'owner_definition_revoked'):
            self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset], 'revoked', owner_run_id=owner['id'])
        with self.service.core.db() as db: db.execute('UPDATE extension_registry SET current_version=1')
        job = self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset], 'schedule-revoked', owner_run_id=owner['id'])
        with self.service.core.db() as db: db.execute('UPDATE extension_schedules SET revision=2')
        self.providers().tick()
        self.assertEqual(self.providers().get(job['id'])['error'], 'extension_media_owner_schedule_revoked')
        self.assertFalse(any(r[0] == 'POST' for r in self.requests))

    def test_shared_core_cancellation_prevents_owned_media_dispatch(self):
        profile=self.configured();owner=self.owner_run()
        job=self.providers().generate(self.request['id'],profile['id'],profile['revision'],[self.asset],'core-cancelled-owner',owner_run_id=owner['id'])
        self.service.core.invoke('commerce_task_cancel',{'task_id':owner['task_id']})
        self.providers().tick()
        self.assertEqual(self.providers().get(job['id'])['error'],'extension_media_owner_inactive')
        self.assertFalse(any(r[0]=='POST' for r in self.requests))

    def test_mcp_cannot_spoof_internal_owner_binding(self):
        with self.assertRaisesRegex(ValueError, 'owner_is_internal_only'):
            self.providers().invoke('commerce_media_provider_generate', {'owner_run_id': 'spoofed'})

    def test_capacity_blocked_jobs_do_not_starve_another_profile(self):
        p = self.configured(); self.mode = 'disconnect'; first = self.generate(p); self.providers().tick()
        for index in range(4): self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset], 'waiting-' + str(index))
        other = self.configured(label='Independent capacity'); self.mode = 'ok'
        independent = self.providers().generate(self.request['id'], other['id'], other['revision'], [self.asset], 'independent')
        self.providers().tick(at=first['created_at'] + 60)
        self.assertTrue(self.providers().get(independent['id'])['external_generation_submitted'])
        self.assertEqual(len([r for r in self.requests if r[:2] == ('POST', '/jobs')]), 2)

    def test_cancel_after_disconnected_submission_reports_unconfirmed_and_keeps_capacity(self):
        p = self.configured(); self.mode = 'disconnect'; job = self.generate(p); self.providers().tick()
        cancelled = self.providers().cancel(job['id'])
        self.assertTrue(cancelled['external_generation_submitted']); self.assertIsNone(cancelled['remote_task_id'])
        self.assertEqual(cancelled['remote_cancel_status'], 'no_task_id_unconfirmed')
        queued = self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset], 'after-unknown-cancel')
        self.mode = 'ok'; self.providers().tick(at=job['created_at'] + 60)
        self.assertFalse(self.providers().get(queued['id'])['external_generation_submitted'])
        self.assertEqual(self.providers().catalog()['profiles'][0]['occupied_slots'], 1)
        self.assertEqual(len([r for r in self.requests if r[:2] == ('POST', '/jobs')]), 1)

    def test_cancel_in_flight_without_task_id_never_claims_not_submitted(self):
        p = self.configured(); job = self.generate(p)
        self.mode = 'block_submit'; self.entered = threading.Event(); self.release = threading.Event()
        worker = threading.Thread(target=self.providers().tick); worker.start()
        try:
            self.assertTrue(self.entered.wait(2))
            cancelled = self.providers().cancel(job['id'])
            self.assertEqual(cancelled['remote_cancel_status'], 'no_task_id_unconfirmed')
            self.assertTrue(cancelled['external_generation_submitted'])
        finally:
            self.release.set(); worker.join(5)
        done = self.providers().get(job['id'])
        self.assertEqual(done['status'], 'cancelled'); self.assertEqual(done['remote_task_id'], 'remote-1')
        self.assertEqual(done['assets'], [])

    def test_cancelled_remote_job_only_get_reconciles_and_releases_capacity_after_terminal(self):
        p = self.configured(); self.mode = 'pending'; job = self.generate(p); self.providers().tick()
        self.providers().cancel(job['id'])
        queued = self.providers().generate(self.request['id'], p['id'], p['revision'], [self.asset], 'after-confirmed-terminal')
        self.providers().tick(at=job['created_at'] + 60)
        self.assertFalse(self.providers().get(queued['id'])['external_generation_submitted'])
        self.assertEqual(len([r for r in self.requests if r[:2] == ('POST', '/jobs')]), 1)
        self.mode = 'ok'; self.providers().tick(at=job['created_at'] + 120)
        cancelled = self.providers().get(job['id'])
        self.assertEqual(cancelled['status'], 'cancelled'); self.assertEqual(cancelled['provider_status'], 'succeeded')
        self.assertTrue(cancelled['provider_terminal']); self.assertEqual(cancelled['assets'], [])
        self.assertTrue(self.providers().get(queued['id'])['external_generation_submitted'])
        self.assertEqual(len([r for r in self.requests if r[:2] == ('POST', '/jobs')]), 2)
        self.assertTrue(any(r[:2] == ('GET', '/jobs/remote-1') for r in self.requests))
        self.assertFalse(any(r[:2] == ('GET', '/result.png') for r in self.requests))
        self.assertEqual(self.service.media.request_get(self.request['id'])['status'], 'awaiting_media')


if __name__ == '__main__': unittest.main()
