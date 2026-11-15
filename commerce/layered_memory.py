"""Business L1 references -> explicitly confirmed L2 -> deterministic L3.

L1 remains in business_source_versions. No duplicate evidence store, model calls,
global assistant memory changes or automatic promotion of imported assertions.
"""
import json
import time
import uuid

from business_workflows.store import digest, encoded, text


class LayeredMemory:
    def __init__(self, service):
        self.service, self.core = service, service.core
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS knowledge_layers(id TEXT PRIMARY KEY,document TEXT NOT NULL,status TEXT NOT NULL,revision INTEGER NOT NULL,created REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS knowledge_layer_requests(key TEXT PRIMARY KEY,sha256 TEXT NOT NULL,memory_id TEXT NOT NULL)')

    def _once(self, db, key, body, make):
        text(key);sha = digest(body)
        old = db.execute('SELECT sha256,memory_id FROM knowledge_layer_requests WHERE key=?', (key,)).fetchone()
        if old:
            if old[0] != sha:raise ValueError('memory_idempotency_conflict')
            return old[1]
        ident = make()
        db.execute('INSERT INTO knowledge_layer_requests VALUES (?,?,?)', (key, sha, ident))
        return ident

    def _bindings(self, bindings):
        if type(bindings) is not list or not 1 <= len(bindings) <= 20:raise ValueError('memory_invalid_bindings')
        scope = mode = None
        seen = set()
        for binding in bindings:
            if type(binding) is not dict or set(binding) != {'source_id', 'version', 'sha256', 'record_key', 'quote'}:
                raise ValueError('memory_invalid_binding')
            for key in ('source_id', 'sha256', 'record_key'):text(binding[key], 160)
            text(binding['quote'], 6000)
            if type(binding['version']) is not int or binding['version'] < 1:raise ValueError('memory_invalid_binding')
            source = self.service.business.source(binding['source_id'])
            if (source['version'] != binding['version'] or source['sha256'] != binding['sha256'] or
                    digest(source['document']) != source['sha256'] or not source['fresh']):
                raise ValueError('memory_source_changed')
            doc = source['document']
            if scope is None:scope, mode = doc['scope'], doc['synthetic']
            elif scope != doc['scope'] or mode != doc['synthetic']:raise ValueError('memory_scope_mismatch')
            matches = [row for row in doc['records'] if row.get('key', row.get('id')) == binding['record_key']]
            if len(matches) != 1:raise ValueError('memory_record_not_found')
            record = matches[0];value = record.get('text', record.get('value'))
            original = value if isinstance(value, str) else encoded(value)
            if binding['quote'] not in original:raise ValueError('memory_quote_not_found')
            marker = encoded(binding)
            if marker in seen:raise ValueError('memory_duplicate_binding')
            seen.add(marker)
        return scope, mode

    def _load(self, ident):
        text(ident)
        with self.core.db() as db:row = db.execute('SELECT * FROM knowledge_layers WHERE id=?', (ident,)).fetchone()
        if row is None:raise ValueError('memory_not_found')
        return row, json.loads(row[1])

    def get(self, memory_id):
        row, doc = self._load(memory_id)
        state, reason = row[2], None
        if state != 'withdrawn':
            try:
                if doc['layer'] == 'L2':self._bindings(doc['bindings'])
                else:
                    for ref in doc['fact_refs']:
                        fact = self.get(ref['id'])
                        if fact['effective_status'] != 'confirmed' or fact['revision'] != ref['revision'] or fact['sha256'] != ref['sha256']:
                            raise ValueError('memory_fact_changed')
            except ValueError as exc:
                state, reason = 'stale', str(exc)
        sha = digest({'document': doc, 'status': row[2], 'revision': row[3]})
        return {'id': row[0], **doc, 'status': row[2], 'effective_status': state, 'invalid_reason': reason,
                'revision': row[3], 'sha256': sha, 'created_at': row[4],
                'confirmation_scope': 'operator_confirmation_not_independent_verification',
                'external_execution_allowed': False}

    def _insert(self, db, doc, status):
        if db.execute('SELECT count(*) FROM knowledge_layers').fetchone()[0] >= 5000:raise ValueError('memory_capacity_reached')
        ident = 'memory_' + uuid.uuid4().hex
        db.execute('INSERT INTO knowledge_layers VALUES (?,?,?,?,?)', (ident, encoded(doc), status, 1, time.time()))
        return ident

    def propose(self, content, bindings, idempotency_key, supersedes=None):
        text(content, 4000)
        with self.core.atomic() as db:
            def make():
                scope, mode = self._bindings(bindings)
                doc = {'layer': 'L2', 'content': content, 'bindings': bindings, 'scope': scope, 'synthetic': mode}
                if supersedes:
                    previous = self.get(supersedes)
                    if previous['layer'] != 'L2' or previous['status'] != 'confirmed' or previous['scope'] != scope or previous['synthetic'] != mode:
                        raise ValueError('memory_correction_scope_mismatch')
                    doc['supersedes'] = {k: previous[k] for k in ('id', 'revision', 'sha256')}
                return self._insert(db, doc, 'proposed')
            ident = self._once(db, idempotency_key, {'action': 'propose', 'content': content, 'bindings': bindings, 'supersedes': supersedes}, make)
        return self.get(ident)

    def decide(self, action, memory_id, expected_revision, expected_sha256, confirmed, idempotency_key):
        if confirmed is not True:raise ValueError('memory_explicit_confirmation_required')
        if type(expected_revision) is not int or expected_revision < 1:raise ValueError('memory_revision_conflict')
        with self.core.atomic() as db:
            def make():
                current = self.get(memory_id)
                if current['revision'] != expected_revision or current['sha256'] != expected_sha256:
                    raise ValueError('memory_revision_conflict')
                if action == 'confirm':
                    if current['layer'] != 'L2' or current['effective_status'] != 'proposed':raise ValueError('memory_fact_not_confirmable')
                    prior = current.get('supersedes')
                    if prior:
                        old = self.get(prior['id'])
                        if old['revision'] != prior['revision'] or old['sha256'] != prior['sha256'] or old['status'] != 'confirmed':
                            raise ValueError('memory_correction_changed')
                        db.execute("UPDATE knowledge_layers SET status='withdrawn',revision=revision+1 WHERE id=?", (old['id'],))
                    status = 'confirmed'
                else:status = 'withdrawn'
                db.execute('UPDATE knowledge_layers SET status=?,revision=revision+1 WHERE id=?', (status, memory_id))
                return memory_id
            ident = self._once(db, idempotency_key, {'action': action, 'id': memory_id,
                'revision': expected_revision, 'sha256': expected_sha256}, make)
        return self.get(ident)

    def summarize(self, fact_ids, title, idempotency_key):
        text(title, 160)
        if type(fact_ids) is not list or not 1 <= len(fact_ids) <= 20 or any(type(v) is not str for v in fact_ids) or len(set(fact_ids)) != len(fact_ids):
            raise ValueError('memory_invalid_fact_ids')
        with self.core.atomic() as db:
            def make():
                facts = [self.get(i) for i in sorted(fact_ids)]
                if any(f['layer'] != 'L2' or f['effective_status'] != 'confirmed' for f in facts):raise ValueError('memory_fact_not_confirmed')
                first = facts[0]
                if any(f['scope'] != first['scope'] or f['synthetic'] != first['synthetic'] for f in facts):raise ValueError('memory_scope_mismatch')
                doc = {'layer': 'L3', 'title': title, 'content': '\n'.join('- ' + f['content'] for f in facts),
                       'fact_refs': [{k: f[k] for k in ('id', 'revision', 'sha256')} for f in facts],
                       'scope': first['scope'], 'synthetic': first['synthetic'], 'method': 'confirmed_fact_excerpt_no_model'}
                return self._insert(db, doc, 'active')
            ident = self._once(db, idempotency_key, {'action': 'summarize', 'fact_ids': fact_ids, 'title': title}, make)
        return self.get(ident)

    def listing(self, synthetic):
        if type(synthetic) is not bool:raise ValueError('memory_invalid_mode')
        with self.core.db() as db:rows = db.execute('SELECT id,document FROM knowledge_layers ORDER BY created DESC').fetchall()
        selected = [r[0] for r in rows if json.loads(r[1])['synthetic'] == synthetic]
        return {'items': [self.get(i) for i in selected[:500]], 'truncated': len(selected) > 500}

    def sources(self, synthetic):
        return {'items': self.service.business.listing(synthetic)['sources'], 'layer': 'L1', 'independently_verified': False}

    def search(self, query, synthetic):
        text(query, 160);hits = []
        if type(synthetic) is not bool:raise ValueError('memory_invalid_mode')
        needle = query.casefold()
        catalog = self.listing(synthetic)
        for item in catalog['items']:
            if item['effective_status'] in ('confirmed', 'active') and needle in item['content'].casefold():hits.append(item)
        for source in self.sources(synthetic)['items']:
            current = self.service.business.source(source['id'])
            if not current['fresh'] or digest(current['document']) != current['sha256']:continue
            for record in current['document']['records']:
                value = record.get('text', record.get('value'))
                raw = value if isinstance(value, str) else encoded(value)
                if needle in raw.casefold():
                    hits.append({'id': source['id'], 'layer': 'L1', 'content': raw[:1000], 'scope': source['scope'],
                                 'status': 'imported_unverified', 'version': current['version'], 'sha256': current['sha256'],
                                 'record_key': record.get('key', record.get('id')), 'synthetic': synthetic})
                if len(hits) >= 100:break
            if len(hits) >= 100:break
        return {'hits': hits[:100], 'truncated': catalog['truncated'] or len(hits) >= 100,
                'scope': 'existing_business_sources_only', 'external_execution_allowed': False}

    def invoke(self, name, args):
        action = name.removeprefix('commerce_memory_')
        if action in ('confirm', 'withdraw'):return self.decide(action, **args)
        return {'propose': self.propose, 'get': self.get, 'summarize': self.summarize, 'list': self.listing,
                'search': self.search, 'sources': self.sources}[action](**args)


def definitions(schema):
    s = {'type': 'string', 'minLength': 1, 'maxLength': 160}
    mode = {'synthetic': {'type': 'boolean'}}
    binding = schema({'source_id': s, 'version': {'type': 'integer', 'minimum': 1}, 'sha256': s,
                      'record_key': s, 'quote': {'type': 'string', 'minLength': 1, 'maxLength': 6000}},
                     ['source_id', 'version', 'sha256', 'record_key', 'quote'])
    return [
        ('commerce_memory_sources', '读取已有业务资料L1来源；导入不等于核实，不复制原始资料。', schema(mode, ['synthetic'])),
        ('commerce_memory_list', '读取同一合成/真实范围的L2/L3及当前失效状态。', schema(mode, ['synthetic'])),
        ('commerce_memory_search', '检索业务资料L1和当前有效的已确认L2/摘要L3；未确认或失效内容不冒充事实。', schema({**mode, 'query': s}, ['synthetic', 'query'])),
        ('commerce_memory_get', '读取业务记忆、绑定和来源变化/撤回状态。', schema({'memory_id': s}, ['memory_id'])),
        ('commerce_memory_propose', '从已有业务资料的准确版本与原文引文保存L2待确认事实；可明确纠正同范围旧事实。', schema({
            'content': {'type': 'string', 'minLength': 1, 'maxLength': 4000}, 'bindings': {'type': 'array', 'items': binding, 'minItems': 1, 'maxItems': 20},
            'supersedes': s, 'idempotency_key': s}, ['content', 'bindings', 'idempotency_key'])),
        *[(f'commerce_memory_{action}', description, schema({'memory_id': s, 'expected_revision': {'type': 'integer', 'minimum': 1},
            'expected_sha256': s, 'confirmed': {'type': 'boolean'}, 'idempotency_key': s},
            ['memory_id', 'expected_revision', 'expected_sha256', 'confirmed', 'idempotency_key']))
          for action, description in [('confirm', '明确确认准确版本的L2；操作者确认不等于独立核实，不授权经营执行。'),
                                      ('withdraw', '明确撤回准确版本业务记忆，依赖摘要随后失效。')]],
        ('commerce_memory_summarize', '按同范围已确认且有效事实生成确定性摘录摘要L3；不增加新断言或调用模型。', schema({
            'fact_ids': {'type': 'array', 'items': s, 'minItems': 1, 'maxItems': 20}, 'title': s, 'idempotency_key': s},
            ['fact_ids', 'title', 'idempotency_key'])),
    ]
