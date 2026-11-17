"""Generated private pages inherit the root theme without changing preferences."""
from pathlib import Path
from html.parser import HTMLParser
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model_providers.setup import page as model_page
from platform_connections.setup import page as platform_page


class Nodes(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.nodes = []; self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))


class PrivateSetupTheme(unittest.TestCase):
    def test_generated_pages_use_the_same_theme_root_as_the_workbench(self):
        for html in [model_page(), platform_page(), (ROOT / 'web/setup.html').read_text()]:
            with self.subTest(title=html[:120]):
                nodes = Nodes(html).nodes
                self.assertEqual(next(attrs for tag, attrs in nodes if tag == 'html').get('data-ui-appearance'), 'shopify')
                self.assertNotIn('data-ui-appearance', next(attrs for tag, attrs in nodes if tag == 'body'))

    def test_return_links_open_the_owning_module(self):
        for html, target in [(model_page(), '/?tab=models'), (platform_page(), '/?tab=connections'), ((ROOT / 'web/setup.html').read_text(), '/?tab=connections')]:
            with self.subTest(target=target):
                self.assertIn(target, [attrs.get('href') for tag, attrs in Nodes(html).nodes if tag == 'a'])


if __name__ == '__main__':
    unittest.main()
