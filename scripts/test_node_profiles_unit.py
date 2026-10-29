"""Exercise the real transaction with a host adapter; no SSH/network mutations."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.node_profile_runtime import apply, rules, GAME_SYSCTLS, restore


class FakeHost:
    def __init__(self):
        self.firewall = set()
        self.sysctls = {k: '30' for k in GAME_SYSCTLS}
        self.mtu = 1280
        self.calls = []
        self.pid = '100'
        self.fail_health = False
        self.checks = 0

    def health(self, queen):
        self.checks += 1
        if self.fail_health and self.checks == 2:
            raise RuntimeError('API health failed')
        return {'pid': self.pid, 'peers': ['existing-client']}

    def present(self, table, chain, args):
        return (table, chain, tuple(args)) in self.firewall

    def rule(self, table, chain, args, enabled):
        key = (table, chain, tuple(args))
        self.calls.append(('rule', key, enabled))
        if enabled:
            self.firewall.add(key)
        else:
            self.firewall.discard(key)

    def run(self, *args, check=True):
        self.calls.append(args)
        if args[:2] == ('sysctl', '-n'):
            return self.sysctls[args[2]]
        if args[:2] == ('sysctl', '-w'):
            key, value = args[2].split('=')
            self.sysctls[key] = value
            return ''
        if args[:2] == ('ip', '-j'):
            return json.dumps([{'mtu': self.mtu}])
        if args[:3] == ('ip', 'link', 'set'):
            self.mtu = int(args[-1])
            return ''
        if args[:3] == ('iptables', '-t', 'nat'):
            return '-A PREROUTING -s 10.66.0.0/16 -p udp --dport 8000 -j DNAT --to-destination 198.51.100.1:8000'
        if args[:2] == ('systemctl', 'is-enabled'):
            return 'disabled'
        raise AssertionError(f'Unexpected host command: {args}')


class TransactionTests(unittest.TestCase):
    def request(self, **kw):
        return {'operation_id': 'fixture-op', 'ai': False, 'gaming': False,
                'queen': True, 'legacy_ai': False, **kw}

    def test_all_profile_combinations_and_nodes(self):
        for queen in (True, False):
            for ai in (True, False):
                for gaming in (True, False):
                    with self.subTest(queen=queen, ai=ai, gaming=gaming), tempfile.TemporaryDirectory() as d:
                        h = FakeHost()
                        result = apply(self.request(queen=queen, ai=ai, gaming=gaming), host=h, root=Path(d))
                        self.assertEqual(result['state'], 'applied')
                        self.assertEqual(h.mtu, 1420 if gaming else 1280)
                        self.assertEqual(len(h.firewall), int(ai) + int(gaming))
                        self.assertEqual(json.loads((Path(d) / 'applied.json').read_text())['gaming'], gaming)

    def test_failure_restores_previous_rules_and_sysctls(self):
        with tempfile.TemporaryDirectory() as d:
            h = FakeHost()
            old = copy.deepcopy(h.sysctls)
            h.fail_health = True
            with self.assertRaisesRegex(RuntimeError, 'API health'):
                apply(self.request(ai=True, gaming=True), host=h, root=Path(d))
            self.assertEqual(h.firewall, set())
            self.assertEqual(h.sysctls, old)
            self.assertEqual(h.mtu, 1420, 'never lower MTU under old clients')
            self.assertFalse((Path(d) / 'applied.json').exists())
            result = json.loads((Path(d) / 'fixture-op.status.json').read_text())
            self.assertTrue(result['rolled_back'])

    def test_disable_preserves_live_mtu_and_shared_rules(self):
        with tempfile.TemporaryDirectory() as d:
            h = FakeHost()
            shared = ('mangle', 'FORWARD', ('-j', 'TCPMSS', '--clamp-mss-to-pmtu'))
            h.firewall.add(shared)
            apply(self.request(ai=True, gaming=True), host=h, root=Path(d))
            apply(self.request(), host=h, root=Path(d))
            self.assertEqual(h.firewall, {shared})
            self.assertEqual(h.mtu, 1420)
            self.assertEqual(h.pid, '100')

    def test_legacy_dns_cleanup_never_touches_api_dnat(self):
        with tempfile.TemporaryDirectory() as d:
            h = FakeHost()
            result = apply(self.request(queen=False, legacy_ai=True), host=h, root=Path(d))
            self.assertEqual(result['state'], 'applied')
            self.assertTrue(all(e['table'] == 'mangle' for e in result['rules']))

    def test_rollback_respects_concurrent_sysctl_changes(self):
        h = FakeHost()
        key = next(iter(GAME_SYSCTLS))
        h.sysctls[key] = '777'
        restore(h, {'sysctls': {key: '888'}})
        self.assertEqual(h.sysctls[key], '777')

    def test_game_never_shortens_existing_udp_timeouts(self):
        with tempfile.TemporaryDirectory() as d:
            h = FakeHost()
            for key in GAME_SYSCTLS:
                if key.startswith('net.netfilter.'):
                    h.sysctls[key] = '600'
            apply(self.request(gaming=True), host=h, root=Path(d))
            self.assertEqual(h.sysctls['net.netfilter.nf_conntrack_udp_timeout'], '600')
            self.assertEqual(h.sysctls['net.netfilter.nf_conntrack_udp_timeout_stream'], '600')

    def test_runtime_has_no_disruptive_operations(self):
        source = (Path(__file__).resolve().parents[1] / 'app/services/node_profile_runtime.py').read_text()
        self.assertNotIn("'restart'", source)
        self.assertNotIn("'wg', 'set'", source)
        self.assertNotIn("'conntrack'", source)
        for table, chain, args, _ in rules():
            self.assertEqual(table, 'mangle')
            self.assertIn('SILENT_NODE_PROFILE', ' '.join(args))
            self.assertNotIn('ACCEPT', args)


if __name__ == '__main__':
    unittest.main()
