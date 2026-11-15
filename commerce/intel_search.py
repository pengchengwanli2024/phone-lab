"""Read-only search over current, hash-bound local evidence. No shadow ledger.

Bodies are streamed once per query; only hashes and bounded excerpts survive the
scan. Old captures and superseded Chinese revisions never supply current hits.
"""
import hashlib
import json
from article_binding import bind

EXCERPT = 220
METADATA = ('title', 'country', 'country_code', 'category', 'source')


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def excerpt(text, offset, normalize):
    # Match offsets refer to normalized Unicode; map back without slicing a
    # combining sequence or assuming casefold preserves string length.
    position = 0
    for index, char in enumerate(text):
        position += len(normalize(char))
        if position > offset:
            break
    else:
        index = 0
    start = max(0, index - 45)
    end = min(len(text), start + EXCERPT)
    return ('…' if start else '') + text[start:end] + ('…' if end < len(text) else '')


class LocalEvidenceSearch:
    def __init__(self, rows, patterns, normalize):
        self.rows = {r['id']: r for r in rows}
        self.patterns, self.normalize = patterns, normalize
        self.matches = {r['id']: dict(groups=set(), evidence=[], materials=[]) for r in rows}
        self.coverage = dict(eligible_records=len(rows), records_with_body=0,
                             records_with_translation=0, records_with_translated_title=0,
                             invalid_materials=0, fetch_started=False, model_started=False,
                             method='stream_current_bound_local_evidence', excerpt_characters=EXCERPT)
        for row in rows:
            text = ' '.join(str(row.get(k) or '') for k in METADATA)
            self.add(row, 'metadata', text, sha(text))

    def add(self, row, kind, text, text_sha, **refs):
        found = self.matches[row['id']]
        found['materials'].append([kind, text_sha, refs])
        normalized = self.normalize(text)
        offsets = []
        for index, group in enumerate(self.patterns):
            hits = [pattern.search(normalized) for pattern in group]
            offsets.extend(hit.start() for hit in hits if hit)
            if any(hits):
                found['groups'].add(index)
        if offsets:
            found['evidence'].append(dict(kind=kind, snippet=excerpt(text, min(offsets), self.normalize),
                text_sha256=text_sha, record_sha256=row['record_sha256'], source_url=row['url'],
                independently_verified=False, **refs))

    def read(self, core):
        with core.db() as db:
            if not db.in_transaction:
                db.execute('BEGIN')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if {'intel_reading_bindings', 'intel_reading_jobs', 'translations'} <= tables:
                self.titles(db)
            if 'intel_articles' in tables:
                self.articles(db, 'article_reviews' in tables)

    def titles(self, db):
        records = db.execute('''SELECT b.item_id,b.record_sha,b.job_id,j.manifest,t.status,t.result
            FROM intel_reading_bindings b JOIN intel_reading_jobs j ON j.id=b.job_id
            JOIN translations t ON t.id=j.translation_id''')
        for item_id, record_sha, job_id, manifest, status, result in records:
            row = self.rows.get(item_id)
            if not row or row['record_sha256'] != record_sha or status != 'completed':
                continue
            try:
                refs = json.loads(manifest)
                ref = next(r for r in refs if r['item_id'] == item_id and r['record_sha256'] == record_sha)
                values = json.loads(result)['translations']
                value = next(v for v in values if v['id'] == item_id)
                zh = value['zh']
                if (ref['title'] != row['title'] or value['original_sha256'] != sha(row['title'])
                        or not isinstance(zh, str) or not 0 < len(zh) <= 12000
                        or value['zh_sha256'] != sha(zh)):
                    raise ValueError()
            except (ValueError, TypeError, KeyError, StopIteration):
                self.coverage['invalid_materials'] += 1
                continue
            self.coverage['records_with_translated_title'] += 1
            self.add(row, 'translated_title', zh, sha(zh), reading_job_id=job_id,
                     translation_status='pending_review')

    def captures(self, db):
        ids = list(self.rows)
        for start in range(0, len(ids), 400):
            batch = ids[start:start + 400]
            # Existing item index restricts I/O to eligible records and their
            # newest capture, including a failed capture as the reader does.
            placeholders = ','.join('?' for _ in batch)
            yield from db.execute('''SELECT a.id,a.item_id,a.record_sha,a.doc FROM intel_articles a
                WHERE a.item_id IN (''' + placeholders + ''') AND a.rowid=(
                    SELECT MAX(n.rowid) FROM intel_articles n WHERE n.item_id=a.item_id)''', batch)

    def articles(self, db, reviews):
        for ident, item_id, record_sha, raw in self.captures(db):
            row = self.rows.get(item_id)
            if row['record_sha256'] != record_sha:
                continue
            try:
                doc = json.loads(raw)
                if doc['status'] != 'ready':
                    continue
                article = doc['article']
                text = article['text']
                if (doc['id'] != ident or doc['item_id'] != item_id or doc['record_sha256'] != record_sha
                        or doc['source'] != row['source'] or doc['url'] != row['url'] or article['record_sha256'] != record_sha
                        or article['source_url'] != row['url'] or not isinstance(text, str)
                        or not 0 < len(text) <= 60000 or sha(text) != article['content_sha256']):
                    raise ValueError()
                bind(article)
            except (ValueError, TypeError, KeyError):
                self.coverage['invalid_materials'] += 1
                continue
            self.coverage['records_with_body'] += 1
            self.add(row, 'article', text, article['content_sha256'], article_id=ident)
            self.translation(db, row, doc, reviews)

    def translation(self, db, row, doc, reviews):
        article = doc['article']
        machine = article.get('translation')
        if not machine:
            return
        try:
            zh = machine['zh']
            if (not isinstance(zh, str) or not 0 < len(zh) <= 160000
                    or machine['original_sha256'] != article['content_sha256'] or sha(zh) != machine['zh_sha256']):
                raise ValueError()
            revision = None
            if reviews:
                # Each article has at most 120 review records. Only current
                # revision text is eligible; review/recheck notes aren't sources.
                for (raw,) in db.execute('SELECT document FROM article_reviews WHERE article_id=? ORDER BY rowid DESC', (doc['id'],)):
                    record = json.loads(raw)
                    if record['kind'] == 'revision':
                        revision = record
                        break
            if revision:
                zh = revision['zh']
                if (revision['article_id'] != doc['id'] or revision['record_sha256'] != row['record_sha256']
                        or revision['content_sha256'] != article['content_sha256']
                        or revision['machine_zh_sha256'] != machine['zh_sha256']
                        or not isinstance(zh, str) or not 0 < len(zh) <= 60000 or sha(zh) != revision['zh_sha256']):
                    raise ValueError()
        except (ValueError, TypeError, KeyError):
            self.coverage['invalid_materials'] += 1
            return
        self.coverage['records_with_translation'] += 1
        refs = dict(article_id=doc['id'], translation_status='local_revision' if revision else 'pending_review')
        if revision:
            refs['revision_id'] = revision['id']
        self.add(row, 'revision' if revision else 'translation', zh, sha(zh), **refs)

    def result(self):
        result = []
        for ident, row in self.rows.items():
            found = self.matches[ident]
            if len(found['groups']) == len(self.patterns):
                binding = sha(json.dumps(found['materials'], ensure_ascii=False, sort_keys=True, separators=(',', ':')))
                result.append(dict(row, search_match=dict(material_sha256=binding, evidence=found['evidence'])))
        return result
