import contextlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path


class MacDnsRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        source = Path(__file__).resolve().parents[1] / 'resources/mac/silent-wg-helper'
        self.m = {'__name__': 'fixture'}
        exec(compile(source.read_text(encoding='utf-8'), str(source), 'exec'), self.m)
        self.m['RUN_DIR'] = self.tmp.name
        self.m['DNS_STATE'] = str(Path(self.tmp.name) / 'persistent/dns-state.json')
        self.m['LEGACY_DNS_STATE'] = str(Path(self.tmp.name) / 'runtime/dns-state.json')
        self.m['_dns_target_services'] = lambda: ['Wi-Fi']
        self.m['_network_services'] = lambda: ['Wi-Fi', 'Ethernet']
        self.m['_flush_dns_cache'] = lambda: None
        self.dns = {'Wi-Fi': ['10.66.66.53'], 'Ethernet': ['9.9.9.9']}
        self.fail_restore = False
        self.m['run'] = self.fake_run
        self.m['run_out'] = self.run_out

    def run_out(self, args, **kwargs):
        if args[1] == '-getdnsservers':
            return '\n'.join(self.dns[args[2]])
        return 'IPv6: Automatic'

    def fake_run(self, args, **kwargs):
        if args[1] == '-setdnsservers':
            if self.fail_restore:
                raise RuntimeError('networksetup failed')
            if args[3:] != ['Empty']:
                self.assertTrue(Path(self.m['DNS_STATE']).is_file(), 'save before mutation')
            self.dns[args[2]] = args[3:]
        return types.SimpleNamespace(returncode=0)

    def call(self, name, args=None):
        with contextlib.redirect_stdout(io.StringIO()):
            self.m[name](args or [])

    def test_reboot_without_state_recovers_only_owned_dns(self):
        self.call('cmd_dns_restore')
        self.assertEqual(self.dns['Wi-Fi'], ['Empty'])
        self.assertEqual(self.dns['Ethernet'], ['9.9.9.9'])

    def test_repeated_set_preserves_original_custom_dns(self):
        self.dns['Wi-Fi'] = ['8.8.8.8']
        self.call('cmd_dns_set', ['utun3', '10.66.66.53'])
        self.call('cmd_dns_set', ['utun3', '10.66.66.53'])
        self.call('cmd_dns_restore')
        self.assertEqual(self.dns['Wi-Fi'], ['8.8.8.8'])

    def test_failed_restore_keeps_recovery_file(self):
        p = Path(self.m['DNS_STATE'])
        p.parent.mkdir()
        p.write_text(json.dumps({'services': {'Wi-Fi': ['8.8.8.8']}, 'v6': {}}))
        self.fail_restore = True
        with self.assertRaises(RuntimeError):
            self.call('cmd_dns_restore')
        self.assertTrue(p.exists())

    def start_until_socket(self, active):
        self.m['need_root'] = lambda: None
        self.m['current_iface'] = lambda: 'utun3' if active else ''
        self.m['iface_up'] = lambda name: active
        def stop_before_listening(*args):
            raise RuntimeError('fixture socket boundary')
        self.m['socket'] = types.SimpleNamespace(
            AF_UNIX=1, SOCK_STREAM=1, socket=stop_before_listening)
        with self.assertRaisesRegex(RuntimeError, 'fixture socket boundary'):
            self.call('cmd_serve')

    def test_boot_recovers_orphaned_dns_before_serving(self):
        self.start_until_socket(active=False)
        self.assertEqual(self.dns['Wi-Fi'], ['Empty'])

    def test_daemon_restart_keeps_live_tunnel_dns(self):
        self.start_until_socket(active=True)
        self.assertEqual(self.dns['Wi-Fi'], ['10.66.66.53'])

    def test_mixed_custom_dns_without_state_is_untouched(self):
        self.dns['Wi-Fi'] = ['10.66.66.53', '9.9.9.9']
        self.call('cmd_dns_restore')
        self.assertEqual(self.dns['Wi-Fi'], ['10.66.66.53', '9.9.9.9'])


if __name__ == '__main__':
    unittest.main()
