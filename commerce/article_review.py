"""Append-only local revision/review declarations; original model output stays intact."""
import json,time,uuid
from article_binding import text_hash
from research import canonical,drift

class ArticleReviews:
    def __init__(self,core,articles):
        self.core,self.articles=core,articles
        with core.db() as db:db.execute('CREATE TABLE IF NOT EXISTS article_reviews (id TEXT PRIMARY KEY,article_id TEXT,idem TEXT UNIQUE,fingerprint TEXT,document TEXT)')

    def listing(self,article_id):
        self.articles.get(article_id)
        with self.core.db() as db:records=[json.loads(r[0]) for r in db.execute('SELECT document FROM article_reviews WHERE article_id=? ORDER BY rowid',(article_id,))]
        return {'records':records,'machine_translation_immutable':True,'checker_version':'calendar-cjk-v2','declaration_is_identity_proof':False}

    def record(self,article_id,operation,idempotency_key,client='local',**data):
        if not isinstance(idempotency_key,str) or not idempotency_key.strip() or len(idempotency_key)>160:raise ValueError('invalid_idempotency_key')
        if operation not in ('recheck','revision','review'):raise ValueError('invalid_article_review_operation')
        fingerprint=text_hash(canonical(dict(article_id=article_id,operation=operation,client=client,**data)))
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT fingerprint,document FROM article_reviews WHERE idem=?',(idempotency_key,)).fetchone()
            if old:
                if old[0]!=fingerprint:raise ValueError('idempotency_conflict')
                return json.loads(old[1])
            doc=self.articles.get(article_id)
            if doc['source_record_changed']:raise ValueError('intel_record_changed')
            article=doc.get('article',{});machine=article.get('translation')
            if not machine:raise ValueError('article_translation_required')
            existing=[json.loads(r[0]) for r in db.execute('SELECT document FROM article_reviews WHERE article_id=? ORDER BY rowid',(article_id,))]
            if len(existing)>=120:raise ValueError('article_review_record_limit')
            base=next((r for r in reversed(existing) if r['kind']=='revision'),None)
            expected=base['zh_sha256'] if base else machine['zh_sha256']
            if data.get('base_sha256')!=expected:raise ValueError('article_revision_conflict')
            text=base['zh'] if base else machine['zh']
            note=data.get('note','')
            if not isinstance(note,str) or len(note)>2000:raise ValueError('invalid_review_note')
            if operation=='revision':
                text=data.get('zh')
                if not isinstance(text,str) or not text.strip() or len(text)>60000:raise ValueError('invalid_article_revision')
            if operation=='review':
                if data.get('decision') not in ('approved','needs_changes') or data.get('confirmed') is not True:raise ValueError('explicit_review_confirmation_required')
                if not note.strip():raise ValueError('review_note_required')
            value=dict(id=uuid.uuid4().hex,article_id=article_id,kind=operation,created_at=time.time(),actor_channel=str(client)[:80],
                       content_sha256=article['content_sha256'],record_sha256=doc['record_sha256'],machine_zh_sha256=machine['zh_sha256'],
                       base_sha256=expected,zh_sha256=text_hash(text),warnings=drift(article['text'],text),checker_version='calendar-cjk-v2',
                       note=note,status=data['decision'] if operation=='review' else 'pending_review',
                       independently_verified=False,declaration_is_identity_proof=False)
            if operation=='revision':value['zh']=text
            if operation=='review':value['reviewed_revision_id']=base['id'] if base else None
            db.execute('INSERT INTO article_reviews VALUES (?,?,?,?,?)',(value['id'],article_id,idempotency_key,fingerprint,canonical(value)))
        return value
