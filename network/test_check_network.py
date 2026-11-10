"""Tests of failure interpretation and private-output handling, without devices."""

import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_network as check


def metrics(http="200", tls="0.7", cert="0"):
    return check.MARKER + ";".join((http, "0.01", "0.02", tls, "1.2", cert))


class InterpretationTests(unittest.TestCase):
    def test_api_root_404_is_transport_only(self):
        result = check.parse_result(0, metrics("404"), None, None)
        self.assertTrue(result["transport_ok"])
        self.assertIsNone(result["http_expected"])
        self.assertIsNone(result["error"])

    def test_web_403_is_not_reported_as_dns_or_transport_failure(self):
        result = check.parse_result(0, metrics("403"), None, 200)
        self.assertTrue(result["transport_ok"])
        self.assertFalse(result["http_expected"])
        summary = check.summarize([{"route": "test", **result}])
        self.assertEqual(summary["status"], "http_response_unexpected")
        self.assertEqual(summary["application_acceptance"], "not_tested")

    def test_failed_cert_and_timeout_never_pass(self):
        for code, output in [(60, metrics(cert="20")), (28, metrics("000", tls="0"))]:
            self.assertFalse(check.parse_result(code, output, None, 200)["transport_ok"])

    def test_no_tls_cannot_claim_verified_certificate(self):
        result = check.parse_result(6, metrics("000", tls="0"), None, 200)
        self.assertFalse(result["transport_ok"])
        self.assertIsNone(result["tls_certificate_verified"])

    def test_missing_or_untrusted_metrics_do_not_leak_raw_text(self):
        private = "private-log https://private.invalid/?credential=PRIVATE"
        for output in (private, private + check.MARKER + "malformed", metrics(tls="nan")):
            result = check.parse_result(1, output, None, 200)
            self.assertFalse(result["transport_ok"])
            self.assertNotIn("PRIVATE", json.dumps(result))

    def test_unavailable_device_state_is_unknown(self):
        self.assertTrue(all(v is None for v in check.parse_device_state(None, None, None).values()))

    def test_state_output_contains_only_selected_fields(self):
        text = 'NetworkAgentInfo{ ni{[type: WIFI[], state: CONNECTED/CONNECTED]} nc{INTERNET&VALIDATED} SSID="private-network"}\nNetworkAgentInfo{ ni{[type: VPN[], state: CONNECTED/CONNECTED]}}'
        state = check.parse_device_state(text, "RSSI: -52 SSID: private-network", "system,com.github.metacubex.clash.meta,10242")
        self.assertTrue(state["wifi_connected"])
        self.assertTrue(state["vpn_connected"])
        self.assertTrue(state["clash_power_exempt"])
        self.assertEqual(state["wifi_rssi_dbm"], -52)
        self.assertNotIn("private-network", json.dumps(state))

    def test_phone_command_never_launches_ui_and_serial_stays_out_of_shell_text(self):
        args = argparse.Namespace(adb="adb", curl="curl", android_serial="target-id", timeout=8)
        with patch.object(check, "run", return_value=(0, metrics(), None)) as runner:
            check.probe(("android", True, "http://127.0.0.1:7890"), check.TARGETS[1], args)
        argv = runner.call_args.args[0]
        self.assertEqual(argv[:5], ["adb", "-s", "target-id", "shell", argv[4]])
        self.assertNotIn("target-id", argv[4])
        self.assertTrue(argv[4].startswith("curl -q "))
        self.assertNotIn("am start", argv[4])
        self.assertNotIn("--insecure", argv[4])

    def test_empty_sample_set_is_not_success(self):
        self.assertEqual(check.summarize([])["status"], "not_measured")

    def test_report_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text("existing")
            with self.assertRaises(FileExistsError):
                check.save_report(path, {})
            self.assertEqual(path.read_text(), "existing")


if __name__ == "__main__":
    unittest.main()
