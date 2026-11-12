"""Synthetic collection, translation integrity and evidence export acceptance."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research import template, validate, export, digest, drift
from translation import normalize, validate_response
from service import Commerce


def sample():
    record = template('research')['record']
    record.update(market='US', language='en', source_url='https://example.com/research',
                  captured_at='2026-11-01T00:00:00Z', raw_excerpt='Synthetic research. Price 12.99 USD. Not waterproof.')
    text = [('Synthetic research.', '合成调研。'), ('Price 12.99 USD.', '价格 12.99 USD。'), ('Not waterproof.', '不防水。')]
    for field, (original, zh) in zip(record['fields'].values(), text):
        field.update(original=original, zh=zh, reviewed=True, locator='Synthetic source paragraph')
    return record


class ResearchAcceptance(unittest.TestCase):
    def test_five_distinct_platform_templates_and_bilingual_fields(self):
        keys = {'ozon': 'product_id', 'tiktok': 'video_context', 'amazon': 'asin', 'mercado': 'item_id', 'temu': 'goods_id'}
        for platform, key in keys.items():
            spec = template(platform)
            self.assertIn(key, spec['record']['fields'])
            self.assertIn('category_rules_checked', spec['record'])
            self.assertTrue(spec['references'])
            self.assertEqual(validate(spec['record'])['status'], 'HOLD')
            self.assertIn('zh', spec['record']['fields']['title'])

    def test_missing_translation_and_review_block_formal_export(self):
        record = sample(); field = record['fields']['findings']
        field['zh'] = ''
        self.assertIn('待翻译', ' '.join(x['message'] for x in validate(record)['issues']))
        with self.assertRaises(ValueError): export(record, True)
        field['zh'] = '价格 12.99 USD。'; field['reviewed'] = False
        with self.assertRaises(ValueError): export(record, True)

    def test_numbers_units_currency_and_conflicts_require_correction(self):
        self.assertTrue(drift('12.99 USD, 2 kg', '12.99 CNY，2 kg'))
        record = sample(); record['fields']['findings']['zh'] = '价格 1299 USD。'
        self.assertTrue(validate(record)['issues'])
        record = sample(); record['fields']['findings']['kind'] = 'conflict'
        self.assertTrue(validate(record)['issues'])

    def test_complete_research_export_retains_exact_original_and_hashes(self):
        record = sample(); result = export(record, True); payload = json.loads(result['json'])
        self.assertEqual(result['status'], 'REVIEWED_RESEARCH')
        self.assertEqual(digest(result['json']), result['sha256'])
        self.assertEqual(payload['record'], record)
        self.assertEqual(payload['raw_excerpt_sha256'], digest(record['raw_excerpt']))
        self.assertIn('中文翻译', result['csv'])
        self.assertIn('12.99 USD', result['csv'])
        self.assertFalse(payload['verification']['publication_ready'])
        self.assertEqual(payload['verification']['evidence_status'], 'caller_supplied_not_independently_verified')

    def test_evidence_dates_links_and_raw_original_required(self):
        for key, value in [('captured_at', '2099-01-01T00:00:00Z'), ('captured_at', '2026-01-01'), ('source_url', 'https://user:password@example.com'), ('raw_excerpt', '')]:
            record = sample(); record[key] = value
            self.assertTrue(validate(record)['issues'], key)

    def test_csv_formula_safe_but_json_keeps_original(self):
        record = sample(); record['fields']['findings'].update(original='=HYPERLINK("https://example.com")', zh='示例公式')
        result = export(record)
        self.assertIn("'=HYPERLINK", result['csv'])
        self.assertEqual(json.loads(result['json'])['record']['fields']['findings']['original'], record['fields']['findings']['original'])

    def test_unknown_fields_and_oversized_input_rejected(self):
        record = sample(); record['unexpected'] = True
        with self.assertRaises(ValueError): validate(record)
        with self.assertRaises(ValueError): normalize({'language': 'en', 'items': [{'id': 'a', 'text': 'x' * 6001}]})


class TranslationAcceptance(unittest.TestCase):
    def test_output_ids_hashes_and_pending_review(self):
        data = {'language': 'en', 'items': [{'id': 'a', 'text': 'Not waterproof. 2 kg.'}]}
        normalize(data)
        result = validate_response(data, {'translations': [{'id': 'a', 'zh': '不防水。2 kg。'}], 'model': 'synthetic-model'})
        self.assertEqual(result['translations'][0]['original_sha256'], digest(data['items'][0]['text']))
        self.assertEqual(result['translations'][0]['status'], 'pending_review')
        self.assertFalse(result['tools_enabled'])
        for values in [[], [{'id': 'b', 'zh': '不防水。'}]]:
            with self.assertRaises(ValueError): validate_response(data, {'translations': values})

    def test_shared_jobs_idempotent_and_calculation_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Commerce(directory)
            data = {'language': 'en', 'items': [{'id': 'a', 'text': 'Price 12 USD.'}]}
            response = validate_response(data, {'translations': [{'id': 'a', 'zh': '价格 12 USD。'}], 'model': 'synthetic-model'})
            with patch('translation.run_model', return_value=response) as model:
                first = app.invoke('commerce_translation_start', {'input': data, 'idempotency_key': 'synthetic-only'})
                second = app.invoke('commerce_translation_start', {'input': data, 'idempotency_key': 'synthetic-only'})
                self.assertEqual(first['id'], second['id'])
                for _ in range(100):
                    result = app.invoke('commerce_translation_get', {'job_id': first['id']})
                    if result['status'] == 'completed': break
                    time.sleep(.01)
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(model.call_count, 1)
            checked = app.invoke('commerce_collection_check', {'record': sample()})
            self.assertEqual(checked['status'], 'REVIEWED_DRAFT')
            calculation = app.invoke('commerce_unit_economics', {'input': {}})
            self.assertEqual(calculation['evidence']['input'], {})
            self.assertEqual(calculation['evidence']['input_sha256'], digest('{}'))

    def test_concurrent_same_translation_is_one_model_call(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Commerce(directory)
            data = {'language': 'en', 'items': [{'id': 'a', 'text': '2 kg'}]}
            response = validate_response(data, {'translations': [{'id': 'a', 'zh': '2 kg'}]})
            with patch('translation.run_model', return_value=response) as model:
                with ThreadPoolExecutor(max_workers=5) as pool:
                    jobs = list(pool.map(lambda _: app.invoke('commerce_translation_start', {'input': data, 'idempotency_key': 'same-translation'}), range(5)))
                self.assertEqual(len({job['id'] for job in jobs}), 1)
                for _ in range(100):
                    if app.translations.get(jobs[0]['id'])['status'] == 'completed': break
                    time.sleep(.01)
                self.assertEqual(model.call_count, 1)


if __name__ == '__main__': unittest.main()
