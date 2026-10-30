"""The summary must retain conclusive local failures beside successful RU TCP probes."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai.availability_model import (
    CHANNEL_API_HTTP, CHANNEL_API_TCP, CHANNEL_API_TLS, CHANNEL_DNS, CHANNEL_PING,
    ERR_OTHER, ERR_TIMEOUT, NodeResult, ProbeResult, TargetSnapshot, VantageAggregate,
)
from ai.availability_report import reclassify_report
from ai.availability_classifier import BLOCKING_KINDS


def healthy_report():
    target = TargetSnapshot(name="Hive", host="198.51.100.1", role="queen",
                            domain="api.example.test", api_port=443)
    for channel in (CHANNEL_API_TCP, CHANNEL_API_TLS, CHANNEL_API_HTTP, CHANNEL_DNS):
        target.local[channel] = ProbeResult(channel=channel, ok=True)
    for channel in (CHANNEL_API_TCP, CHANNEL_PING):
        target.ru[channel] = VantageAggregate(channel=channel, nodes=[
            NodeResult(node="ru-a", ok=True), NodeResult(node="ru-b", ok=True)])
    return {"ts": "2026-10-30T19:24:08+00:00", "status": "ok", "targets": [target.to_dict()]}


class LocalHealthTests(unittest.TestCase):
    def test_failed_local_http_cannot_produce_an_all_available_summary(self):
        report = healthy_report()
        report["targets"][0]["local"][CHANNEL_API_HTTP].update(ok=False, error_kind=ERR_OTHER)
        result = reclassify_report(report)
        self.assertEqual(result["status"], "degraded")
        self.assertTrue(any(v["channel"] == CHANNEL_API_HTTP for v in result["verdicts"]))
        self.assertEqual(result["ts"], report["ts"])
        self.assertEqual(result["targets"], report["targets"])
        self.assertFalse(any(v["kind"] in BLOCKING_KINDS or v["commands"] for v in result["verdicts"]))

    def test_failed_local_dns_cannot_produce_an_all_available_summary(self):
        report = healthy_report()
        report["targets"][0]["local"][CHANNEL_DNS].update(ok=False, error_kind=ERR_TIMEOUT)
        result = reclassify_report(report)
        self.assertEqual(result["status"], "degraded")
        self.assertTrue(any(v["channel"] == CHANNEL_DNS for v in result["verdicts"]))

    def test_successful_local_health_and_ru_checks_remain_available(self):
        self.assertEqual(reclassify_report(healthy_report())["status"], "ok")

    def test_inconclusive_local_probe_does_not_claim_a_service_failure(self):
        report = healthy_report()
        report["targets"][0]["local"][CHANNEL_DNS].update(ok=False, error_kind=ERR_TIMEOUT, inconclusive=True)
        self.assertEqual(reclassify_report(report)["status"], "ok")


if __name__ == "__main__":
    unittest.main()
