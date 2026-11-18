"""The trigger firing frame is prompt-only and never changes the stored question."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trigger_firing
from assistant_team import AssistantTeams


class FiringFrame(unittest.TestCase):
    def test_unattended_kinds_get_a_frame_and_manual_does_not(self):
        for kind in ('once', 'interval', 'weekly', 'webhook', 'after_discussion'):
            with self.subTest(kind=kind):
                text = trigger_firing.frame(kind)
                self.assertIn('就是该触发器这一次的执行', text)
                self.assertIn('不要去查看、创建或修改触发器设置', text)
                self.assertIn('不要把“已配置”当作完成', text)
        self.assertIsNone(trigger_firing.frame('manual'))
        self.assertIsNone(trigger_firing.binding('trigger_0123456789abcdef', 'manual', 'manual:1'))

    def test_binding_is_bounded_and_rejects_bad_references(self):
        value = trigger_firing.binding('trigger_0123456789abcdef', 'weekly', 'schedule:1')
        self.assertEqual(set(value), {'trigger_id', 'kind', 'event_id', 'instruction'})
        for args in (('', 'weekly', 'e'), ('t', 'weekly', ''), (None, 'weekly', 'e'), ('t', 'hourly', 'e')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                trigger_firing.binding(*args)

    def test_prompt_context_carries_the_frame_only_when_present(self):
        profile = {'id': 'p1', 'name': '成员', 'role_id': 'r1', 'instructions': 'i', 'sha256': 'c'}
        plain = AssistantTeams.prompt_context({'profile': profile, 'channel': None})
        self.assertNotIn('trigger_firing', plain)
        firing = trigger_firing.binding('trigger_0123456789abcdef', 'interval', 'schedule:1')
        framed = AssistantTeams.prompt_context({'profile': profile, 'channel': None, 'trigger_firing': firing})
        self.assertEqual(framed['trigger_firing'], firing)


if __name__ == '__main__':
    unittest.main()
