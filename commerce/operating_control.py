"""Main workspace projection and original task intake; no business executor."""
import hashlib
import json
from pathlib import Path

READ_ONLY = {'commerce_operating_control_get'}
KINDS = ('research', 'feature', 'operations')


def definitions(schema, string):
    mode = {'synthetic': {'type': 'boolean'}}
    return [
        ('commerce_operating_control_get', '读取共享经营预算、手机接入和原任务；不执行交易或调度', schema(mode, ['synthetic'])),
        ('commerce_operating_control_task_submit', '将明确研究/功能/运营需求保存到原任务中心；排队不代表执行，不扩大预算或权限',
         schema({**mode, 'kind': {'type': 'string', 'enum': list(KINDS)}, 'title': {'type': 'string', 'minLength': 1, 'maxLength': 160},
                 'details': {'type': 'string', 'maxLength': 6000}, 'idempotency_key': string},
                ['synthetic', 'kind', 'title', 'details', 'idempotency_key'])),
    ]


def boolean(value):
    if type(value) is not bool:
        raise ValueError('operating_control_invalid_mode')
    return value


def text(value, limit, required=False):
    if type(value) is not str or len(value) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError('operating_control_invalid_text')
    if required and not value.strip():
        raise ValueError('operating_control_invalid_text')
    return value.strip()


def cny(minor):
    if type(minor) is not int or minor < 0:
        return None
    return str(minor // 100) + '.' + str(minor % 100).zfill(2)


class OperatingControl:
    def __init__(self, service):
        self.service, self.core = service, service.core

    def invoke(self, name, args):
        return {'commerce_operating_control_get': self.get, 'commerce_operating_control_task_submit': self.task_submit}[name](**args)

    def profile(self):
        path = Path(self.service.state) / 'operating-control.json'
        default = {'revision': 0, 'platform': 'ozon', 'market': 'RU', 'fulfillment': 'pending',
                   'inventory_location': 'pending', 'sku_status': 'pending_user', 'logistics_status': 'not_connected'}
        if not path.exists():
            return default
        if path.is_symlink() or path.stat().st_size > 16000:
            raise ValueError('operating_control_profile_invalid')
        try:
            saved = json.loads(path.read_text())
            if type(saved) is not dict or set(saved) - set(default) or type(saved.get('revision')) is not int or saved['revision'] < 1:
                raise ValueError()
            for key, value in saved.items():
                if key != 'revision' and (type(value) is not str or not value or len(value) > 100 or any(ord(c) < 32 for c in value)):
                    raise ValueError()
            return {**default, **saved}
        except (ValueError, UnicodeError):
            raise ValueError('operating_control_profile_invalid') from None

    def _tasks(self, synthetic):
        # Query the original task source directly so unrelated recent tasks do
        # not truncate the control inbox. No second task/queue record is made.
        rows = []
        with self.core.db() as db:
            has_mobile = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mobile_inbox'").fetchone()
            mobile_tasks = {r[0] for r in db.execute('SELECT task_id FROM mobile_inbox WHERE task_id IS NOT NULL')} if has_mobile else set()
            for raw in db.execute('SELECT id,payload,status FROM tasks ORDER BY rowid DESC'):
                payload = json.loads(raw[1]);data = payload.get('input', {})
                if data.get('demo') is not synthetic or (data.get('origin') != 'operating_control' and raw[0] not in mobile_tasks):
                    continue
                title = data.get('title', '')
                if raw[0] in mobile_tasks and data.get('request_text'):
                    title += ' · ' + data['request_text'][:80]
                rows.append({'id': raw[0], 'title': title, 'intent': data.get('intake_kind', data.get('mobile_intent', '')), 'status': raw[2]})
                if len(rows) >= 30:
                    break
        return rows

    def _mobile(self):
        # Local protocol readiness must never imply an authenticated channel.
        return {'recommended': 'feishu', 'connection_status': 'authorization_required', 'owner_bound': False,
                'commands_ready': False, 'decisions_ready': False, 'setup_steps': [
                    '创建飞书企业自建应用并开启机器人能力。',
                    '开通接收消息、发送消息和卡片交互所需权限。',
                    '在本机私有配置中填写应用凭据，并绑定可指挥和决策的管理员。',
                    '连接后实际核对手机收消息、提交任务、准确决定和原任务结果。']}

    def _store(self, synthetic):
        if synthetic or not hasattr(self.service, 'live'):
            return None
        live = self.service.live.status()
        return {'label': live['store_label'], 'configured': live['configured'],
                'orders': live['orders'], 'stock': live['stock'], 'sales': live['sales'],
                'orders_scope_confirmed': live['orders_scope_confirmed'],
                'automatic_read_enabled': live['sync_enabled'], 'business_writes_enabled': False}

    def mobile_budget(self):
        value = self.service.operating_budget.policy_get('live')
        policy, usage = value['policy'], value['usage']
        body = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        return {'schema': 'commerce-mobile-budget-view-v1', 'currency': 'CNY',
                'status': 'configured' if policy['configured'] else 'unknown',
                'total_limit': cny(policy['cap_minor']) if policy['configured'] else None,
                'remaining': cny(usage['available_minor']) if policy['configured'] else None,
                'period': 'cumulative_pilot', 'source_sha256': hashlib.sha256(body.encode()).hexdigest()}

    def get(self, synthetic):
        boolean(synthetic)
        profile = self.profile()
        budget = self.service.operating_budget.policy_get('synthetic' if synthetic else 'live')
        policy, usage = budget['policy'], budget['usage']
        configured = policy['configured']
        mobile = self._mobile()
        store = self._store(synthetic)
        if store and store['stock']['available'] and profile['sku_status'] != 'confirmed':
            profile = {**profile, 'sku_status': 'api_synced_mapping_pending'}
        decisions = []
        if hasattr(self.service, 'attention'):
            view = self.service.attention.listing(demo=synthetic, limit=10)
            decisions = [{'id': r['id'], 'title': r.get('title', '待核事项'), 'status': r.get('kind', 'review'),
                          'detail': r.get('detail', ''), 'can_decide_here': False} for r in view.get('items', [])]
        blockers = []
        if not configured:
            blockers.append('尚未登记本轮共享预算。')
        if profile['sku_status'] != 'confirmed':
            blockers.append('平台SKU已读取；仍须核对公司本地库存、采购款式和库位映射。' if store and store['stock']['available'] else '店铺SKU和库存映射等待补充。')
        if profile['logistics_status'] != 'connected_verified':
            blockers.append('仓库、面单、承运商与物流接口尚未完成接入。')
        blockers.extend(['手机可信身份与实际消息回传尚未验收。', '采购、付款、客服和广告等外部执行器仍须各自授权与回读。'])
        return {'schema': 'commerce-operating-control-v1', 'scope': {k: v for k, v in profile.items() if k != 'revision'},
                'configuration_revision': profile['revision'],
                'budget': {'configured': configured, 'currency': 'CNY', 'cap': cny(policy['cap_minor']) if configured else None,
                           'occupied': cny(usage['held_minor']) if configured else None,
                           'spent': cny(usage['gross_paid_minor']) if configured else None,
                           'available': cny(usage['available_minor']) if configured else None,
                           'status': 'halted' if policy['halted'] else 'configured' if configured else 'unconfigured',
                           'period': 'cumulative_pilot',
                           'enforcement': '已接入台账的原任务共享占用；尚未覆盖全部外部执行器。'},
                'store': store, 'mobile': mobile, 'autonomy': {'status': 'preparing', 'external_business_enabled': False, 'blockers': blockers},
                'tasks': self._tasks(synthetic), 'decisions': decisions, 'external_execution_allowed': False}

    def task_submit(self, synthetic, kind, title, details, idempotency_key):
        boolean(synthetic)
        if type(kind) is not str or kind not in KINDS:
            raise ValueError('operating_control_invalid_kind')
        title = text(title, 160, True);details = text(details, 6000)
        key = text(idempotency_key, 160, True)
        task = self.core.invoke('commerce_task_create', {'kind': 'analysis' if kind == 'research' else 'draft',
            'idempotency_key': 'operating-control-' + hashlib.sha256(key.encode()).hexdigest(),
            'input': {'demo': synthetic, 'title': title, 'details': details, 'origin': 'operating_control',
                      'intake_kind': kind, 'external_execution_allowed': False}})
        return {'task_id': task['id'], 'title': title, 'status': task['status'],
                'dispatch_status': 'pending' if task['status'] == 'queued' else 'original_task_state',
                'external_execution_allowed': False}
