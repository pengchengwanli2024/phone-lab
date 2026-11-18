"""Listing lineage: pure audit/impact/export, shared HTTP + stdio contract and template.

Synthetic documents only; the model is a stub and nothing leaves the process.
"""
import copy
import csv
import io
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import listing_lineage as lineage

TOOLS = ('commerce_listing_lineage_audit', 'commerce_listing_lineage_impact', 'commerce_listing_lineage_export',
         'commerce_listing_lineage_facts_draft')


def document():
    return {
        'facts': [{'id': 'F-001', 'dimension': 'material', 'statement': 'Synthetic: 100% polyester, 180 gsm', 'proof': ['synthetic-report-1']},
                  {'id': 'F-002', 'dimension': 'care', 'statement': 'Synthetic: machine washable', 'proof': []},
                  {'id': 'F-003', 'dimension': 'pack', 'statement': 'Synthetic: 2 pieces', 'proof': ['synthetic-photo-3']}],
        'keywords': [{'id': 'K-004', 'term': 'Wrinkle Free'}, {'id': 'K-019', 'term': 'travel dress'}, {'id': 'K-020', 'term': 'unused term'}],
        'claims': [{'id': 'C-012', 'statement': 'Wrinkle free drape', 'fact_ids': ['F-001'], 'keyword_ids': ['K-004', 'K-019'],
                    'insight_refs': ['synthetic review theme: wrinkles']},
                   {'id': 'C-013', 'statement': 'Soft and breathable', 'insight_refs': ['synthetic review theme: softness']},
                   {'id': 'C-014', 'statement': 'Machine washable', 'fact_ids': ['F-002']},
                   {'id': 'C-015', 'statement': 'Antibacterial fabric', 'fact_ids': ['F-001']},
                   {'id': 'C-016', 'statement': 'Set of two', 'fact_ids': ['F-003']},
                   {'id': 'C-017', 'statement': 'Certified', 'fact_ids': ['F-999']}],
        'fields': [{'id': 'Title', 'channel': 'Amazon US', 'text': 'Wrinkle  free travel dress, set of two',
                    'claim_ids': ['C-012', 'C-016'], 'keyword_ids': ['K-004', 'K-019'], 'version': 'v1.2', 'max_chars': 200},
                   {'id': 'Bullet_2', 'channel': 'Amazon US', 'text': 'Soft, machine washable.', 'claim_ids': ['C-013', 'C-014']},
                   {'id': 'Bullet_3', 'channel': 'Amazon US', 'text': 'Set of two with ANTIBACTERIAL finish', 'claim_ids': ['C-016'],
                    'keyword_ids': ['K-019'], 'max_chars': 10},
                   {'id': 'Title', 'channel': 'Ozon RU', 'text': 'Комплект из двух', 'claim_ids': ['C-016']}],
        'restricted_terms': [{'term': 'antibacterial', 'reason': 'synthetic: no test report'}]}


class PureLineage(unittest.TestCase):
    def test_audit_rejects_claims_without_evidence_and_holds_fields_citing_them(self):
        result = lineage.audit(document())
        claims = {c['id']: c for c in result['claims']}
        self.assertEqual({k: v['audit_status'] for k, v in claims.items()}, {
            'C-012': 'passed', 'C-013': 'rejected_no_evidence', 'C-014': 'needs_proof',
            'C-015': 'rejected_restricted_term', 'C-016': 'passed', 'C-017': 'rejected_no_evidence'})
        self.assertEqual(claims['C-017']['reasons'], [{'code': 'fact_not_found', 'ids': ['F-999']}])
        fields = {(f['channel'], f['id']): f for f in result['fields']}
        self.assertEqual(fields[('Amazon US', 'Title')]['status'], 'ready')
        self.assertEqual(fields[('Ozon RU', 'Title')]['status'], 'ready')
        self.assertEqual(fields[('Amazon US', 'Bullet_2')]['blocking'], [{'code': 'claim_not_passed', 'ids': ['C-013', 'C-014']}])
        codes = [b['code'] for b in fields[('Amazon US', 'Bullet_3')]['blocking']]
        self.assertEqual(codes, ['restricted_term', 'over_length'])
        self.assertEqual(fields[('Amazon US', 'Bullet_3')]['warnings'], [{'code': 'keyword_not_in_text', 'ids': ['K-019']}])
        self.assertEqual(result['status'], 'HOLD')
        self.assertEqual(result['coverage']['claims_from_insight_only'], ['C-013'])
        self.assertEqual(result['coverage']['keywords_unplaced'], ['K-020'])
        self.assertEqual(result['coverage']['claims_unused'], ['C-015', 'C-017'])
        self.assertEqual(claims['C-016']['used_in'][2], {'channel': 'Ozon RU', 'field_id': 'Title'})
        self.assertIs(result['external_execution_allowed'], False)
        self.assertIs(result['review_required'], True)

    def test_pass_requires_every_field_clean_and_is_stable_for_equal_documents(self):
        doc = document()
        doc['fields'] = [doc['fields'][0], doc['fields'][3]]
        first = lineage.audit(doc)
        self.assertEqual(first['status'], 'PASS')
        self.assertEqual(first['document_sha256'], lineage.audit(copy.deepcopy(doc))['document_sha256'])
        doc['facts'][0]['statement'] += ' (changed)'
        self.assertNotEqual(first['document_sha256'], lineage.audit(doc)['document_sha256'])
        doc['fields'] = []
        self.assertEqual(lineage.audit(doc)['status'], 'HOLD')

    def test_insight_reference_never_substitutes_for_a_product_fact(self):
        doc = document()
        doc['claims'][1]['insight_refs'] = ['synthetic theme ' + str(i) for i in range(20)]
        status = {c['id']: c['audit_status'] for c in lineage.audit(doc)['claims']}
        self.assertEqual(status['C-013'], 'rejected_no_evidence')

    def test_impact_locates_exact_fields_across_channels(self):
        result = lineage.impact(document(), {'fact_ids': ['F-003']})
        self.assertEqual([(f['channel'], f['field_id']) for f in result['affected_fields']],
                         [('Amazon US', 'Title'), ('Amazon US', 'Bullet_3'), ('Ozon RU', 'Title')])
        self.assertEqual(result['affected_claims'], [{'claim_id': 'C-016', 'via': ['F-003']}])
        self.assertEqual(result['unaffected_field_count'], 1)
        by_claim = lineage.impact(document(), {'claim_ids': ['C-014', 'C-404']})
        self.assertEqual([f['field_id'] for f in by_claim['affected_fields']], ['Bullet_2'])
        self.assertEqual(by_claim['unknown_ids'], ['C-404'])
        by_keyword = lineage.impact(document(), {'keyword_ids': ['K-019']})
        self.assertEqual([f['field_id'] for f in by_keyword['affected_fields']], ['Title', 'Bullet_3'])
        self.assertEqual(by_keyword['affected_fields'][1]['claims'], [])
        with self.assertRaisesRegex(ValueError, 'lineage_empty_change'):
            lineage.impact(document(), {})

    def test_export_tables_parse_and_neutralize_formula_cells(self):
        doc = document()
        doc['fields'][1]['text'] = '=HYPERLINK("https://example.invalid")'
        result = lineage.export(doc)
        rows = {name: list(csv.reader(io.StringIO(text))) for name, text in result['tables'].items()}
        self.assertEqual(set(rows), {'Product_Facts', 'Keywords', 'Claims_Pool', 'Listing_Output'})
        self.assertEqual(rows['Claims_Pool'][1][:4], ['C-012', 'Wrinkle free drape', 'K-004, K-019', 'F-001'])
        self.assertEqual(rows['Claims_Pool'][2][5], 'rejected_no_evidence')
        self.assertEqual(rows['Listing_Output'][2][2], "'=HYPERLINK(\"https://example.invalid\")")
        self.assertEqual(len(rows['Listing_Output']), 5)
        self.assertEqual(result['link_columns']['Listing_Output.引用的Claim_IDs'], 'Claims_Pool.Claim_ID')
        self.assertIs(result['external_execution_allowed'], False)

    def test_malformed_documents_are_rejected(self):
        def changed(edit):
            doc = document();edit(doc);return doc
        cases = [
            lambda d: d.pop('facts'),
            lambda d: d.update(extra=1),
            lambda d: d.update(schema='other'),
            lambda d: d['facts'].append(dict(d['facts'][0])),
            lambda d: d['fields'].append(dict(d['fields'][0])),
            lambda d: d['facts'][0].update(id='X-1'),
            lambda d: d['claims'][0].update(fact_ids=['F-001', 'F-001']),
            lambda d: d['claims'][0].update(fact_ids='F-001'),
            lambda d: d['claims'][0].update(statement=' '),
            lambda d: d['fields'][0].update(version='latest'),
            lambda d: d['fields'][0].update(max_chars=True),
            lambda d: d['fields'][0].update(unknown=1),
            lambda d: d.update(claims=[{'id': 'C-' + str(i), 'statement': 's'} for i in range(301)]),
        ]
        for index, edit in enumerate(cases):
            with self.subTest(case=index), self.assertRaisesRegex(ValueError, '^lineage_'):
                lineage.audit(changed(edit))
        for value in (None, [], 'text'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '^lineage_'):
                lineage.audit(value)

    def test_template_is_synthetic_and_auditable(self):
        template = lineage.template()
        self.assertIs(template['synthetic'], True)
        self.assertEqual(lineage.audit(template['document'])['status'], 'PASS')


def dossier():
    def source(ident, kind, **extra):
        return {'id': ident, 'revision': 2, 'sha256': ident * 8, 'kind': kind, 'label': 'Synthetic ' + ident,
                'url': 'https://example.invalid/' + ident, 'archived': False, 'review_state': 'checked',
                'independently_verified': False, 'model': '', 'variant': '', **extra}
    return {'case_id': 'case-synthetic', 'dossier_sha256': 'd' * 64, 'sources': [
        source('s1', 'supplier', model='YS2607F', variant='12 double-sided cards, blue pen', review_state='unreviewed'),
        source('s2', 'supplier', model='YS2607C', variant='Spanish cards', review_state='conflict'),
        source('c1', 'competitor', model='ZABIAKA 4648407', variant='12 cards'),
        source('m1', 'market', variant='store search terms'),
        source('d1', 'document', model='YS2607F', variant='blue pen, 12 double-sided cards'),
        source('d2', 'document'),
        source('old', 'supplier', model='retired', archived=True)]}


def catalog():
    return {'source_sha256': 'e' * 64, 'fields': [
        {'key': 'subject', 'original': 'корзина подвесная 30,5x17,5x9,5см', 'kind': 'source_statement',
         'reviewed': False, 'source_url': 'https://example.invalid/p', 'locator': 'S1:P3'},
        {'key': 'findings', 'original': 'likely fits cabinet doors', 'kind': 'inference'}]}


class FactsDraft(unittest.TestCase):
    def test_facts_come_only_from_records_that_describe_this_product(self):
        result = lineage.facts_draft(dossier(), catalog())
        self.assertEqual([(f['dimension'], f['statement']) for f in result['facts']],
                         [('型号', 'YS2607F'), ('规格/变体', 'blue pen, 12 double-sided cards'),
                          ('来源原文:subject', 'корзина подвесная 30,5x17,5x9,5см')])
        self.assertTrue(all(f['proof'] == [] for f in result['facts']))
        self.assertEqual([f['id'] for f in result['facts']], ['F-001', 'F-002', 'F-003'])
        origin = result['candidates'][0]['origin']
        self.assertEqual((origin['id'], origin['revision'], origin['field']), ('d1', 2, 'model'))
        self.assertNotIn('identity_confirmed_by_caller', origin)
        reasons = {(row.get('id') or row.get('key')): row['reason'] for row in result['excluded']}
        self.assertEqual(reasons, {'s2': 'source_in_conflict', 'c1': 'competitor_not_product_evidence',
                                   'm1': 'not_product_attribute_source', 'd2': 'no_attribute_fields',
                                   'old': 'archived_source', 'findings': 'inference_not_fact'})
        self.assertEqual(result['insight_candidates'], ['Synthetic c1'])
        self.assertEqual((result['status'], result['external_execution_allowed']), ('HOLD', False))

    def test_supplier_records_stay_out_of_facts_until_the_caller_confirms_identity(self):
        result = lineage.facts_draft(dossier(), catalog())
        self.assertEqual([row['origin']['id'] for row in result['supply_candidates']], ['s1'])
        self.assertEqual(result['supply_candidates'][0]['fields'],
                         {'model': 'YS2607F', 'variant': '12 double-sided cards, blue pen'})
        self.assertEqual(result['supply_candidates'][0]['reason'], 'supplier_item_identity_unconfirmed')
        self.assertTrue(all('identity_confirmed_by_caller' not in c['origin'] for c in result['candidates']))
        confirmed = lineage.facts_draft(dossier(), catalog(), ['s1'])
        self.assertEqual([f['statement'] for f in confirmed['facts']][:2],
                         ['YS2607F', '12 double-sided cards, blue pen'])
        self.assertEqual(confirmed['supplier_source_ids_confirmed'], ['s1'])
        self.assertIs(confirmed['candidates'][0]['origin']['identity_confirmed_by_caller'], True)
        self.assertEqual(confirmed['supply_candidates'], [])

    def test_invalid_supplier_selection_is_rejected(self):
        for bad in (['c1'], ['s2'], ['missing'], ['s1', 's1']):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'lineage_invalid_supplier_source'):
                lineage.facts_draft(dossier(), None, bad)

    def test_draft_facts_feed_audit_as_needs_proof_until_proof_is_added(self):
        facts = lineage.facts_draft(dossier(), catalog(), ['s1'])['facts']
        doc = {'facts': facts[:2], 'claims': [{'id': 'C-001', 'statement': '12 double-sided cards', 'fact_ids': ['F-002']}],
               'fields': [{'id': 'Bullet_1', 'channel': 'Ozon RU', 'text': '12 карточек', 'claim_ids': ['C-001']}]}
        self.assertEqual(lineage.audit(doc)['claims'][0]['audit_status'], 'needs_proof')
        doc['facts'][1]['proof'] = ['synthetic packaging photo']
        self.assertEqual(lineage.audit(doc)['status'], 'PASS')

    def test_long_values_are_truncated_and_invalid_dossiers_rejected(self):
        value = dossier();value['sources'][4]['variant'] = 'x' * 1500
        candidate = lineage.facts_draft(value)['candidates'][1]
        self.assertTrue(candidate['truncated']);self.assertEqual(len(candidate['fact']['statement']), 1000)
        for bad in (None, {}, {'case_id': 'x', 'sources': 'no'}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'lineage_invalid_dossier'):
                lineage.facts_draft(bad)

    def test_tool_reads_the_existing_dossier_and_catalog_through_the_service(self):
        calls = []
        service = SimpleNamespace(
            product_evidence=SimpleNamespace(get=lambda case_id: calls.append(('evidence', case_id)) or dossier()),
            catalog=SimpleNamespace(invoke=lambda name, args: calls.append((name, args['case_id'])) or catalog()))
        result = lineage.invoke('commerce_listing_lineage_facts_draft', {'case_id': 'case-synthetic'}, service)
        self.assertEqual(calls, [('evidence', 'case-synthetic'), ('commerce_catalog_get', 'case-synthetic')])
        self.assertEqual(len(result['facts']), 3)
        named = lineage.invoke('commerce_listing_lineage_facts_draft',
                               {'case_id': 'case-synthetic', 'supplier_source_ids': ['s1']}, service)
        self.assertEqual(len(named['facts']), 5)
        def missing(name, args):
            raise ValueError('catalog_not_found')
        service.catalog = SimpleNamespace(invoke=missing)
        self.assertEqual(len(lineage.invoke('commerce_listing_lineage_facts_draft', {'case_id': 'x'}, service)['facts']), 2)
        with self.assertRaisesRegex(ValueError, 'lineage_service_required'):
            lineage.invoke('commerce_listing_lineage_facts_draft', {'case_id': 'x'})

    def store_terms(self):
        return {'availability': 'snapshot', 'source': 'own_store_product_queries_not_global_hotterms',
                'offer_id': 'SYNTHETIC-OFFER-1', 'platform_sku': '5700000001',
                'period': {'date_from': '2026-11-08T00:00:00Z', 'date_to': '2026-11-15T00:00:00Z'},
                'snapshot_sha256': 'f' * 64,
                'items': [{'query': 'шапка зимняя', 'query_index': 1, 'unique_search_users': 2570},
                          {'query': 'ШАПКА  зимняя', 'query_index': 2},
                          {'query': '   ', 'query_index': 3}, 'junk',
                          {'query': 'шапка на мальчика', 'query_index': 4, 'unique_search_users': 130}]}

    def test_store_keywords_are_deduped_bounded_and_keep_their_source(self):
        result = lineage.facts_draft(dossier(), catalog(), (), self.store_terms())
        self.assertEqual([k['term'] for k in result['keywords']], ['шапка зимняя', 'шапка на мальчика'])
        self.assertEqual([k['id'] for k in result['keywords']], ['K-001', 'K-002'])
        origin = result['keyword_candidates'][0]['origin']
        self.assertEqual((origin['kind'], origin['platform_sku'], origin['offer_id'], origin['unique_search_users']),
                         ('store_search_terms', '5700000001', 'SYNTHETIC-OFFER-1', 2570))
        self.assertEqual(origin['snapshot_sha256'], 'f' * 64)
        self.assertIs(origin['not_global_hot_terms'], True)
        status = result['keyword_source']
        self.assertEqual(status['status'], 'snapshot')
        self.assertIs(status['empty_is_not_zero_demand'], True)
        self.assertIn('不是全平台热搜', status['scope_note'])
        self.assertIn('本店商品真实搜索词快照', result['keywords'][0]['source'])

    def test_keywords_are_not_requested_unless_asked(self):
        result = lineage.facts_draft(dossier(), catalog())
        self.assertEqual((result['keywords'], result['keyword_source']), ([], {'status': 'not_requested'}))

    def test_store_keyword_terms_feed_the_audit_keyword_check(self):
        result = lineage.facts_draft(dossier(), catalog(), (), self.store_terms())
        facts = [dict(result['facts'][0], proof=['synthetic report'])]
        doc = {'facts': facts, 'keywords': result['keywords'],
               'claims': [{'id': 'C-001', 'statement': 'warm hat', 'fact_ids': ['F-001'], 'keyword_ids': ['K-001']}],
               'fields': [{'id': 'Title', 'channel': 'Ozon RU', 'text': 'Тёплая шапка', 'claim_ids': ['C-001'],
                           'keyword_ids': ['K-001']}]}
        field = lineage.audit(doc)['fields'][0]
        self.assertEqual(field['warnings'], [{'code': 'keyword_not_in_text', 'ids': ['K-001']}])
        doc['fields'][0]['text'] = 'шапка зимняя тёплая'
        self.assertEqual(lineage.audit(doc)['fields'][0]['status'], 'ready')

    def reader(self, calls, products=None):
        products = products if products is not None else [{'sku': 5700000001, 'offer_id': 'SYNTHETIC-OFFER-1'}]

        def invoke(name, args):
            calls.append((name, dict(args)))
            if args['query'] == 'SYNTHETIC-OFFER-1':
                return {'availability': 'snapshot', 'source': 'own_store_product_queries_not_global_hotterms',
                        'period': {'date_from': 'a', 'date_to': 'b'}, 'snapshot_sha256': 'f' * 64,
                        'products': products, 'items': []}
            return {'availability': 'snapshot', 'source': 'own_store_product_queries_not_global_hotterms',
                    'period': {'date_from': 'a', 'date_to': 'b'}, 'snapshot_sha256': 'f' * 64,
                    'products': products, 'items': [{'query': 'шапка зимняя', 'sku': 5700000001},
                                                    {'query': 'чужая модель', 'sku': 999}]}
        return SimpleNamespace(invoke=invoke)

    def test_tool_resolves_platform_sku_and_only_reads_store_terms_when_asked(self):
        calls = []
        service = SimpleNamespace(
            product_evidence=SimpleNamespace(get=lambda case_id: dossier()),
            catalog=SimpleNamespace(invoke=lambda name, args: dict(catalog(), sku='SYNTHETIC-OFFER-1')),
            ozon_search_terms=self.reader(calls))
        quiet = lineage.invoke('commerce_listing_lineage_facts_draft', {'case_id': 'case-synthetic'}, service)
        self.assertEqual((quiet['keywords'], calls), ([], []))
        asked = lineage.invoke('commerce_listing_lineage_facts_draft',
                               {'case_id': 'case-synthetic', 'include_store_keywords': True}, service)
        self.assertEqual(calls, [('commerce_ozon_search_terms_search', {'query': 'SYNTHETIC-OFFER-1', 'limit': 100}),
                                 ('commerce_ozon_search_terms_search', {'query': '5700000001', 'limit': 100})])
        self.assertEqual([k['term'] for k in asked['keywords']], ['шапка зимняя'])
        self.assertEqual((asked['keyword_source']['offer_id'], asked['keyword_source']['platform_sku'],
                          asked['keyword_source']['sku']), ('SYNTHETIC-OFFER-1', '5700000001', '5700000001'))

    def test_missing_or_ambiguous_store_identity_generates_no_keywords(self):
        no_sku = SimpleNamespace(product_evidence=SimpleNamespace(get=lambda case_id: dossier()),
                                 catalog=SimpleNamespace(invoke=lambda name, args: catalog()))
        missing = lineage.invoke('commerce_listing_lineage_facts_draft',
                                 {'case_id': 'case-synthetic', 'include_store_keywords': True}, no_sku)
        self.assertEqual((missing['keywords'], missing['keyword_source']['status']), ([], 'no_store_sku'))
        calls = []
        ambiguous = SimpleNamespace(
            product_evidence=SimpleNamespace(get=lambda case_id: dossier()),
            catalog=SimpleNamespace(invoke=lambda name, args: dict(catalog(), sku='SYNTHETIC-OFFER-1')),
            ozon_search_terms=self.reader(calls, [{'sku': 111, 'offer_id': 'SYNTHETIC-OFFER-1'}, {'sku': 222, 'offer_id': 'SYNTHETIC-OFFER-1'}]))
        result = lineage.invoke('commerce_listing_lineage_facts_draft',
                                {'case_id': 'case-synthetic', 'include_store_keywords': True}, ambiguous)
        self.assertEqual((result['keywords'], result['keyword_source']['status']), ([], 'ambiguous_store_sku'))
        self.assertIn('没有唯一对应', result['keyword_source']['scope_note'])


class SharedContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.state = Path(cls.tmp.name)
        cls.token = 'synthetic-listing-lineage-token'
        (cls.state / 'auth.token').write_text(cls.token)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        cls.env = dict(os.environ, COMMERCE_STATE=str(cls.state), COMMERCE_PORT=str(cls.port))
        cls.process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], env=cls.env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                try:
                    cls.call('commerce_task_list', {})
                    break
                except (OSError, ValueError):
                    time.sleep(.05)
            else:
                raise RuntimeError('isolated_commerce_start_failed')
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.process.stderr.close()
        cls.tmp.cleanup()

    @classmethod
    def call(cls, name, args, token=None):
        request = urllib.request.Request(f'http://127.0.0.1:{cls.port}/v1/invoke',
            data=json.dumps({'tool': name, 'arguments': args, 'client': 'test'}).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (token or cls.token)})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=10) as response:
            return json.load(response)

    def rpc(self, process, method, params):
        process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}) + '\n')
        process.stdin.flush()
        ready, _, _ = select.select([process.stdout], [], [], 15)
        self.assertTrue(ready, 'MCP response deadline')
        return json.loads(process.stdout.readline())

    def test_three_stdio_clients_discover_readonly_tools_and_match_http(self):
        expected = self.call('commerce_listing_lineage_audit', {'document': document()})
        self.assertEqual(expected, lineage.audit(document()))
        for client in ('codex', 'hermes', 'harness'):
            process = subprocess.Popen([sys.executable, str(ROOT / 'mcp_server.py'), client], env=self.env,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                with self.subTest(client=client):
                    self.assertIn('result', self.rpc(process, 'initialize', {'protocolVersion': '2025-11-25', 'capabilities': {}}))
                    tools = {t['name']: t for t in self.rpc(process, 'tools/list', {})['result']['tools']}
                    for name in TOOLS:
                        self.assertTrue(tools[name]['annotations']['readOnlyHint'])
                        self.assertFalse(tools[name]['annotations']['destructiveHint'])
                        self.assertFalse(tools[name]['annotations']['openWorldHint'])
                    audit = self.rpc(process, 'tools/call', {'name': TOOLS[0], 'arguments': {'document': document()}})['result']
                    self.assertFalse(audit['isError'])
                    self.assertEqual(audit['structuredContent'], expected)
                    impact = self.rpc(process, 'tools/call', {'name': TOOLS[1], 'arguments': {
                        'document': document(), 'changed': {'fact_ids': ['F-003']}}})['result']
                    self.assertEqual(len(impact['structuredContent']['affected_fields']), 3)
                    export = self.rpc(process, 'tools/call', {'name': TOOLS[2], 'arguments': {'document': document()}})['result']
                    self.assertIn('Claim_ID', export['structuredContent']['tables']['Claims_Pool'])
                    rejected = self.rpc(process, 'tools/call', {'name': TOOLS[0], 'arguments': {'document': {}}})['result']
                    self.assertTrue(rejected['isError'])
                    self.assertEqual(rejected['content'][0]['text'], 'lineage_invalid_document')
            finally:
                process.stdin.close()
                process.wait(timeout=10)
                process.stdout.close()
                process.stderr.close()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call(TOOLS[3], {'case_id': 'missing-synthetic-case'})
        self.assertIn(error.exception.code, (400, 404, 422))
        error.exception.close()
        self.assertEqual(self.call('commerce_task_list', {})['tasks'], [])

    def test_existing_authentication_boundary_applies(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call(TOOLS[0], {'document': document()}, token='invalid-synthetic-token')
        self.assertEqual(error.exception.code, 401)
        error.exception.close()


class WorkflowTemplate(unittest.TestCase):
    def test_generator_audit_critic_template_runs_on_existing_runtime_with_stub_model(self):
        from commerce_core import Core
        from extension_runtime import ExtensionRuntime
        from extension_runtime.contracts import SAFE_BUILTINS
        for name in TOOLS:
            self.assertIn(name, SAFE_BUILTINS)
        template = json.loads((ROOT / 'examples/listing-lineage-workflow.json').read_text())
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        core = Core(Path(tmp.name) / 'db.sqlite')
        route = {'provider': 'compatible', 'profile_id': 'synthetic-local', 'profile_revision': '1',
                 'engine': 'llama_cpp', 'model': 'synthetic-local', 'base_url': 'http://127.0.0.1:1/v1', 'json_mode': True}
        service = SimpleNamespace(core=core, state=Path(tmp.name),
            models=SimpleNamespace(snapshot=lambda *a, **k: route, runtime_route=lambda value: value),
            invoke=lambda name, args, client='local': lineage.invoke(name, args))
        runtime = ExtensionRuntime(service);self.addCleanup(runtime.stop)

        def drain(value):
            for _ in range(16):
                runtime._process(value['id']);value = runtime.run_get(value['id'])
                if value['status'] not in ('queued', 'running'):
                    return value
            self.fail('bounded workflow did not settle')

        def ready(definition):
            ext = runtime.save(definition)
            run = runtime.launch(ext['id'], idempotency_key='test-' + ext['id'], test=True)
            self.assertEqual(drain(run)['status'], 'succeeded')
            return runtime.enable(ext['id'], ext['version'], True)

        agents = {}
        for role in ('generator', 'critic'):
            definition = copy.deepcopy(template[role]);definition['spec']['model_id'] = 'synthetic-local'
            agents[role] = ready(definition)
        workflow = copy.deepcopy(template['workflow'])
        workflow['spec']['steps'][0]['uses']['extension_id'] = agents['generator']['id']
        workflow['spec']['steps'][2]['uses']['extension_id'] = agents['critic']['id']
        workflow = ready(workflow)
        source = document()
        seen = []

        def model(payload, cancelled, model_route, instructions, output_schema=None):
            data = payload['input']
            if 'audit' in data:
                seen.append(('critic', data['audit']['status']))
                return {'action': 'finish', 'output': {'verdict': 'hold', 'findings': [
                    {'target_id': 'C-013', 'kind': 'unsupported', 'reason': 'synthetic'}]}}
            seen.append(('generator', sorted(data)))
            claims = [source['claims'][0], dict(source['claims'][1], fact_ids=[])]
            return {'action': 'finish', 'output': {'claims': claims, 'fields': [
                {'id': 'Bullet_1', 'channel': data['channel'], 'text': 'Wrinkle free and soft', 'claim_ids': ['C-012', 'C-013']}]}}

        run_input = {'facts': source['facts'], 'keywords': source['keywords'], 'insights': ['synthetic review theme'],
                     'channel': 'Amazon US', 'language': 'en', 'field_specs': [{'id': 'Bullet_1', 'max_chars': 500}],
                     'restricted_terms': source['restricted_terms']}
        with patch.object(runtime, '_model', side_effect=model):
            run = runtime.launch(workflow['id'], input=run_input, idempotency_key='lineage-run',
                                 budget={'max_steps': 8, 'max_model_calls': 2, 'max_seconds': 300,
                                         'max_output_bytes': 64000, 'allow_model_calls': True})
            result = drain(run)
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertEqual([role for role, _ in seen], ['generator', 'critic'])
        self.assertEqual(seen[1][1], 'HOLD')
        audit = result['output']['audit']
        self.assertEqual({c['id']: c['audit_status'] for c in audit['claims']},
                         {'C-012': 'passed', 'C-013': 'rejected_no_evidence'})
        self.assertEqual(audit['fields'][0]['status'], 'blocked')
        self.assertEqual(result['output']['critique']['verdict'], 'hold')


if __name__ == '__main__':
    unittest.main()
