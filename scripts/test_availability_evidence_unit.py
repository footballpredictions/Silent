"""Reproduce service-probe failures without declaring a working VPN blocked."""
from pathlib import Path
from copy import deepcopy
import asyncio
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai.availability_classifier import BLOCKING_KINDS, classify_target, plan_incidents, report_status
from ai.availability_knowledge import KIND_HTTPS_DEGRADED, KIND_OK, KIND_SERVICE_DOWN, KIND_UDP_BLOCK
from ai.availability_model import (
    CHANNEL_AGENT_TCP, CHANNEL_API_TCP, CHANNEL_PING, CHANNEL_WDTT_UDP,
    ERR_PENDING, ERR_TIMEOUT, NodeResult, ProbeResult, TargetSnapshot, VantageAggregate,
)


def aggregate(channel, *, failed=0, ok=0, pending=0, source='ru-external'):
    nodes = [NodeResult(node=f'ok-{i}', asn=f'AS{100+i}', ok=True) for i in range(ok)]
    nodes += [NodeResult(node=f'fail-{i}', asn=f'AS{200+i}', error_kind=ERR_TIMEOUT) for i in range(failed)]
    nodes += [NodeResult(node=f'pending-{i}', error_kind=ERR_PENDING) for i in range(pending)]
    return VantageAggregate(channel=channel, nodes=nodes, source=source)


def working_cell(*, ping_ok=True):
    s = TargetSnapshot(name='Working cell', host='198.51.100.2', role='cell',
                       agent_port=9100, wdtt_port=56000, wg_port=56001, online_count=25)
    s.local[CHANNEL_AGENT_TCP] = ProbeResult(channel=CHANNEL_AGENT_TCP, ok=True)
    s.ru[CHANNEL_AGENT_TCP] = aggregate(CHANNEL_AGENT_TCP, failed=2, pending=1)
    s.ru[CHANNEL_PING] = aggregate(CHANNEL_PING, ok=2 if ping_ok else 0, failed=0 if ping_ok else 2)
    s.world[CHANNEL_AGENT_TCP] = aggregate(CHANNEL_AGENT_TCP, ok=2, source='world-external')
    return s


class EvidenceTests(unittest.TestCase):
    def test_real_case_two_service_timeouts_and_missing_probe_are_not_vpn_block(self):
        verdicts = classify_target(working_cell())
        self.assertFalse(any(v.kind in BLOCKING_KINDS for v in verdicts), [v.kind for v in verdicts])
        self.assertTrue(verdicts, 'retain observations for diagnostics')
        self.assertTrue(all(v.severity == 'info' and not v.commands for v in verdicts))

    def test_service_and_ping_failures_do_not_prove_whole_ip_blackhole(self):
        verdicts = classify_target(working_cell(ping_ok=False))
        self.assertFalse(any(v.kind in BLOCKING_KINDS for v in verdicts), [v.kind for v in verdicts])

    def test_service_probe_never_creates_an_incident_after_repeated_checks(self):
        state = {}
        for cycle in range(5):
            pushed, state = plan_incidents(classify_target(working_cell()), state,
                now_ts=10000 + cycle * 1800, confirm_cycles=2, renotify_sec=3600, max_per_cycle=5)
            self.assertEqual(pushed, [])

    def test_one_bad_probe_with_missing_nodes_is_not_a_confirmed_port_block(self):
        s = TargetSnapshot(name='Queen', host='198.51.100.1', role='queen', api_port=443)
        s.local[CHANNEL_API_TCP] = ProbeResult(channel=CHANNEL_API_TCP, ok=True)
        s.ru[CHANNEL_PING] = aggregate(CHANNEL_PING, ok=2)
        s.ru[CHANNEL_API_TCP] = aggregate(CHANNEL_API_TCP, failed=1, pending=2)
        s.world[CHANNEL_API_TCP] = aggregate(CHANNEL_API_TCP, ok=2, source='world-external')
        self.assertFalse(any(v.kind in BLOCKING_KINDS for v in classify_target(s)))

    def test_external_https_timeouts_are_a_path_warning_without_claiming_filtering(self):
        s = TargetSnapshot(name='Queen', host='198.51.100.1', role='queen', api_port=443)
        s.local[CHANNEL_API_TCP] = ProbeResult(channel=CHANNEL_API_TCP, ok=True)
        s.ru[CHANNEL_PING] = aggregate(CHANNEL_PING, ok=2)
        s.ru[CHANNEL_API_TCP] = aggregate(CHANNEL_API_TCP, failed=2, pending=1)
        s.world[CHANNEL_API_TCP] = aggregate(CHANNEL_API_TCP, ok=2, source='world-external')
        verdicts = classify_target(s)
        self.assertFalse(any(v.kind in BLOCKING_KINDS for v in verdicts))
        self.assertIn(KIND_HTTPS_DEGRADED, [v.kind for v in verdicts])
        self.assertEqual(report_status(verdicts), 'degraded')
        self.assertTrue(all(v.severity == 'warning' for v in verdicts))

    def test_local_service_failure_is_still_reported(self):
        s = working_cell()
        s.local[CHANNEL_AGENT_TCP].ok = False
        self.assertIn(KIND_SERVICE_DOWN, [v.kind for v in classify_target(s)])

    def test_real_transport_block_is_still_reported(self):
        s = working_cell()
        s.ru[CHANNEL_AGENT_TCP] = aggregate(CHANNEL_AGENT_TCP, ok=3)
        s.ru[CHANNEL_WDTT_UDP] = aggregate(CHANNEL_WDTT_UDP, failed=3)
        s.ru[CHANNEL_API_TCP] = aggregate(CHANNEL_API_TCP, ok=3)
        self.assertIn(KIND_UDP_BLOCK, [v.kind for v in classify_target(s)])

    def test_stored_false_block_is_reclassified_without_changing_measurements(self):
        from ai.availability_report import reclassify_report
        target = working_cell().to_dict()
        target.pop('agent_port')  # Reports saved before this fix omitted the port.
        report = {'ts': '2026-10-29T14:42:51+00:00', 'status': 'blocked',
                  'summary': 'old block', 'worst_severity': 'error', 'targets': [target],
                  'verdicts': [{'kind': 'port_block', 'channel': 'agent_tcp'}]}
        original = deepcopy(report)
        result = reclassify_report(report)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['worst_severity'], 'info')
        self.assertFalse(any(v['kind'] in BLOCKING_KINDS for v in result['verdicts']))
        self.assertEqual(result['ts'], report['ts'])
        self.assertEqual(result['targets'], report['targets'])
        self.assertEqual(report, original)

    def test_stored_real_transport_block_is_preserved(self):
        from ai.availability_report import reclassify_report
        s = working_cell()
        s.ru[CHANNEL_AGENT_TCP] = aggregate(CHANNEL_AGENT_TCP, ok=3)
        s.ru[CHANNEL_WDTT_UDP] = aggregate(CHANNEL_WDTT_UDP, failed=3)
        result = reclassify_report({'targets': [s.to_dict()], 'status': 'blocked'})
        self.assertEqual(result['status'], 'blocked')
        self.assertIn(KIND_UDP_BLOCK, [v['kind'] for v in result['verdicts']])

    def test_incomplete_legacy_report_is_not_silently_made_healthy(self):
        from ai.availability_report import reclassify_report
        for targets in ([], [{'name': 'missing data'}], [working_cell().to_dict(), {}]):
            original = {'targets': targets, 'status': 'blocked', 'summary': 'original'}
            result = reclassify_report(original)
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['summary'], 'original')

    def test_latest_and_history_use_current_rules_without_database_writes(self):
        from app.services import availability_store as store
        raw = json.dumps({'targets': [working_cell().to_dict()], 'status': 'blocked',
                          'summary': 'old block', 'ts': '2026-10-29T14:42:51+00:00'})
        row = {'ts': '2026-10-29T14:42:51+00:00', 'status': 'blocked',
               'summary': 'old block', 'report_json': raw}
        db = MagicMock()
        db.execute = AsyncMock(return_value=SimpleNamespace(
            mappings=lambda: SimpleNamespace(first=lambda: row, all=lambda: [row])))
        db.commit = AsyncMock()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=db)
        context.__aexit__ = AsyncMock(return_value=None)
        async def read():
            with patch.object(store, 'AsyncSessionLocal', return_value=context):
                latest = await store.load_latest_report()
                history = await store.load_history(30)
            self.assertEqual(latest['status'], 'unknown')
            self.assertEqual(history[0]['status'], 'unknown')
            self.assertEqual(history[0]['ts'], row['ts'])
            db.commit.assert_not_awaited()
            self.assertEqual(row['report_json'], raw)
            for call in db.execute.await_args_list:
                self.assertTrue(str(call.args[0]).startswith('SELECT '))
        asyncio.run(read())

    def test_repeated_node_does_not_count_as_independent_failures(self):
        s = TargetSnapshot(name='Queen', host='198.51.100.1', role='queen')
        s.local[CHANNEL_API_TCP] = ProbeResult(channel=CHANNEL_API_TCP, ok=True)
        s.ru[CHANNEL_PING] = aggregate(CHANNEL_PING, ok=2)
        s.ru[CHANNEL_API_TCP] = VantageAggregate(CHANNEL_API_TCP, nodes=[
            NodeResult(node='same-node', error_kind='reset'),
            NodeResult(node='same-node', error_kind='reset')])
        self.assertFalse(any(v.kind in BLOCKING_KINDS for v in classify_target(s)))


if __name__ == '__main__':
    unittest.main()
