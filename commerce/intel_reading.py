"""Explicit Chinese title jobs, bound to public record revisions.

Uses the existing translation executor. Reading or searching never starts a model.
"""
import hashlib
import json
import re
import threading
import uuid
from research import canonical, digest
from intel_map import presentation


def definitions(schema, string):
    return [
        ('commerce_intel_reading_start', '为明确展示的最多20条来源标题生成待校对中文；保留原文与版本，不自动抓取正文',
         schema({'input': {'type': 'object'}, 'idempotency_key': string}, ['input', 'idempotency_key'])),
        ('commerce_intel_reading_get', '读取同一中文标题任务与来源版本状态；不重发翻译',
         schema({'job_id': string}, ['job_id'])),
    ]


class IntelReading:
    def __init__(self, core, intelligence, translations):
        self.core, self.intelligence, self.translations = core, intelligence, translations
        self.lock = threading.Lock()
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS intel_reading_jobs (id TEXT PRIMARY KEY, idem TEXT UNIQUE, request_sha TEXT, manifest TEXT, translation_id TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS intel_reading_bindings (item_id TEXT, record_sha TEXT, job_id TEXT, PRIMARY KEY(item_id,record_sha))')

    def start(self, input, idempotency_key):
        if not isinstance(input, dict) or set(input) != {'records'}:
            raise ValueError('invalid_intel_reading_input')
        records = input['records']
        if not isinstance(records, list) or not 1 <= len(records) <= 20:
            raise ValueError('intel_reading_batch_size')
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 100:
            raise ValueError('invalid_idempotency_key')
        seen = set()
        for ref in records:
            if (not isinstance(ref, dict) or set(ref) != {'item_id', 'record_sha256'}
                    or not isinstance(ref['item_id'], str) or not re.fullmatch('[a-f0-9]{24}', ref['item_id'])
                    or not isinstance(ref['record_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', ref['record_sha256'])
                    or ref['item_id'] in seen):
                raise ValueError('invalid_intel_reading_record')
            seen.add(ref['item_id'])
        request_sha = digest(canonical(input))
        with self.lock:
            with self.core.db() as db:
                old = db.execute('SELECT id,request_sha FROM intel_reading_jobs WHERE idem=?', (idempotency_key,)).fetchone()
            if old:
                if old[1] != request_sha:
                    raise ValueError('idempotency_conflict')
                return self.get(old[0])
            manifest = []
            for ref in records:
                row = self.intelligence.store.item(ref['item_id'])
                if row['record_sha256'] != ref['record_sha256']:
                    raise ValueError('intel_record_changed')
                manifest.append(dict(ref, title=row['title']))
            with self.core.db() as db:
                previous = db.execute('SELECT id FROM intel_reading_jobs WHERE request_sha=? ORDER BY rowid DESC LIMIT 1',
                                      (request_sha,)).fetchone()
            if previous:
                existing = self.get(previous[0])
                if existing['status'] in ('queued', 'running', 'completed'):
                    return existing
            data = {'language': 'auto', 'items': [{'id': r['item_id'], 'text': r['title']} for r in manifest]}
            # Stable executor key also recovers an interrupted link save without
            # replaying an already accepted model request.
            key = 'intel-title:' + hashlib.sha256(idempotency_key.encode()).hexdigest()
            translated = self.translations.start(data, key)
            ident = uuid.uuid4().hex
            with self.core.db() as db:
                db.execute('INSERT INTO intel_reading_jobs VALUES (?,?,?,?,?)',
                           (ident, idempotency_key, request_sha, canonical(manifest), translated['id']))
                for ref in manifest:
                    db.execute('INSERT OR REPLACE INTO intel_reading_bindings VALUES (?,?,?)',
                               (ref['item_id'], ref['record_sha256'], ident))
            return self.get(ident)

    def get(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch('[a-f0-9]{32}', job_id):
            raise ValueError('invalid_intel_reading_job')
        with self.core.db() as db:
            row = db.execute('SELECT manifest,translation_id FROM intel_reading_jobs WHERE id=?', (job_id,)).fetchone()
            current = {r[0]: json.loads(r[1])['record_sha256'] for r in db.execute('SELECT id,item FROM intel_archive')}
        if not row:
            raise ValueError('intel_reading_not_found')
        manifest = json.loads(row[0])
        job = self.translations.get(row[1])
        readings = []
        if job['status'] == 'completed':
            output = {r['id']: r for r in job['result']['translations']}
            if len(output) != len(manifest):
                raise ValueError('intel_reading_binding_mismatch')
            for ref in manifest:
                value = output.get(ref['item_id'])
                if not value or value.get('original_sha256') != digest(ref['title']):
                    raise ValueError('intel_reading_binding_mismatch')
                readings.append(dict(item_id=ref['item_id'], record_sha256=ref['record_sha256'],
                                     original_title=ref['title'], zh_title=value['zh'],
                                     zh_sha256=value['zh_sha256'], warnings=value.get('warnings', []),
                                     status='pending_review', independently_verified=False,
                                     source_record_changed=current.get(ref['item_id']) != ref['record_sha256']))
        receipt = {k: (job.get('result') or {}).get(k) for k in ('provider','model','translated_at','prompt_version')}
        return dict(id=job_id, status=job['status'], readings=readings,
                    error=(job.get('result') or {}).get('error'), model_receipt=receipt)

    def decorate(self, result):
        rows = [*result.get('items', []), *result.get('markers', [])]
        for panel in result.get('panels', {}).values():
            rows.extend(panel.get('items', []))
        for row in rows:
            row['display'] = presentation(row)
        with self.core.db() as db:
            bindings = {r['id']: db.execute('SELECT job_id FROM intel_reading_bindings WHERE item_id=? AND record_sha=?',
                                            (r['id'], r['record_sha256'])).fetchone() for r in rows}
        jobs = {}
        for row in rows:
            binding = bindings[row['id']]
            if not binding:
                continue
            ident = binding[0]
            if ident not in jobs:
                jobs[ident] = self.get(ident)
            reading = next((r for r in jobs[ident]['readings'] if r['item_id'] == row['id']), None)
            if reading and not reading['source_record_changed']:
                row['reading'] = reading
        return result
