"""One local owner's preference survives tool/client and service reconstruction."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


class ThemePreferences(unittest.TestCase):
    def test_default_and_cross_client_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Commerce(folder)
            self.assertEqual(first.invoke('commerce_ui_get_preferences', {}, 'codex')['theme'], 'system')
            first.invoke('commerce_ui_set_preferences', {'theme': 'dark'}, 'hermes')
            self.assertEqual(Commerce(folder).invoke('commerce_ui_get_preferences', {}, 'harness')['theme'], 'dark')
            first.invoke('commerce_ui_set_preferences', {'theme': 'light'}, 'harness')
            self.assertEqual(first.invoke('commerce_ui_get_preferences', {}, 'browser')['theme'], 'light')

    def test_invalid_preferences_do_not_change_saved_value(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Commerce(folder)
            for value in [None, True, 'auto', '<script>', 'DARK']:
                with self.assertRaises(ValueError):
                    app.invoke('commerce_ui_set_preferences', {'theme': value})
            self.assertEqual(app.invoke('commerce_ui_get_preferences', {})['theme'], 'system')

    def test_theme_changes_do_not_modify_shared_business_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Commerce(folder)
            task = app.invoke('commerce_task_create', {'idempotency_key':'synthetic-ui-case','kind':'analysis'})
            for theme in ['dark','light','system']:
                app.invoke('commerce_ui_set_preferences', {'theme': theme})
                app.invoke('commerce_ui_set_preferences', {'theme': theme})
            self.assertEqual(app.invoke('commerce_task_get', {'task_id':task['id']}), task)


if __name__ == '__main__':
    unittest.main()
