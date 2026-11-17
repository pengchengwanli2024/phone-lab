"""Local browser handoff uses the existing one-use ticket, never device control."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phone_management import open_in_browser


class PhoneManagementHandoff(unittest.TestCase):
    def test_opens_only_local_phone_page_without_returning_ticket(self):
        service = SimpleNamespace(live=SimpleNamespace(new_setup_ticket=Mock(return_value='synthetic-private-ticket')))
        with patch('runtime.PORT', 38799), patch('phone_management.webbrowser.open', return_value=True) as launch:
            result = open_in_browser(service)
        address = urlsplit(launch.call_args.args[0])
        self.assertEqual((address.scheme, address.hostname, address.port, address.path), ('http', '127.0.0.1', 38799, '/phones'))
        self.assertEqual(parse_qs(address.query), {'ticket': ['synthetic-private-ticket']})
        self.assertTrue(result['opened'])
        self.assertNotIn('synthetic-private-ticket', json.dumps(result))
        service.live.new_setup_ticket.assert_called_once_with()

    def test_unconfirmed_or_failed_browser_launch_does_not_report_opened(self):
        for outcome in (False, OSError('private launch detail')):
            with self.subTest(outcome=type(outcome).__name__):
                service = SimpleNamespace(live=SimpleNamespace(new_setup_ticket=lambda: 'synthetic-private-ticket'))
                with patch('phone_management.webbrowser.open', side_effect=outcome if isinstance(outcome, Exception) else None, return_value=False):
                    result = open_in_browser(service)
                self.assertFalse(result['opened'])
                self.assertEqual(result['status'], 'browser_open_unconfirmed')
                self.assertNotIn('private', json.dumps(result))
