"""Local routing is deterministic and never infers a permission grant."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assistant_team_routing import normalize_routing, choose_members, collaboration_plan


class TeamRoutingTests(unittest.TestCase):
    def setUp(self):
        self.profiles = [
            {'id': 'profile_a', 'name': '物流顾问', 'enabled': True, 'expertise': ['运输', '物流', 'shipping']},
            {'id': 'profile_b', 'name': '成本顾问', 'enabled': True, 'expertise': ['毛利', '成本', 'cost']},
        ]
        self.channel = {'member_ids': ['profile_a', 'profile_b'], 'routing': {
            'mode': 'auto', 'lead_id': 'profile_b', 'max_rounds': 1,
            'rules': [{'keywords': ['运输'], 'member_ids': ['profile_a']}],
        }}

    def test_legacy_default_still_addresses_everyone(self):
        d = choose_members({'member_ids': self.channel['member_ids']}, self.profiles, '你好')
        self.assertEqual(d['selected_member_ids'], ['profile_a', 'profile_b'])
        self.assertEqual(d['reason'], 'all_members')

    def test_explicit_mentions_precede_keyword_rules(self):
        d = choose_members(self.channel, self.profiles, '@成本顾问 核对运输费用')
        self.assertEqual(d['selected_member_ids'], ['profile_b'])
        self.assertEqual(d['reason'], 'explicit_mentions')

    def test_unrecognized_and_ambiguous_mentions_are_not_silently_routed(self):
        with self.assertRaisesRegex(ValueError, 'team_unknown_mention'):
            choose_members(self.channel, self.profiles, '@不存在的顾问 请回答')
        profiles = [dict(p, name='顾问') for p in self.profiles]
        with self.assertRaisesRegex(ValueError, 'team_ambiguous_mention'):
            choose_members(self.channel, profiles, '@顾问 请回答')

    def test_keyword_rules_then_expertise_then_lead(self):
        d = choose_members(self.channel, self.profiles, '核对运输资料')
        self.assertEqual(d['selected_member_ids'], ['profile_a'])
        self.assertEqual(d['reason'], 'keyword_rules')
        d = choose_members(self.channel, self.profiles, '说明 SHIPPING 的含义')
        self.assertEqual(d['selected_member_ids'], ['profile_a'])
        self.assertEqual(d['reason'], 'member_expertise')
        d = choose_members(self.channel, self.profiles, '解释这次分工')
        self.assertEqual(d['selected_member_ids'], ['profile_b'])
        self.assertEqual(d['reason'], 'lead_fallback')

    def test_mentions_only_is_explicit_and_never_silently_falls_back(self):
        self.channel['routing']['mentions_only'] = True
        with self.assertRaisesRegex(ValueError, 'team_no_recipient'):
            choose_members(self.channel, self.profiles, '运输')
        self.assertEqual(choose_members(self.channel, self.profiles, '@物流顾问 请说明运输')['selected_member_ids'], ['profile_a'])

    def test_multiple_rules_union_targets_in_channel_order(self):
        self.channel['routing']['rules'].append({'keywords': ['毛利'], 'member_ids': ['profile_b']})
        d = choose_members(self.channel, self.profiles, '运输与毛利')
        self.assertEqual(d['selected_member_ids'], ['profile_a', 'profile_b'])

    def test_selected_disabled_member_is_rejected(self):
        self.profiles[0]['enabled'] = False
        with self.assertRaisesRegex(ValueError, 'team_profile_disabled'):
            choose_members(self.channel, self.profiles, '运输')

    def test_no_unknown_targets_or_unbounded_rules(self):
        for changes in [{'lead_id': 'outside'}, {'mode': 'magic'}, {'max_rounds': True},
                        {'max_rounds': 4}, {'rules': [{'keywords': ['运输'], 'member_ids': ['outside']}]},
                        {'grant': True}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize_routing({**self.channel['routing'], **changes}, self.channel['member_ids'])

    def test_collaboration_has_finite_rounds_and_one_final_lead(self):
        plan = collaboration_plan(self.profiles, 'profile_b', 3)
        self.assertEqual(len(plan), 7)
        self.assertEqual([p['profile_id'] for p in plan[:2]], ['profile_a', 'profile_b'])
        self.assertEqual([p['round'] for p in plan[:-1]], [1, 1, 2, 2, 3, 3])
        self.assertEqual(plan[-1]['kind'], 'synthesis')
        self.assertEqual(plan[-1]['profile_id'], 'profile_b')
        self.assertEqual(plan[-1]['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
