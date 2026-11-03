"""Client disconnects are observations, not verified DPI or transport capabilities."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.availability_classifier import BLOCKING_KINDS, classify_target, report_status
from ai.availability_knowledge import knowledge_to_dict
from ai.availability_model import (
    CHANNEL_API_TCP, CHANNEL_PING, CHANNEL_WDTT_UDP,
    ClientSignals, NodeResult, ProbeResult, TargetSnapshot, VantageAggregate,
)
from ai.availability_report import reclassify_report


def nodes(channel, ok):
    return VantageAggregate(channel, nodes=[
        NodeResult(node=f'ru{i}.fixture', ok=ok, error_kind='' if ok else 'timeout')
        for i in range(2)
    ])


def working_queen():
    s = TargetSnapshot(name='Улей', host='192.0.2.1', role='queen', api_port=443,
                       wdtt_port=56000, online_count=12)
    s.local[CHANNEL_API_TCP] = ProbeResult(channel=CHANNEL_API_TCP, ok=True)
    s.ru[CHANNEL_API_TCP] = nodes(CHANNEL_API_TCP, True)
    s.ru[CHANNEL_PING] = nodes(CHANNEL_PING, True)
    return s


class ClientEvidenceTests(unittest.TestCase):
    def test_replay_nine_disconnects_with_three_short_tunnels_is_not_confirmed_dpi(self):
        # 2026-11-03 10:59Z: six tunnels had already lived minutes/hours.
        s = working_queen()
        s.clients = ClientSignals(window_minutes=30, reports=9, failures=9,
            by_stage={'tunnel_dead': 9}, by_network={'mobile': 7, 'wifi': 2},
            by_transport={'udp': 9}, short_lived_tunnels=3)
        raw = {'ts': '2026-11-03T10:59:23Z', 'status': 'blocked',
               'summary': 'old DPI conclusion', 'targets': [s.to_dict()],
               'verdicts': [{'kind': 'protocol_fingerprint', 'severity': 'error'}]}
        before = deepcopy(raw)
        result = reclassify_report(raw)
        self.assertEqual(result['status'], 'degraded')
        self.assertFalse(any(v['kind'] in BLOCKING_KINDS for v in result['verdicts']))
        self.assertTrue(any(v['severity'] == 'warning' for v in result['verdicts']))
        self.assertEqual(result['targets'], before['targets'])
        self.assertEqual(result['ts'], before['ts'])
        self.assertEqual(raw, before)

    def test_handshake_reports_do_not_prove_udp_filtering(self):
        s = working_queen()
        s.clients = ClientSignals(window_minutes=30, reports=20, failures=20,
            by_stage={'handshake': 18, 'tcp': 2}, by_transport={'udp': 18})
        verdicts = classify_target(s)
        self.assertEqual(report_status(verdicts), 'degraded')
        self.assertFalse(any(v.kind in BLOCKING_KINDS for v in verdicts))

    def test_mobile_reports_do_not_prove_operator_shutdown(self):
        s = working_queen()
        s.clients = ClientSignals(window_minutes=30, reports=24, failures=24,
            by_stage={'handshake': 24}, by_network={'mobile': 22, 'wifi': 2},
            by_transport={'udp': 24})
        verdicts = classify_target(s)
        self.assertEqual(report_status(verdicts), 'degraded')
        self.assertFalse(any(v.kind in BLOCKING_KINDS for v in verdicts))

    def test_independent_transport_failure_is_still_reported(self):
        s = working_queen()
        s.ru[CHANNEL_WDTT_UDP] = nodes(CHANNEL_WDTT_UDP, False)
        self.assertTrue(any(v.kind in BLOCKING_KINDS for v in classify_target(s)))

    def test_recommendations_only_use_available_udp_capabilities(self):
        for item in knowledge_to_dict():
            plan = ' '.join(item['fixes'] + item['commands']).lower()
            for unavailable in ('olcrtc2', 'vless', 'reality', 'tcp-вход', 'mtproto', 'socks5', 'utls', 'encrypted clienthello'):
                self.assertNotIn(unavailable, plan, item['kind'])

    def test_archived_agent_timeout_is_neutral_and_does_not_mutate_evidence(self):
        from app.services.hive_incidents import _row_to_public
        raw = {'ts': '2026-11-03T10:45:27Z', 'severity': 'warning',
               'source': 'cell-agent.status', 'category': 'network-timeout',
               'hint': 'Сеть/таймаут (в т.ч. DPI или блокировка)',
               'message': '/v1/status failed: ConnectTimeout',
               'checks_json': '["Проверить DPI"]'}
        before = deepcopy(raw)
        result = _row_to_public(raw)
        self.assertNotIn('dpi', result['hint'].lower())
        self.assertNotIn('блокировка', result['hint'].lower())
        self.assertEqual(result['message'], raw['message'])
        self.assertEqual(result['severity'], raw['severity'])
        self.assertEqual(raw, before)


if __name__ == '__main__':
    unittest.main()
