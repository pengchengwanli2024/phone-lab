"""Local channel selection and read-only diagnostics of the existing Hermes profile.

Saving a plan neither changes gateway credentials nor enables messaging. The
existing Hermes setup owns authorization; receipt tests remain separate work.
"""
from pathlib import Path
import copy
import json
import re
import subprocess
import threading
import time
from translation import model_command

PROFILE = 'commerce-bot'
CATALOG = (
    ('feishu', '飞书', (('app', '自建应用', 'feishu'),)),
    ('wecom', '企业微信', (('smart_robot', '智能机器人', 'wecom'), ('callback', '自建应用回调', 'wecom_callback'))),
    ('wechat', '微信', (('undecided', '待选择账号类型', None), ('personal_ilink', '个人微信 iLink', 'weixin'),
                       ('official_account', '公众号（尚无适配）', None), ('customer_service', '微信客服（尚无适配）', None))),
    ('dingtalk', '钉钉', (('stream', '应用 Stream', 'dingtalk'),)),
)
RUNTIME_STATES = {'not_running', 'stale', 'connected_reported', 'not_connected', 'unknown'}


def definitions(schema, string):
    return [
        ('commerce_channel_status', '读取四渠道本机接入计划与既有 commerce-bot 状态；不发送、不启用网关，配置不代表授权或实收', schema({'refresh': {'type': 'boolean'}})),
        ('commerce_channel_configure', '保存本项目渠道选择及备注，版本冲突时拒绝；不接收凭据、不改 Hermes 配置、不启用或发送', schema({
            'channel': {'type': 'string', 'enum': [row[0] for row in CATALOG]},
            'mode': {'type': 'string', 'enum': list(dict.fromkeys(mode[0] for row in CATALOG for mode in row[2]))},
            'selected': {'type': 'boolean'}, 'label': {'type': 'string', 'maxLength': 60},
            'expected_revision': {'type': 'string', 'maxLength': 12},
        }, ['channel', 'mode', 'selected', 'label', 'expected_revision'])),
    ]


def probe_profile():
    # Reuse the installed, profile-scoped Hermes runtime resolver. This worker
    # only loads config/plugin metadata and reads its existing status marker.
    command, env = model_command()
    command[-1] = str(Path(__file__).with_name('channel_probe_worker.py'))
    try:
        done = subprocess.run(command, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=12)
        if done.returncode or len(done.stdout) > 32768:
            raise ValueError('channel_probe_unavailable')
        value = json.loads(done.stdout)
        if not isinstance(value, dict) or type(value.get('profile_available')) is not bool or not isinstance(value.get('platforms'), dict):
            raise ValueError('channel_probe_unavailable')
        return value
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ValueError('channel_probe_unavailable') from None


class ChannelConnections:
    def __init__(self, core):
        self.core = core
        self.lock = threading.Lock()
        self.cached = None
        self.checked = 0
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS channel_bindings (channel TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL, updated REAL NOT NULL)')

    def _probe(self, refresh):
        with self.lock:
            if refresh or self.cached is None or time.monotonic() - self.checked > 15:
                try:
                    value = probe_profile()
                    self.cached = {'profile_available': value.get('profile_available') is True,
                                   'shared_core_configured': value.get('shared_core_configured') is True,
                                   'platforms': value.get('platforms', {}), 'probe_status': 'observed'}
                except Exception:
                    # Never keep an old successful state after diagnostics fail,
                    # and never expose arbitrary native exceptions or config.
                    self.cached = {'profile_available': False, 'shared_core_configured': False,
                                   'platforms': {}, 'probe_status': 'unavailable', 'error': 'channel_probe_unavailable'}
                self.checked = time.monotonic()
            return copy.deepcopy(self.cached)

    def status(self, refresh=False):
        if type(refresh) is not bool:
            raise ValueError('invalid_channel_refresh')
        probe = self._probe(refresh)
        with self.core.db() as db:
            plans = {row[0]: (json.loads(row[1]), row[2]) for row in db.execute('SELECT channel,payload,revision FROM channel_bindings')}
        channels = []
        for ident, name, modes in CATALOG:
            value, revision = plans.get(ident, ({'mode': modes[0][0], 'selected': False, 'label': ''}, 0))
            mode = next(item for item in modes if item[0] == value['mode'])
            native = probe['platforms'].get(mode[2], {}) if mode[2] else {}
            if not isinstance(native, dict):
                native = {}
            runtime = native.get('runtime_status', 'unknown')
            if runtime not in RUNTIME_STATES:
                runtime = 'unknown'
            adapter = native.get('adapter_available') is True
            credentials = native.get('credentials_present') is True
            enabled = native.get('gateway_enabled') is True
            missing = native.get('missing_fields', [])
            missing = [field for field in missing if isinstance(field, str) and re.fullmatch('[A-Z][A-Z0-9_]{1,79}', field)][:12] if isinstance(missing, list) else []
            if ident == 'wechat' and mode[0] == 'undecided':
                readiness = 'account_type_required'
            elif not value['selected']:
                readiness = 'not_selected'
            elif not mode[2]:
                readiness = 'unsupported_account_type'
            elif probe['probe_status'] != 'observed':
                readiness = 'unknown'
            elif not adapter:
                readiness = 'adapter_missing'
            elif not credentials or not enabled:
                readiness = 'authorization_required'
            elif runtime != 'connected_reported':
                readiness = 'gateway_not_running'
            else:
                readiness = 'scope_and_delivery_not_verified'
            channels.append({'id': ident, 'name': name,
                             'modes': [{'id': key, 'label': label, 'adapter_supported': platform is not None} for key, label, platform in modes],
                             'binding': {**value, 'revision': str(revision)}, 'adapter_available': adapter,
                             'credentials_present': credentials, 'missing_fields': missing, 'gateway_enabled': enabled,
                             'runtime_status': runtime, 'readiness': readiness, 'delivery_verified': False})
        return {'profile': PROFILE, 'profile_available': probe['profile_available'], 'probe_status': probe['probe_status'],
                **({'error': probe['error']} if probe.get('error') else {}), 'shared_core_configured': probe['shared_core_configured'],
                'setup_command': 'hermes -p commerce-bot gateway setup', 'external_messages_sent': False,
                'scope_verified': False, 'channels': channels}

    def configure(self, channel, mode, selected, label, expected_revision):
        entry = next((row for row in CATALOG if row[0] == channel), None)
        if not entry or mode not in {item[0] for item in entry[2]}:
            raise ValueError('invalid_channel_mode')
        if type(selected) is not bool or not isinstance(label, str) or len(label) > 60 or any(ord(c) < 32 for c in label):
            raise ValueError('invalid_channel_configuration')
        if re.search(r'(?i)(bearer\s|sk-[a-z0-9]{16}|-----BEGIN|https?://|/Users/|/home/)', label):
            raise ValueError('channel_label_is_not_a_credential_field')
        if not isinstance(expected_revision, str) or not re.fullmatch(r'0|[1-9][0-9]{0,10}', expected_revision):
            raise ValueError('invalid_channel_revision')
        payload = {'mode': mode, 'selected': selected, 'label': label.strip()}
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM channel_bindings WHERE channel=?', (channel,)).fetchone()
            revision = row[0] if row else 0
            if revision != int(expected_revision):
                raise ValueError('channel_configuration_conflict')
            db.execute('INSERT INTO channel_bindings VALUES (?,?,?,?) ON CONFLICT(channel) DO UPDATE SET payload=excluded.payload,revision=excluded.revision,updated=excluded.updated',
                       (channel, json.dumps(payload, ensure_ascii=False), revision + 1, time.time()))
        return self.status()
