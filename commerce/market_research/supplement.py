"""Explicit, version-pinned public research notes; never a webpage capture."""
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlsplit

from business_workflows.evidence import _sources
from business_workflows.store import digest as document_digest
from research import canonical, digest


def references(value):
    try:
        refs = _sources(value)
    except ValueError:
        raise ValueError('market_research_supplement_invalid_sources') from None
    if len(refs) > 12:
        raise ValueError('market_research_supplement_too_many_sources')
    return refs


def public_url(url, kind):
    if not isinstance(url, str) or len(url) > 500:
        raise ValueError('market_research_supplement_invalid_url')
    parsed = urlsplit(url)
    product = (parsed.netloc == 'www.ozon.ru' and
               re.fullmatch(r'/product/[a-zA-Z0-9_-]+-\d+/(reviews/)?', parsed.path))
    guidance = parsed.netloc == 'seller.ozon.ru' and parsed.path.startswith('/media/')
    if (parsed.scheme != 'https' or parsed.query or parsed.fragment
            or not (guidance if kind == 'official_seller_guidance' else product)
            or (kind == 'product_snapshot' and parsed.path.endswith('/reviews/'))):
        raise ValueError('market_research_supplement_invalid_url')


def source_page(service, task_id, ref, source_id):
    try:
        source = service.business.source(ref['id'], ref['version'])
    except ValueError:
        raise ValueError('market_research_supplement_source_missing') from None
    doc = source['document']
    if (source['sha256'] != ref['sha256'] or document_digest(doc) != ref['sha256']
            or not source['fresh'] or not source['current']):
        raise ValueError('market_research_supplement_source_changed_or_stale')
    if (doc['synthetic'] is not False or doc['kind'] != 'facts'
            or doc['scope'] != {'platform': 'ozon', 'store_ref': None, 'subject_ref': task_id}):
        raise ValueError('market_research_supplement_scope_mismatch')
    values = {row['key']: row['value'] for row in doc['records']}
    notes = values.get('source_notes')
    if (values.get('acquisition') != 'remote_indexed_snapshot'
            or values.get('local_live_capture') is not False
            or values.get('review_status') != 'operator_import_unverified'
            or not isinstance(notes, dict)
            or notes.get('kind') not in ('product_snapshot', 'review_snapshot', 'official_seller_guidance')
            or notes.get('url') != doc['origin_ref']
            or not isinstance(notes.get('crawl_age_reported'), str)
            or not 1 <= len(notes['crawl_age_reported']) <= 120):
        raise ValueError('market_research_supplement_invalid_notes')
    public_url(doc['origin_ref'], notes['kind'])
    text = canonical(notes)
    if len(text) > 16000:
        raise ValueError('market_research_supplement_notes_too_large')
    products = []
    if notes['kind'] == 'product_snapshot':
        facts = notes.get('facts')
        if not isinstance(facts, dict) or not isinstance(facts.get('product'), str) or not 1 <= len(facts['product'].strip()) <= 300:
            raise ValueError('market_research_supplement_invalid_product')
        price = facts.get('snapshot_price_rub_other_banks')
        if price is not None:
            try:
                amount = Decimal(str(price))
                if not amount.is_finite() or amount <= 0 or amount > 10**12:
                    raise InvalidOperation()
                price = format(amount, 'f')
            except (InvalidOperation, ValueError):
                raise ValueError('market_research_supplement_invalid_price') from None
        products = [{'title': facts['product'], 'url': doc['origin_ref'],
                     'price': price, 'currency': 'RUB' if price is not None else None, 'text': text}]
    page = {'id': source_id, 'url': doc['origin_ref'], 'title': doc['label'],
            'captured_at': doc['observed_at'], 'imported_at': source['imported_at'],
            'snapshot_age': notes['crawl_age_reported'], 'sha256': ref['sha256'],
            'source_ref': ref, 'text': text, 'products': products,
            'evidence_kind': 'imported_public_notes', 'provenance': 'operator_import_unverified',
            'independently_verified': False}
    page['capture_sha256'] = digest(canonical(page))
    return page


def begin(research, task_id, expected_revision, source_refs, idempotency_key):
    if type(expected_revision) is not int or expected_revision < 1:
        raise ValueError('market_research_revision_conflict')
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key.strip()) <= 160:
        raise ValueError('invalid_idempotency_key')
    refs = references(source_refs)
    request = canonical({'action': 'supplement', 'expected_revision': expected_revision, 'source_refs': refs})
    with research.core.atomic() as db:
        job = research._load(db, task_id)
        old = db.execute('SELECT request FROM market_research_retries WHERE task_id=? AND idem=?', (task_id, idempotency_key)).fetchone()
        if old:
            if old[0] != request:
                raise ValueError('idempotency_conflict')
            return research.public(job)
        if job['revision'] != expected_revision:
            raise ValueError('market_research_revision_conflict')
        failed_batch = job.get('_supplement_batch') if job['status'] == 'failed' else None
        if not failed_batch and (job['status'] not in ('partial', 'completed') or job['phase'] != 'finished'):
            raise ValueError('market_research_supplement_not_ready')
        research.service.copilot._idle(db, job['thread_id'])
        thread = research.service.copilot._thread(db, job['thread_id'])
        if thread['context'] != job['_context'] or job['_context'].get('demo'):
            raise ValueError('market_research_context_changed')
        if len(job['sources']) + len(refs) > 50:
            raise ValueError('market_research_supplement_too_many_sources')
        replacing = set(failed_batch['source_ids']) if failed_batch else set()
        used = {s['source_ref']['id'] for s in job['sources'] if s.get('source_ref') and s['id'] not in replacing
                and s['status'] != 'superseded'}
        if used.intersection(ref['id'] for ref in refs):
            raise ValueError('market_research_supplement_duplicate_source')
        pages = [source_page(research.service, task_id, ref, 'S' + str(len(job['sources']) + i + 1))
                 for i, ref in enumerate(refs)]
        urls = [p['url'] for page in pages for p in page['products']]
        if not urls or len(urls) != len(set(urls)) or set(urls).intersection(c['product_url'] for c in job['candidates']):
            raise ValueError('market_research_supplement_new_product_required')
        if failed_batch:
            job.setdefault('supplement_history', []).append({**failed_batch, 'run_id': job['run_id'],
                'status': job['status'], 'error': job['error']})
            for source in job['sources']:
                if source['id'] in replacing:
                    source['status'] = 'superseded'
        else:
            job.setdefault('report_history', []).append({'revision': job['revision'], 'run_id': job['run_id'],
                'report': job['report'], 'candidate_artifact_ids': [c['artifact_id'] for c in job['candidates']],
                'source_ids': [s['id'] for s in job['sources']]})
        for candidate in job['candidates']:
            candidate.setdefault('research_run_id', job['run_id'])
        job['_captures'].extend(pages)
        for page in pages:
            job['sources'].append({k: v for k, v in page.items() if k not in ('text', 'products', 'capture_sha256')})
            job['sources'][-1].update(status='imported', error=None, excerpt=page['text'][:1200])
        job.update(_analysis=None, _model_pending=None, phase='analyzing',
                   _supplement_batch={'source_ids': [p['id'] for p in pages], 'source_refs': refs})
        payload = db.execute('SELECT payload FROM agent_runs WHERE id=?', (job['run_id'],)).fetchone()[0]
        import json
        research._queue_successor(db, job, json.loads(payload))
        db.execute('INSERT INTO market_research_retries VALUES (?,?,?)', (task_id, idempotency_key, request))
        return research.public(job)


def validate_pinned(research, job):
    for ref in (job.get('_supplement_batch') or {}).get('source_refs', []):
        source_page(research.service, job['task_id'], ref, 'check')
