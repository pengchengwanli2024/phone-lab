"""Dashboard contracts use synthetic source records, never live business data."""
import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from service import Commerce
from test_intel_workspace import feed


class IntelDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, name, args=None):
        return self.app.invoke('commerce_intel_' + name, args or {}, 'test')

    def collect(self, source, data):
        with patch('intelligence.fetch', return_value=data):
            self.app.intelligence.refresh(source)

    def test_preferences_are_shared_persistent_validated_and_compare_and_swap(self):
        original = self.call('dashboard_get')
        self.assertEqual(original['preferences']['language'], 'zh')
        desired = copy.deepcopy(original['preferences'])
        desired['panels'].reverse()
        desired['panels'][0]['collapsed'] = True
        result = self.call('dashboard_update', {'expected_revision': original['revision'], 'preferences': desired})
        self.assertEqual(Commerce(self.tmp.name).invoke('commerce_intel_dashboard_get', {})['preferences'], desired)
        self.assertEqual(result['revision'], original['revision'] + 1)
        with self.assertRaisesRegex(ValueError, 'intel_dashboard_conflict'):
            self.call('dashboard_update', {'expected_revision': original['revision'], 'preferences': original['preferences']})
        for field, value in [('layers', ['invented-feed']), ('layers', None), ('language', 'xx'), ('time', '9000')]:
            invalid = copy.deepcopy(desired); invalid[field] = value
            with self.assertRaisesRegex(ValueError, 'invalid_intel_dashboard'):
                self.call('dashboard_update', {'expected_revision': result['revision'], 'preferences': invalid})
        invalid = copy.deepcopy(desired); invalid['panels'][1]['id'] = invalid['panels'][0]['id']
        with self.assertRaisesRegex(ValueError, 'invalid_intel_dashboard'):
            self.call('dashboard_update', {'expected_revision': result['revision'], 'preferences': invalid})

    def test_layer_filter_applies_before_marker_limit_and_does_not_change_news(self):
        self.collect('usgs', feed(300))
        gdacs = b'<rss xmlns:g="http://www.gdacs.org" xmlns:geo="http://www.georss.org/georss"><channel><item><title>Green flood alert in Mexico</title><link>https://example.org/flood</link><guid>flood-1</guid><g:country>Mexico</g:country><g:alertlevel>Green</g:alertlevel><geo:point>19 -99</geo:point></item></channel></rss>'
        self.collect('gdacs', gdacs)
        result = self.call('search', {'include_map': True, 'map_layers': ['flood'], 'include_panels': True})
        self.assertEqual(result['total'], 301)
        self.assertEqual(len(result['markers']), 1)
        self.assertEqual(result['map_stats']['by_layer']['earthquake'], 300)
        self.assertEqual(result['map_stats']['matched'], 1)
        self.assertIn('墨西哥', result['markers'][0]['display']['zh_title'])
        self.assertIn('洪水', result['markers'][0]['display']['zh_title'])
        self.assertEqual(result['markers'][0]['title'], 'Green flood alert in Mexico')

    def test_map_link_filters_list_and_panels_but_default_map_only_does_not(self):
        self.collect('usgs', feed(2))
        outside = {'west': 100, 'east': 150, 'south': 0, 'north': 60}
        self.assertEqual(self.call('search', {'bounds': outside, 'map_layers': ['earthquake']})['total'], 2)
        result = self.call('search', {'bounds': outside, 'map_layers': ['earthquake'], 'link_map': True, 'include_panels': True})
        self.assertEqual(result['total'], 0)
        self.assertTrue(all(p['total'] == 0 for p in result['panels'].values()))
        for bounds in [{'west': 181, 'east': 0, 'south': 0, 'north': 20}, {'west': 0, 'east': 20, 'south': 30, 'north': -20}]:
            with self.assertRaisesRegex(ValueError, 'invalid_intel_map'):
                self.call('search', {'bounds': bounds})

    def test_time_and_map_state_bind_pagination_when_linked(self):
        self.collect('usgs', feed(45))
        params = {'include_map': True, 'map_layers': ['earthquake'], 'link_map': True, 'limit': '20'}
        first = self.call('search', params)
        with self.assertRaisesRegex(ValueError, 'intel_cursor_expired'):
            self.call('search', {**params, 'map_layers': ['flood'], 'cursor': first['next_cursor']})
        for hours in ['1', '6', '48']:
            self.assertEqual(self.call('search', {'hours': hours})['total'], 0)

    def test_reading_and_presentation_do_not_start_models_or_replace_source_hash(self):
        data = json.loads(feed(1))
        data['features'][0]['properties']['title'] = 'M 4.5 - 10 km NW of Town, Russia'
        self.collect('usgs', json.dumps(data).encode())
        original = self.app.intelligence.store.rows('latest')[0]
        with patch.object(self.app.translations, 'start', side_effect=AssertionError('read must not start a model')):
            result = self.call('search', {'include_map': True, 'include_panels': True})
            item = self.call('item_get', {'item_id': original['id']})
        self.assertEqual(item['record_sha256'], original['record_sha256'])
        self.assertIn('地震', item['display']['zh_title'])
        self.assertIn('俄罗斯', item['display']['zh_title'])
        self.assertEqual(result['markers'][0]['record_sha256'], original['record_sha256'])


if __name__ == '__main__':
    unittest.main()
