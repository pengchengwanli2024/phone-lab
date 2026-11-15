"""Image jobs receive their own frame contract, not a whole visual family."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from creative_direction import DIRECTION_FIELDS, input_sha, specification
from creative_plan import plan


class SingleFrame(unittest.TestCase):
    def project(self):
        brief = {'synthetic': True, 'product': {'name': 'Synthetic tool', 'verified_facts': [
            {'id': 'color', 'text': 'Synthetic green handle', 'evidence_ref': 'synthetic-source'}]},
                 'target': {'language': 'ru', 'country': 'RU'}}
        direction = {key: 'synthetic-' + key for key in DIRECTION_FIELDS}
        brief['design_direction'] = {'input_sha256': input_sha(brief), 'analysis': direction, 'references': []}
        return {'brief': brief, 'plan': plan(brief)}

    def test_three_individual_image_formats_have_one_explicit_frame(self):
        for kind in ('product_main', 'product_detail', 'usage_scene'):
            with self.subTest(kind=kind):
                spec = specification(self.project(), kind)
                self.assertIn('禁止拼贴、分屏或多面板', spec['prompt'])
                self.assertIn('本次只生成', spec['prompt'])
                self.assertNotIn('节奏与叙事：synthetic-rhythm', spec['prompt'])
                self.assertNotIn('镜头与特写：synthetic-shots', spec['prompt'])
                self.assertEqual(spec['direction']['rhythm'], 'synthetic-rhythm')
                self.assertEqual(spec['fact_ids'], ['color'])

    def test_main_detail_and_scene_describe_distinct_subjects(self):
        self.assertIn('完整产品', specification(self.project(), 'product_main')['prompt'])
        self.assertIn('单个细节', specification(self.project(), 'product_detail')['prompt'])
        self.assertIn('单一使用场景', specification(self.project(), 'usage_scene')['prompt'])

    def test_video_retains_camera_rhythm_and_five_shots(self):
        for kind in ('showcase_video', 'ugc_video'):
            spec = specification(self.project(), kind)
            self.assertIn('节奏与叙事：synthetic-rhythm', spec['prompt'])
            self.assertIn('镜头与特写：synthetic-shots', spec['prompt'])
            self.assertNotIn('禁止拼贴、分屏或多面板', spec['prompt'])
            self.assertEqual(len(spec['shots']), 5)
            self.assertEqual(spec['duration_ms'], 30000)


if __name__ == '__main__':
    unittest.main()
