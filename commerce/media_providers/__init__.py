"""Private configurable media generation, frozen receipts and guarded result adoption.

No adapter is configured automatically. Credentials enter only through configure()
on the owning service's authenticated private HTTP surface, never through MCP.
"""
import base64
import binascii
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
import time
import uuid

from research import canonical, digest
from creative_studio import MAX_ASSET
from . import adapters
from .transport import endpoint, relative, request, TransportError

PROVIDERS = {'openai': 'OpenAI', 'bytedance': '字节跳动 / 火山方舟', 'alibaba': '阿里云',
             'minimax': 'MiniMax', 'lovart': 'Lovart', 'local': '本机媒体模型', 'custom': '自定义媒体服务'}
ADAPTER_IDS = {'generic_json_async', 'comfyui', *adapters.NATIVE}
CONFIG_KEYS = {'id', 'expected_revision', 'label', 'provider', 'adapter', 'base_url', 'model', 'media_kind',
               'enabled', 'api_key', 'clear_api_key', 'auth_header', 'auth_scheme', 'capabilities', 'protocol',
               'workflow', 'bindings', 'output_nodes', 'parameters'}
ACTIVE = ('pending', 'submitted')
_SECRET_FIELDS = {'api_key', 'apikey', 'access_token', 'secret', 'password', 'authorization', 'credential_ref'}


def definitions(schema, string):
    return [
        ('commerce_media_provider_catalog', '读取可配置的云端及本机图片视频服务、能力和接入状态，不返回密钥', schema()),
        ('commerce_media_provider_test_profile', '只读探测指定媒体配置，不生成媒体；无安全探针时明确未验证', schema({'profile_id': string, 'expected_revision': string}, ['profile_id', 'expected_revision'])),
        ('commerce_media_provider_generate', '按冻结的产品制作版本提交指定媒体服务，可能产生费用；不自动改用其它服务', schema({'request_id': string, 'profile_id': string, 'expected_profile_revision': string, 'asset_ids': {'type': 'array', 'items': string, 'minItems': 1, 'maxItems': 8}, 'idempotency_key': string, 'shot_index': {'type': 'integer', 'minimum': 0, 'maximum': 30}}, ['request_id', 'profile_id', 'expected_profile_revision', 'asset_ids', 'idempotency_key'])),
        ('commerce_media_provider_get', '读取媒体生成真实状态及已验证文件，unknown 不自动重发', schema({'job_id': string}, ['job_id'])),
        ('commerce_media_provider_jobs', '按制作清单或项目读取持久化媒体任务，便于重新打开页面后恢复状态', schema({'request_id': string, 'project_id': string})),
        ('commerce_media_provider_cancel', '停止本任务本地接收；仅在配置了安全单任务接口时请求远端取消，不保证退款', schema({'job_id': string}, ['job_id'])),
        ('commerce_media_provider_reattach', '明确将已有实际生成文件用于当前同项目制作版本；重新检查产品、权限和文件哈希', schema({'job_id': string, 'request_id': string, 'expected_revision': string}, ['job_id', 'request_id', 'expected_revision'])),
    ]


def _text(value, maximum=160, required=True):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value) or (required and not value.strip()):
        raise ValueError('media_provider_invalid_configuration')
    return value.strip()


def _number(value, minimum, maximum):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and minimum <= value <= maximum


def _private_free(value):
    if isinstance(value, dict):
        if any(str(k).lower() in _SECRET_FIELDS for k in value): raise ValueError('media_provider_secret_only_in_api_key_field')
        for item in value.values(): _private_free(item)
    elif isinstance(value, list):
        for item in value: _private_free(item)


def configuration_schema():
    """Private setup form contract; api_key is deliberately absent from MCP tools."""
    string = {'type': 'string'}
    return {'type': 'object', 'additionalProperties': False,
            'required': ['label', 'provider', 'adapter', 'base_url', 'model', 'media_kind', 'capabilities'],
            'allOf': [{'if': {'properties': {'adapter': {'const': adapter}}}, 'then': {'properties': {'capabilities': {'properties': {'max_input_images': {'maximum': limit}}}}}} for adapter, limit in adapters.INPUT_IMAGE_LIMITS.items() if limit < 8],
            'properties': {
                'id': string, 'expected_revision': string, 'label': {'type': 'string', 'maxLength': 80},
                'provider': {'type': 'string', 'enum': list(PROVIDERS)}, 'adapter': {'type': 'string', 'enum': sorted(ADAPTER_IDS)},
                'base_url': string, 'model': string, 'media_kind': {'type': 'string', 'enum': ['image', 'video']},
                'enabled': {'type': 'boolean', 'default': False}, 'api_key': {'type': 'string', 'writeOnly': True, 'maxLength': 8192}, 'clear_api_key': {'type': 'boolean'},
                'auth_header': {'type': 'string', 'default': 'Authorization'}, 'auth_scheme': {'type': 'string', 'enum': ['Bearer', 'raw']},
                'capabilities': {'type': 'object', 'additionalProperties': False, 'properties': {
                    'image_input': {'type': 'boolean', 'default': True}, 'max_input_images': {'type': 'integer', 'minimum': 1, 'maximum': 8, 'default': 1}, 'min_duration_seconds': {'type': 'number', 'minimum': .1, 'maximum': 120},
                    'max_duration_seconds': {'type': 'number', 'minimum': .1, 'maximum': 120}, 'durations_seconds': {'type': 'array', 'items': {'type': 'number', 'minimum': .1, 'maximum': 120}},
                    'max_input_bytes': {'type': 'integer', 'minimum': 1024, 'maximum': 16777216}, 'max_output_bytes': {'type': 'integer', 'minimum': 1024, 'maximum': MAX_ASSET}, 'max_outputs': {'type': 'integer', 'minimum': 1, 'maximum': 8}, 'max_concurrent_jobs': {'type': 'integer', 'minimum': 1, 'maximum': 8, 'default': 1}}},
                'protocol': {'type': 'object', 'additionalProperties': False, 'properties': {**{key: string for key in ('probe_path', 'submit_path', 'poll_path', 'task_id_path', 'status_path', 'outputs_path', 'output_url_path', 'output_base64_path', 'cancel_path')},
                    'submit_body': {'type': 'object'}, 'cancel_body': {'type': 'object'}, 'states': {'type': 'object'}}},
                'workflow': {'type': 'object'}, 'bindings': {'type': 'object'}, 'output_nodes': {'type': 'array', 'items': string}, 'parameters': {'type': 'object'}}}


def _validate(data):
    if not isinstance(data, dict) or set(data) - CONFIG_KEYS: raise ValueError('media_provider_invalid_configuration')
    provider = data.get('provider'); adapter = data.get('adapter'); kind = data.get('media_kind')
    if provider not in PROVIDERS or adapter not in ADAPTER_IDS or kind not in ('image', 'video'): raise ValueError('media_provider_invalid_configuration')
    if provider == 'openai' and kind == 'video': raise ValueError('media_provider_openai_video_api_unavailable')
    if adapter in adapters.NATIVE and adapters.NATIVE[adapter] != (provider, kind): raise ValueError('media_provider_adapter_kind_mismatch')
    if adapter == 'comfyui' and provider != 'local': raise ValueError('media_provider_comfy_requires_explicit_local_origin')
    for field in ('enabled', 'clear_api_key'):
        if type(data.get(field, False)) is not bool: raise ValueError('media_provider_invalid_configuration')
    caps = data.get('capabilities')
    if not isinstance(caps, dict) or set(caps) - {'image_input', 'max_input_images', 'min_duration_seconds', 'max_duration_seconds', 'durations_seconds', 'max_output_bytes', 'max_input_bytes', 'max_outputs', 'max_concurrent_jobs'} or type(caps.get('image_input', True)) is not bool:
        raise ValueError('media_provider_invalid_capabilities')
    caps = {'image_input': True, 'max_input_images': 1, 'max_output_bytes': MAX_ASSET, 'max_input_bytes': 16 * 1024 * 1024, 'max_outputs': 1, 'max_concurrent_jobs': 1, **caps}
    for field, lower, upper in [('max_input_images', 1, 8), ('max_output_bytes', 1024, MAX_ASSET), ('max_input_bytes', 1024, 16 * 1024 * 1024), ('max_outputs', 1, 8), ('max_concurrent_jobs', 1, 8)]:
        if type(caps[field]) is not int or not lower <= caps[field] <= upper: raise ValueError('media_provider_invalid_capabilities')
    if caps['max_input_images'] > adapters.INPUT_IMAGE_LIMITS[adapter]: raise ValueError('media_provider_adapter_input_image_limit')
    if 'max_duration_seconds' in caps and not _number(caps['max_duration_seconds'], .1, 120): raise ValueError('media_provider_invalid_capabilities')
    if 'min_duration_seconds' in caps and not _number(caps['min_duration_seconds'], .1, 120): raise ValueError('media_provider_invalid_capabilities')
    if caps.get('min_duration_seconds', 0) > caps.get('max_duration_seconds', 120): raise ValueError('media_provider_invalid_capabilities')
    if 'durations_seconds' in caps and (not isinstance(caps['durations_seconds'], list) or not 1 <= len(caps['durations_seconds']) <= 120 or any(not _number(v, .1, 120) for v in caps['durations_seconds'])): raise ValueError('media_provider_invalid_capabilities')
    if kind == 'video' and not (caps.get('max_duration_seconds') or caps.get('durations_seconds')): raise ValueError('media_provider_duration_capability_required')
    p = data.get('protocol', {})
    if not isinstance(p, dict) or set(p) - {'probe_path', 'submit_path', 'poll_path', 'submit_body', 'task_id_path', 'status_path', 'outputs_path', 'output_url_path', 'output_base64_path', 'states', 'cancel_path', 'cancel_body'}:
        raise ValueError('media_provider_invalid_protocol')
    if adapter == 'generic_json_async':
        if not isinstance(p.get('submit_body'), dict) or not p.get('submit_path') or not p.get('outputs_path'): raise ValueError('media_provider_protocol_mapping_required')
        if p.get('poll_path') and not p.get('task_id_path'): raise ValueError('media_provider_task_id_mapping_required')
        variables = set(re.findall(r'\{\{([a-z0-9_]+)\}\}', canonical(p['submit_body'])))
        if not {'model', 'prompt'} <= variables: raise ValueError('media_provider_model_prompt_binding_required')
        if caps['image_input'] and not ({'images', 'image_data_uris'} & variables) and not {'image_data_uri_' + str(index) for index in range(caps['max_input_images'])} <= variables: raise ValueError('media_provider_product_image_binding_required')
    elif adapter in adapters.NATIVE and set(p) - {'probe_path'}:
        raise ValueError('media_provider_native_protocol_mapping_fixed')
    if p.get('states') is not None:
        states = p['states']
        if not isinstance(states, dict) or set(states) - {'pending', 'succeeded', 'failed', 'unknown'} or any(not isinstance(v, list) or not v or len(v) > 30 or any(not isinstance(x, str) or not x or len(x) > 80 for x in v) for v in states.values()):
            raise ValueError('media_provider_invalid_states')
        values = [x for v in states.values() for x in v]
        if len(values) != len(set(values)): raise ValueError('media_provider_ambiguous_states')
    for field in ('task_id_path', 'status_path', 'outputs_path', 'output_url_path', 'output_base64_path'):
        if field in p and (not isinstance(p[field], str) or not re.fullmatch(r'[a-zA-Z0-9_\-.]{1,240}', p[field])): raise ValueError('media_provider_invalid_mapping_path')
    base = endpoint(data.get('base_url'), provider == 'local')
    for field in ('probe_path', 'submit_path', 'poll_path', 'cancel_path'):
        if field in p: relative(base, p[field])
    header = data.get('auth_header', 'Authorization')
    if not isinstance(header, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,79}', header) or header.lower() in ('host', 'cookie', 'content-type', 'content-length', 'connection', 'proxy-authorization') or data.get('auth_scheme', 'Bearer') not in ('Bearer', 'raw'):
        raise ValueError('media_provider_invalid_auth_header')
    config = {'label': _text(data.get('label'), 80), 'provider': provider, 'adapter': adapter, 'base_url': base,
              'model': _text(data.get('model'), 200), 'media_kind': kind, 'capabilities': caps,
              'auth_header': header, 'auth_scheme': data.get('auth_scheme', 'Bearer'), 'protocol': copy.deepcopy(p)}
    if adapter == 'comfyui':
        graph = data.get('workflow'); bindings = data.get('bindings'); nodes = data.get('output_nodes')
        if not isinstance(graph, dict) or not graph or not isinstance(bindings, dict) or set(bindings) - {'prompt', 'image', 'width', 'height', 'duration_seconds', 'model'} or 'prompt' not in bindings or (caps['image_input'] and 'image' not in bindings): raise ValueError('media_provider_comfy_workflow_required')
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 8 or any(not isinstance(n, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', n) for n in nodes): raise ValueError('media_provider_comfy_output_nodes_required')
        for key, path in bindings.items():
            if not isinstance(path, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,240}', path) or adapters.get_path(graph, path) is None: raise ValueError('media_provider_workflow_binding_missing')
        config.update(workflow=copy.deepcopy(graph), bindings=copy.deepcopy(bindings), output_nodes=list(nodes))
    parameters = data.get('parameters', {})
    if not isinstance(parameters, dict): raise ValueError('media_provider_invalid_parameters')
    if adapter in adapters.NATIVE and set(parameters) & {'model', 'prompt', 'content', 'input', 'parameters', 'duration', 'duration_seconds', 'image', 'images', 'img_url', 'first_frame_image', 'last_frame_image', 'reference_image', 'response_format', 'task_id', 'api_key'}:
        raise ValueError('media_provider_reserved_parameter')
    if parameters: config['parameters'] = copy.deepcopy(parameters)
    _private_free(config)
    try:
        if len(canonical(config)) > 180000: raise ValueError('media_provider_configuration_too_large')
    except (TypeError, OverflowError): raise ValueError('media_provider_invalid_configuration') from None
    return config


class MediaProviders:
    def __init__(self, service):
        self.service = service; self.core = service.core; self.state = Path(service.state)
        self._lock = threading.RLock(); self._stopped = False
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS media_provider_profiles(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,config TEXT NOT NULL,enabled INTEGER NOT NULL,tested_revision INTEGER,test_status TEXT NOT NULL,tested_at REAL,updated REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS media_provider_jobs(id TEXT PRIMARY KEY,idem TEXT UNIQUE NOT NULL,request_id TEXT NOT NULL,project TEXT NOT NULL,document TEXT NOT NULL)')
        self.recover()

    def _record(self, db, profile_id):
        if not isinstance(profile_id, str) or not re.fullmatch(r'media_[a-f0-9]{16}', profile_id): raise ValueError('media_provider_profile_not_found')
        row = db.execute('SELECT id,revision,config,enabled,tested_revision,test_status,tested_at FROM media_provider_profiles WHERE id=?', (profile_id,)).fetchone()
        if not row: raise ValueError('media_provider_profile_not_found')
        config = json.loads(row[2]); config['capabilities']['max_input_images'] = adapters.input_image_limit(config)
        return {'id': row[0], 'revision': str(row[1]), 'config': config, 'enabled': bool(row[3]), 'tested_revision': str(row[4]) if row[4] is not None else None, 'test_status': row[5], 'tested_at': row[6]}

    @staticmethod
    def _public_profile(row):
        config = {k: v for k, v in row['config'].items() if k != 'credential_ref'}
        return {k: v for k, v in row.items() if k != 'config'} | config | {'key_configured': bool(row['config'].get('credential_ref')), 'selectable': row['enabled'] and row['test_status'] in ('passed', 'not_available') and row['tested_revision'] == row['revision'], 'capability_source': 'operator_configured_not_model_discovery'}

    def catalog(self):
        with self.core.db() as db:
            profiles = [self._public_profile(self._record(db, row[0])) for row in db.execute('SELECT id FROM media_provider_profiles ORDER BY updated DESC')]
            jobs = [json.loads(row[0]) for row in db.execute("SELECT document FROM media_provider_jobs WHERE json_extract(document,'$.status') IN ('pending','submitted','unknown','cancelled')")]
        for profile in profiles:
            matching = [j for j in jobs if j['profile_id'] == profile['id']]
            profile['occupied_slots'] = sum(self._occupies_capacity(j) for j in matching)
            profile['unresolved_jobs'] = sum(j['status'] == 'unknown' for j in matching)
            profile['queued_jobs'] = sum(j['stage'] == 'queued' and j['status'] == 'pending' for j in matching)
            profile['readiness_reasons'] = (['disabled'] if not profile['enabled'] else []) + ([profile['test_status']] if profile['test_status'] != 'passed' else [])
        return {'profiles': profiles, 'providers': [{'id': key, 'label': label, 'native_adapters': [a for a, (p, _) in adapters.NATIVE.items() if p == key],
                    **({'native_video_status': 'unavailable_shutdown_2026_09_24', 'native_image_status': 'pending_explicit_api_key_setup', 'source': 'https://developers.openai.com/api/reference/resources/videos'} if key == 'openai' else {}),
                    **({'native_status': 'host_plugin_separate_from_direct_api'} if key == 'lovart' else {})} for key, label in PROVIDERS.items()],
                'plugin_connections': self.service.media_plugins.catalog() if hasattr(self.service,'media_plugins') else None,
                'adapters': adapters.catalog_adapters(), 'credentials_via_private_setup_only': True, 'live_provider_generation_verified': False,
                'template_variables': ['model', 'prompt', 'images', 'image_data_uris', 'image_data_uri_0', 'width', 'height', 'duration_seconds', 'task_id', 'job_id'],
                'generation_requires_explicit_request': True, 'configuration_schema': configuration_schema()}

    def configure(self, data):
        config = _validate(data)
        key = data.get('api_key', '')
        if not isinstance(key, str) or len(key) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in key): raise ValueError('media_provider_invalid_api_key')
        with self._lock, self.core.atomic() as db:
            old = self._record(db, data['id']) if data.get('id') else None
            if old and data.get('expected_revision') != old['revision']: raise ValueError('media_provider_profile_changed')
            profile_id = old['id'] if old else 'media_' + uuid.uuid4().hex[:16]
            if not old and db.execute('SELECT count(*) FROM media_provider_profiles').fetchone()[0] >= 100: raise ValueError('media_provider_profile_limit')
            reference = None if data.get('clear_api_key') else (old or {}).get('config', {}).get('credential_ref')
            if key.strip():
                directory = self.state / 'media-provider-credentials'
                if directory.is_symlink(): raise ValueError('media_provider_unsafe_credential_storage')
                directory.mkdir(mode=0o700, exist_ok=True); directory.chmod(0o700)
                reference = secrets.token_hex(16)
                fd = os.open(directory / (reference + '.json'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as file: json.dump({'api_key': key.strip()}, file)
            config['credential_ref'] = reference
            revision = int(old['revision']) + 1 if old else 1
            db.execute('INSERT INTO media_provider_profiles VALUES(?,?,?,?,NULL,?,NULL,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,config=excluded.config,enabled=excluded.enabled,tested_revision=NULL,test_status=excluded.test_status,tested_at=NULL,updated=excluded.updated',
                       (profile_id, revision, canonical(config), int(data.get('enabled', False)), 'not_tested', time.time()))
            return self._public_profile(self._record(db, profile_id))

    def _secret(self, config):
        reference = config.get('credential_ref')
        if not reference: return ''
        if not isinstance(reference, str) or not re.fullmatch(r'[a-f0-9]{32}', reference): raise ValueError('media_provider_credentials_unavailable')
        directory = self.state / 'media-provider-credentials'; path = directory / (reference + '.json')
        if directory.is_symlink() or path.is_symlink(): raise ValueError('media_provider_credentials_unavailable')
        try: return json.loads(path.read_text())['api_key']
        except (OSError, ValueError, KeyError): raise ValueError('media_provider_credentials_unavailable') from None

    def test_profile(self, profile_id, expected_revision):
        with self.core.db() as db: row = self._record(db, profile_id)
        if row['revision'] != expected_revision: raise ValueError('media_provider_profile_changed')
        try: status = adapters.probe(row['config'], self._secret(row['config']))
        except ValueError: status = 'failed'
        with self.core.atomic() as db:
            if self._record(db, profile_id)['revision'] != expected_revision: raise ValueError('media_provider_profile_changed')
            db.execute('UPDATE media_provider_profiles SET tested_revision=?,test_status=?,tested_at=? WHERE id=?', (int(expected_revision), status, time.time(), profile_id))
            result = self._public_profile(self._record(db, profile_id))
        return {**result, 'probe_scope': 'read_only_connectivity_not_generation' if status == 'passed' else 'not_verified_no_safe_probe' if status == 'not_available' else 'read_only_probe_failed'}

    def _job(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9]{32}', job_id): raise ValueError('media_provider_job_not_found')
        with self.core.db() as db: row = db.execute('SELECT document FROM media_provider_jobs WHERE id=?', (job_id,)).fetchone()
        if not row: raise ValueError('media_provider_job_not_found')
        return json.loads(row[0])

    def _save(self, job, *, cancellation_update=False):
        job['updated_at'] = time.time()
        with self.core.atomic(reuse=True) as db:
            row = db.execute('SELECT document FROM media_provider_jobs WHERE id=?', (job['id'],)).fetchone()
            current = json.loads(row[0]) if row else {}
            if current.get('provider_terminal') and not job.get('provider_terminal'):
                job.update(provider_terminal=True, provider_status=current['provider_status'])
            if current.get('cancel_requested'):
                # A stale network worker must never clear durable cancellation.
                remote = job.get('remote_cancel_status') if cancellation_update else current.get('remote_cancel_status')
                job.update(cancel_requested=True, status='cancelled', stage='cancelled_locally', review_status='not_adopted',
                           cancel_scope=current.get('cancel_scope', 'local_result_adoption'), remote_cancel_status=remote,
                           cancel_requested_at=current.get('cancel_requested_at'))
            db.execute('UPDATE media_provider_jobs SET document=? WHERE id=?', (canonical(job), job['id']))

    def _adoption_guard(self, job):
        if self._stopped: raise ValueError('media_provider_stopped_before_adoption')
        current = self._job(job['id'])
        if current.get('cancel_requested') or current['status'] == 'cancelled': raise ValueError('media_provider_cancelled_before_adoption')

    @staticmethod
    def _owner_guard(db, owner_run_id, job_id=None):
        if owner_run_id is None: return
        if not isinstance(owner_run_id, str) or not owner_run_id or len(owner_run_id) > 160: raise ValueError('media_provider_invalid_owner_run')
        from extension_runtime import guard_media_owner
        guard_media_owner(db, owner_run_id, job_id=job_id)

    def _guard(self, job, request_document=None):
        with self.core.db() as db: profile = self._record(db, job['profile_id'])
        if not profile['enabled']: raise ValueError('media_provider_disabled')
        if profile['revision'] != job['profile_revision']: raise ValueError('media_provider_profile_changed')
        if len(job['source_assets']) > adapters.input_image_limit(job['profile_snapshot']): raise ValueError('media_provider_input_image_limit_exceeded')
        current = request_document or self.service.media.request_get(job['request_id'])
        if current['project_id'] != job['project_id']: raise ValueError('media_provider_request_outside_scope')
        if request_document is None and current['request_sha256'] != job['request']['request_sha256']: raise ValueError('media_provider_request_changed')
        p = self.service.media._current(current)
        for source in job['source_assets']:
            path, metadata, _ = self.service.creative.asset(job['project_id'], source['asset_id'])
            if metadata['sha256'] != source['sha256'] or hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']: raise ValueError('creative_asset_changed')
        return p

    @staticmethod
    def _plugin_submission_guard(db, request_id):
        # A local cancellation or a lost host receipt does not make a charged
        # plugin creation safe to repeat through another provider entry point.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_plugin_executions'").fetchone():
            unresolved = db.execute("SELECT 1 FROM media_plugin_executions WHERE request_id=? AND json_extract(document,'$.external_generation_submitted')=1 AND COALESCE(json_extract(document,'$.provider_terminal'),0)=0 LIMIT 1", (request_id,)).fetchone()
            if unresolved: raise ValueError('media_plugin_generation_already_submitted')

    def generate(self, request_id, profile_id, expected_profile_revision, asset_ids, idempotency_key, shot_index=None, *, owner_run_id=None):
        if self._stopped: raise ValueError('media_provider_stopped')
        _text(idempotency_key, 160)
        with self._lock, self.core.atomic() as db:
            self._owner_guard(db, owner_run_id)
            row = self._record(db, profile_id)
            if row['revision'] != expected_profile_revision: raise ValueError('media_provider_profile_changed')
            if not self._public_profile(row)['selectable']: raise ValueError('media_provider_not_ready')
            d = self.service.media.request_get(request_id); self.service.media._current(d)
            config = row['config']; video = d['spec']['format'].endswith('_video')
            if config['media_kind'] != ('video' if video else 'image'): raise ValueError('media_provider_request_kind_mismatch')
            if not config['capabilities']['image_input']: raise ValueError('media_provider_product_image_input_unsupported')
            if not isinstance(asset_ids, list) or not 1 <= len(asset_ids) <= 8 or len(set(asset_ids)) != len(asset_ids): raise ValueError('creative_invalid_asset_selection')
            if len(asset_ids) > adapters.input_image_limit(config): raise ValueError('media_provider_input_image_limit_exceeded')
            if shot_index is not None and (not video or type(shot_index) is not int or not 0 <= shot_index < len(d['spec']['shots'])): raise ValueError('media_provider_invalid_shot_index')
            requested_duration = d['spec']['duration_ms'] / 1000 if video else None
            if shot_index is not None:
                shot = d['spec']['shots'][shot_index]; requested_duration = (shot['end_ms'] - shot['start_ms']) / 1000
            caps = config['capabilities']
            duration = max(requested_duration, caps.get('min_duration_seconds', 0)) if video else None
            if video and caps.get('durations_seconds'):
                eligible = sorted(v for v in caps['durations_seconds'] if v >= duration and v <= caps.get('max_duration_seconds', 120))
                if not eligible: raise ValueError('media_provider_duration_unsupported_generate_individual_shots')
                duration = eligible[0]
            if video and duration > caps.get('max_duration_seconds', 120): raise ValueError('media_provider_duration_unsupported_generate_individual_shots')
            if duration is not None and int(duration) == duration: duration = int(duration)
            sources = []; total = 0
            for asset_id in asset_ids:
                path, meta, kind = self.service.creative.asset(d['project_id'], asset_id)
                if kind not in ('product_image', 'generated_image'): raise ValueError('creative_product_media_required')
                if hashlib.sha256(path.read_bytes()).hexdigest() != meta['sha256']: raise ValueError('creative_asset_changed')
                total += path.stat().st_size
                sources.append({'asset_id': asset_id, 'sha256': meta['sha256'], 'kind': kind})
            if total > caps['max_input_bytes']: raise ValueError('media_provider_input_too_large')
            if config['adapter'] == 'comfyui' and len(sources) != 1: raise ValueError('media_provider_comfy_single_image_binding_required')
            frozen = {'request_sha256': d['request_sha256'], 'profile_id': profile_id, 'profile_revision': expected_profile_revision, 'source_assets': sources, 'shot_index': shot_index, 'owner_run_id': owner_run_id}
            idem = digest(canonical([request_id, idempotency_key])); existing = db.execute('SELECT id,document FROM media_provider_jobs WHERE idem=?', (idem,)).fetchone()
            if existing:
                if json.loads(existing[1])['input_sha256'] != digest(canonical(frozen)): raise ValueError('idempotency_conflict')
                return self.get(existing[0])
            self._plugin_submission_guard(db, request_id)
            if d.get('result_sha256'): raise ValueError('creative_result_immutable_create_new_version')
            if db.execute('SELECT count(*) FROM media_provider_jobs WHERE project=?', (d['project_id'],)).fetchone()[0] >= 200: raise ValueError('media_provider_job_limit')
            job = {'id': uuid.uuid4().hex, 'request_id': request_id, 'project_id': d['project_id'], 'profile_id': profile_id, 'profile_revision': expected_profile_revision, 'owner_run_id': owner_run_id,
                   'provider': config['provider'], 'adapter': config['adapter'], 'adapter_version': '1', 'model': config['model'], 'media_kind': config['media_kind'], 'shot_index': shot_index,
                   'duration_seconds': duration, 'requested_duration_seconds': requested_duration, 'submitted_duration_seconds': duration,
                   'complete_request_output': shot_index is None, 'status': 'pending', 'stage': 'queued', 'provider_status': 'not_submitted',
                   'remote_task_id': None, 'assets': [], 'artifacts': [], 'review_status': 'awaiting_media', 'error': None, 'external_generation_submitted': False, 'cancel_requested': False, 'provider_terminal': False,
                   'created_at': time.time(), 'updated_at': time.time(), 'next_poll_at': 0, 'result_sha256': None, 'request': copy.deepcopy(d),
                   'profile_snapshot': copy.deepcopy(config), 'source_assets': sources, 'input_sha256': digest(canonical(frozen))}
            db.execute('INSERT INTO media_provider_jobs VALUES(?,?,?,?,?)', (job['id'], idem, request_id, d['project_id'], canonical(job)))
            return self.get(job['id'])

    def get(self, job_id):
        job = self._job(job_id)
        self.service.media.project(job['project_id'])
        try: self._guard(job); stale = False
        except ValueError: stale = True
        return {k: v for k, v in job.items() if k not in ('request', 'profile_snapshot', 'artifacts', 'next_poll_at', 'receipt_filename')} | {'stale': stale}

    def jobs(self, request_id=None, project_id=None):
        if request_id is None and project_id is None: raise ValueError('media_provider_job_scope_required')
        if request_id is not None:
            d = self.service.media.request_get(request_id)
            if project_id is not None and project_id != d['project_id']: raise ValueError('media_provider_request_outside_scope')
            project_id = d['project_id']
        self.service.media.project(project_id)
        with self.core.db() as db:
            rows = db.execute('SELECT id FROM media_provider_jobs WHERE project=?' + (' AND request_id=?' if request_id is not None else '') + ' ORDER BY rowid DESC LIMIT 100',
                              (project_id, request_id) if request_id is not None else (project_id,)).fetchall()
        return {'jobs': [self.get(row[0]) for row in rows], 'project_id': project_id, 'request_id': request_id}

    def _context(self, job):
        images = []
        for source in job['source_assets']:
            path, meta, _ = self.service.creative.asset(job['project_id'], source['asset_id'])
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != source['sha256']: raise ValueError('creative_asset_changed')
            mime = 'image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if raw.startswith(b'\xff\xd8\xff') else None
            if not mime: raise ValueError('media_provider_product_image_format_unsupported')
            encoded = base64.b64encode(raw).decode()
            images.append({**source, 'mime': mime, 'base64': encoded, 'data_uri': 'data:' + mime + ';base64,' + encoded})
        spec = job['request']['spec']; prompt = spec['prompt']
        if job['shot_index'] is not None:
            shot = spec['shots'][job['shot_index']]
            prompt += '\n只制作当前镜头，不制作整片：' + canonical(shot) + '；生成 ' + str(job['duration_seconds']) + ' 秒，目标镜头使用 ' + str(job.get('requested_duration_seconds', job['duration_seconds'])) + ' 秒，多余部分供本机裁切。'
        return {'model': job['model'], 'prompt': prompt, 'images': images, 'image_data_uris': [i['data_uri'] for i in images],
                **{'image_data_uri_' + str(index): image['data_uri'] for index, image in enumerate(images)},
                'width': spec['width'], 'height': spec['height'], 'duration_seconds': job['duration_seconds'], 'job_id': job['id']}

    def _folder(self, job):
        root = self.state / 'media-provider-results'
        if root.is_symlink(): raise ValueError('media_provider_unsafe_result_storage')
        root.mkdir(mode=0o700, exist_ok=True); root.chmod(0o700)
        folder = root / job['id']
        if folder.is_symlink(): raise ValueError('media_provider_unsafe_result_storage')
        folder.mkdir(mode=0o700, exist_ok=True)
        return folder

    def _download(self, job, outputs, api_key):
        from media_outputs import retrieve
        config = job['profile_snapshot']; caps = config['capabilities']
        result = retrieve(self.service.creative, self._folder(job), job['media_kind'], outputs,
                          config=config, max_output_bytes=caps['max_output_bytes'], max_outputs=caps['max_outputs'],
                          duration_seconds=job['duration_seconds'], api_key=api_key,
                          cancelled=lambda: self._job(job['id']).get('cancel_requested', False))
        job['artifacts'] = result['artifacts']; job['result_sha256'] = result['result_sha256']; job['status'] = 'succeeded'; job['stage'] = 'output_ready'; job['review_status'] = 'not_adopted'
        self._save(job)

    def _registered_outputs(self, job):
        assets = []
        for artifact in job['artifacts']:
            # A crash after registration can safely reuse the exact provider output.
            existing = next((a for a in self.service.creative.get(job['project_id'])['assets'] if a.get('media_provider_job_id') == job['id'] and a.get('provider_output_index') == artifact['index'] and a['sha256'] == artifact['sha256']), None)
            if existing:
                path, meta, _ = self.service.creative.asset(job['project_id'], existing['id'])
                if hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']: raise ValueError('creative_asset_changed')
                assets.append(existing); continue
            path = self._folder(job) / artifact['filename']
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']: raise ValueError('creative_asset_changed')
            # register() moves the staging file. Persisted artifact hashes remain provenance.
            asset = self.service.creative.register(job['project_id'], 'generated_' + job['media_kind'], path,
                {'display_name': '生成镜头 ' + str(job['shot_index'] + 1) if job['shot_index'] is not None else '生成媒体 · 待审阅', 'origin': 'configured_media_provider',
                 'provider': job['provider'], 'provider_adapter': job['adapter'], 'provider_adapter_version': job.get('adapter_version', '1'), 'provider_model': job['model'], 'provider_profile_id': job['profile_id'], 'provider_profile_revision': job['profile_revision'],
                 'media_provider_job_id': job['id'], 'provider_task_id': job['remote_task_id'], 'provider_output_index': artifact['index'], 'creative_request_id': job['request_id'],
                 'creative_request_sha256': job['request']['request_sha256'], 'project_input_sha256': job['request']['input_sha256'], 'direction_sha256': job['request']['direction_sha256'],
                 'source_assets': job['source_assets'], 'media': artifact['media'], 'shot_index': job['shot_index'], 'complete_request_output': job['complete_request_output'],
                 'requested_duration_seconds': job.get('requested_duration_seconds', job['duration_seconds']), 'submitted_duration_seconds': job['duration_seconds'],
                 'review_status': 'awaiting_review', 'product_identity_preserved': 'not_independently_verified', 'generation_verified': 'actual_media_bytes_and_probe_only'})
            assets.append(asset)
        return assets

    def _adopt(self, job, target=None, revision=None):
        # Registration and provenance reuse share the same DB lock, so two
        # gateway workers cannot register the same frozen output twice.
        with self.core.atomic() as db:
            self._adoption_guard(job)
            self._owner_guard(db, job.get('owner_run_id'), job_id=job['id'])
            p = self._guard(job, target)
            d = target or self.service.media.request_get(job['request_id'])
            if revision is not None and p['revision'] != revision: raise ValueError('creative_revision_conflict_refresh_first')
            if (d['spec']['format'].endswith('_video')) != (job['media_kind'] == 'video'): raise ValueError('media_provider_request_kind_mismatch')
            if job['complete_request_output'] and job['media_kind'] == 'video' and d['spec']['duration_ms'] / 1000 > job['duration_seconds'] + .35: raise ValueError('media_provider_output_duration_mismatch')
            assets = self._registered_outputs(job)
        job['assets'] = assets
        if job['complete_request_output']:
            with self.core.atomic() as db:
                self._adoption_guard(job)
                self._owner_guard(db, job.get('owner_run_id'), job_id=job['id'])
                self.service.media.request_attach(d['id'], p['revision'], [a['id'] for a in assets], _reuse=True)
        job.update(status='succeeded', stage='awaiting_review', review_status='awaiting_review', error=None,
                   attached_request_id=d['id'] if job['complete_request_output'] else None)
        self._save(job)

    def reattach(self, job_id, request_id, expected_revision):
        with self._lock:
            job = self._job(job_id)
            if job['status'] != 'succeeded' or not job['artifacts']: raise ValueError('media_provider_verified_output_required')
            d = self.service.media.request_get(request_id)
            self._adopt(job, d, expected_revision)
            return self.get(job_id)

    def _apply(self, job, result, api_key, at):
        job['provider_status'] = result['provider_status']
        job['provider_terminal'] = result['status'] in ('succeeded', 'failed')
        if result.get('remote_task_id'): job['remote_task_id'] = result['remote_task_id']
        job['status'] = result['status']; job['next_poll_at'] = at + 5
        if result['status'] in ('submitted', 'pending'):
            if not job['remote_task_id']: raise ValueError('media_provider_pending_without_task_id')
            job['stage'] = 'polling'; self._save(job)
        elif result['status'] == 'succeeded':
            # Persist the acknowledged response before downloading. A synchronous
            # image result has no task ID that could safely be polled after restart.
            folder = self._folder(job); temporary = folder / (uuid.uuid4().hex + '.receipt')
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as file: json.dump({'outputs': result['outputs']}, file)
            destination = folder / 'receipt.json'
            if destination.is_symlink(): raise ValueError('media_provider_unsafe_result_storage')
            temporary.replace(destination)
            job.update(status='pending', stage='retrieving', receipt_filename='receipt.json')
            self._save(job)
            self._finish_receipt(job, api_key)
        else:
            job['stage'] = 'provider_' + result['status']; job['error'] = 'media_provider_reported_' + result['status']; self._save(job)

    def _finish_receipt(self, job, api_key):
        if self._stopped or self._job(job['id']).get('cancel_requested'): return
        receipt = self._folder(job) / 'receipt.json'
        if receipt.is_symlink() or not receipt.is_file() or receipt.stat().st_size > 48 * 1024 * 1024: raise ValueError('media_provider_receipt_unavailable')
        try: outputs = json.loads(receipt.read_text())['outputs']
        except (ValueError, KeyError, UnicodeError): raise ValueError('media_provider_receipt_unavailable') from None
        self._download(job, outputs, api_key)
        if self._job(job['id']).get('cancel_requested'): return
        if self._stopped:
            job.update(status='pending', stage='output_ready', review_status='not_adopted', error='media_provider_stopped_before_adoption')
            self._save(job); return
        try: self._adopt(job)
        except ValueError as error:
            if self._stopped:
                job.update(status='pending', stage='output_ready', review_status='not_adopted', error=str(error))
            else:
                job.update(stage='result_held', review_status='not_adopted', error=str(error))
            self._save(job)

    @staticmethod
    def _occupies_capacity(job):
        return (job['status'] in (*ACTIVE, 'unknown') and job['stage'] != 'queued') or (job['status'] == 'cancelled' and job['external_generation_submitted'] and not job.get('provider_terminal') and job['provider_status'] not in ('succeeded', 'failed', 'cancelled', 'expired', 'success', 'error', 'SUCCEEDED', 'FAILED', 'CANCELED'))

    def _reconcile_cancelled(self, job, at):
        """Only GET task status; never retrieve output files or adopt cancelled work."""
        try:
            self.service.media.project(job['project_id'])
            with self.core.db() as db: profile = self._record(db, job['profile_id'])
            if not profile['enabled']: raise ValueError('media_provider_disabled')
            if profile['revision'] != job['profile_revision']: raise ValueError('media_provider_profile_changed')
            config = job['profile_snapshot']
            result = adapters.poll(config, job['remote_task_id'], self._secret(config))
            job.update(provider_status=result['provider_status'], provider_terminal=result['status'] in ('succeeded', 'failed'),
                       remote_reconciliation_status='terminal' if result['status'] in ('succeeded', 'failed') else 'pending',
                       next_poll_at=at + 5, error=None)
        except ValueError as error:
            job.update(remote_reconciliation_status='unconfirmed', error=str(error), next_poll_at=at + 15)
        self._save(job)

    def tick(self, at=None):
        if self._stopped or not self._lock.acquire(blocking=False): return
        try:
            at = time.time() if at is None else at
            with self.core.db() as db:
                rows = db.execute("SELECT document FROM media_provider_jobs WHERE (json_extract(document,'$.status') IN ('pending','submitted') OR (json_extract(document,'$.status')='cancelled' AND json_extract(document,'$.remote_task_id') IS NOT NULL AND json_extract(document,'$.external_generation_submitted')=1 AND COALESCE(json_extract(document,'$.provider_terminal'),0)=0)) AND json_extract(document,'$.next_poll_at')<=? ORDER BY json_extract(document,'$.next_poll_at'),rowid LIMIT 128", (at,)).fetchall()
            active = [job for (raw,) in rows if (job := json.loads(raw))['next_poll_at'] <= at]
            io_count = 0
            for job in active:
                if io_count >= 4: break
                if self._stopped: break
                if job['status'] == 'cancelled':
                    if self._occupies_capacity(job):
                        io_count += 1; self._reconcile_cancelled(job, at)
                    else:
                        job['provider_terminal'] = True; self._save(job)
                    continue
                submitting = job['stage'] == 'queued'
                try:
                    self._guard(job)
                except ValueError as error:
                    job.update(status='unknown' if job['external_generation_submitted'] else 'failed', stage='blocked', error=str(error)); self._save(job); continue
                try:
                    config = job['profile_snapshot']; api_key = self._secret(config)
                    if submitting:
                        context = self._context(job)
                        # Durable claim precedes the potentially charged request. Never retry this stage.
                        with self.core.atomic() as db:
                            current = self._job(job['id'])
                            if self._stopped or current.get('cancel_requested') or current['stage'] != 'queued' or current['status'] != 'pending': continue
                            self._plugin_submission_guard(db, current['request_id'])
                            self._owner_guard(db, current.get('owner_run_id'), job_id=current['id'])
                            others = [json.loads(row[0]) for row in db.execute("SELECT document FROM media_provider_jobs WHERE json_extract(document,'$.profile_id')=? AND id<>?", (job['profile_id'], job['id']))]
                            if sum(self._occupies_capacity(other) for other in others) >= config['capabilities'].get('max_concurrent_jobs', 1):
                                job.update(error='media_provider_waiting_for_profile_capacity', next_poll_at=at + 5); self._save(job); continue
                            job.update(stage='submitting', status='submitted', external_generation_submitted=True); self._save(job)
                        io_count += 1
                        result = adapters.submit(config, context, api_key)
                    elif job['stage'] == 'retrieving':
                        io_count += 1
                        self._finish_receipt(job, api_key)
                        continue
                    else:
                        io_count += 1
                        result = adapters.poll(config, job['remote_task_id'], api_key)
                    self._apply(job, result, api_key, at)
                except ValueError as error:
                    if isinstance(error, TransportError) and not submitting and not job.get('artifacts'):
                        # Safe GET failures can be retried; remote state is still unknown.
                        job.update(status='pending', stage='retrieving' if job.get('receipt_filename') else 'polling', error=str(error), next_poll_at=at + 15)
                    else:
                        ambiguous = submitting and job['external_generation_submitted'] and (not isinstance(error, TransportError) or error.ambiguous)
                        job.update(status='unknown' if ambiguous else 'failed', stage='unknown' if ambiguous else 'failed', error=str(error))
                    self._save(job)
        finally:
            self._lock.release()

    def cancel(self, job_id):
        # Persist intent before any remote work, without waiting for tick's I/O lock.
        with self.core.atomic() as db:
            job = self._job(job_id); self.service.media.project(job['project_id'])
            if job['status'] not in (*ACTIVE, 'unknown'): return self.get(job_id)
            unconfirmed = 'no_task_id_unconfirmed' if job['external_generation_submitted'] else 'not_submitted'
            job.update(cancel_requested=True, cancel_requested_at=time.time(), status='cancelled', stage='cancelled_locally', review_status='not_adopted',
                       cancel_scope='local_result_adoption', remote_cancel_status='request_pending' if job.get('remote_task_id') else unconfirmed)
            self._save(job)
        remote = unconfirmed
        if job.get('remote_task_id'):
            try:
                self._guard(job)
                remote = adapters.cancel(job['profile_snapshot'], job['remote_task_id'], self._secret(job['profile_snapshot']))
            except ValueError: remote = 'unknown_or_configuration_blocked'
        # Refresh the worker's newly returned task/output metadata before updating.
        with self.core.atomic() as db:
            job = self._job(job_id); job['remote_cancel_status'] = remote; self._save(job, cancellation_update=True)
        return self.get(job_id)

    def recover(self):
        with self._lock, self.core.db() as db:
            for (raw,) in db.execute('SELECT document FROM media_provider_jobs').fetchall():
                job = json.loads(raw)
                if job['stage'] == 'submitting':
                    job.update(status='unknown', stage='unknown', error='media_provider_submit_interrupted_no_automatic_resubmit'); self._save(job)
                elif job['status'] in ('succeeded', 'pending') and job['stage'] == 'output_ready' and not job.get('cancel_requested'):
                    try: self._adopt(job)
                    except ValueError as error:
                        job.update(stage='result_held', error=str(error)); self._save(job)
        return {'recovered': True, 'automatic_resubmission': False}

    def stop(self):
        self._stopped = True

    def invoke(self, name, args):
        action = name.removeprefix('commerce_media_provider_')
        if action not in ('catalog', 'test_profile', 'generate', 'get', 'jobs', 'cancel', 'reattach') or not name.startswith('commerce_media_provider_'): raise ValueError('media_provider_unknown_tool')
        if 'owner_run_id' in args: raise ValueError('media_provider_owner_is_internal_only')
        return getattr(self, action)(**args)
