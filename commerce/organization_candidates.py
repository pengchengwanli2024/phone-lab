"""Explicit local candidate intake; no service initialization or inventory writes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import uuid

from research import canonical, digest


def create_candidate(database, context, *, key, name, source_ref, currency=None):
    if not isinstance(context, dict) or set(context) != {'case_id', 'scope_sha256', 'origin'} or context['origin'] != 'manual':
        raise ValueError('invalid_exchange_context')
    if not isinstance(key, str) or not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', key):
        raise ValueError('invalid_candidate_key')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120 or any(ord(c) < 32 for c in name):
        raise ValueError('invalid_candidate_name')
    if not isinstance(source_ref, str) or not 1 <= len(source_ref.strip()) <= 500:
        raise ValueError('candidate_source_reference_required')
    if currency is not None and (not isinstance(currency, str) or not re.fullmatch('[A-Z]{3}', currency)):
        raise ValueError('explicit_currency_required')
    database = Path(database)
    if database.is_symlink() or not database.is_file():
        raise ValueError('existing_private_database_required')
    db = sqlite3.connect(database.resolve().as_uri() + '?mode=rw', uri=True, timeout=10)
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            anchor = db.execute('SELECT id,connection,scope,currency,created FROM org_cases WHERE id=?', (context['case_id'],)).fetchone()
            if not anchor:
                raise ValueError('organization_case_not_found')
            old_scope = json.loads(anchor[2])
            before = dict(id=anchor[0], scope=old_scope, currency=anchor[3], created_at=anchor[4])
            if digest(canonical(before)) != context['scope_sha256']:
                raise ValueError('exchange_scope_changed_refresh_binding')
            if old_scope.get('platform') != 'ozon' or old_scope.get('market') != 'RU' or not anchor[1]:
                raise ValueError('candidate_requires_explicit_ozon_ru_scope')
            scope = dict(platform='ozon', market='RU', fulfillment=old_scope['fulfillment'],
                         product_id=None, row_key='candidate:' + key, sku='CANDIDATE:' + key,
                         inventory_type='candidate', origin='research_candidate_not_inventory',
                         label=name.strip(), source_ref=source_ref.strip())
            prior = db.execute('SELECT id,scope,currency,created FROM org_cases WHERE connection=? AND row_key=?', (anchor[1], scope['row_key'])).fetchone()
            if prior:
                if json.loads(prior[1]) != scope or currency is not None and prior[2] != currency:
                    raise ValueError('candidate_key_conflict')
                ident, saved_currency, created_at = prior[0], prior[2], prior[3]
                created = False
            else:
                ident, saved_currency, created_at = uuid.uuid4().hex, currency, datetime.now(timezone.utc).isoformat()
                db.execute('INSERT INTO org_cases VALUES (?,?,?,?,?,?)', (ident, anchor[1], scope['row_key'], canonical(scope), currency, created_at))
                created = True
        return dict(case=dict(id=ident, scope=scope, currency=saved_currency, created_at=created_at),
                    created=created, inventory_created=False, marketplace_writes=False,
                    verification='research_candidate_identity_only_not_product_facts')
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description='Create an explicit local research candidate in the existing organization board.')
    parser.add_argument('--anchor-case', help='Existing active case determines connection and market scope only.')
    parser.add_argument('--key', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--source-ref', required=True)
    parser.add_argument('--currency', help='Explicit planning currency; no currency conversion is performed.')
    args = parser.parse_args()
    from runtime import STATE, request
    board = request('commerce_organization_board', {'case_id': args.anchor_case} if args.anchor_case else {}, 'codex')
    if not board.get('case'):
        raise SystemExit('an_existing_active_scope_is_required')
    context = request('commerce_organization_exchange_status', {'case_id': board['case']['id']}, 'codex')['context']
    result = create_candidate(STATE / 'commerce.sqlite', context, key=args.key, name=args.name,
                              source_ref=args.source_ref, currency=args.currency)
    # Read back through the running service, rather than claiming source-only activation.
    observed = request('commerce_organization_board', {'case_id': result['case']['id']}, 'codex')
    if observed['case'] != result['case']:
        raise SystemExit('candidate_readback_mismatch')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
