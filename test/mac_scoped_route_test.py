import contextlib
import io
import tempfile
import types
import unittest
from pathlib import Path


class MacScopedRouteTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        source = Path(__file__).resolve().parents[1] / 'resources' / 'mac' / 'silent-wg-helper'
        self.module = {'__name__': 'fixture'}
        exec(compile(source.read_text(encoding='utf-8'), str(source), 'exec'), self.module)
        self.module['RUN_DIR'] = self.directory.name
        self.module['LAN_PROTECT_STATE'] = str(Path(self.directory.name) / 'lan-protect.json')
        self.module['run'] = self.run_route
        self.routes = {}
        self.mutations = []
        self.fail_add = False

    def run_route(self, arguments, **options):
        self.assertEqual(arguments[:2], ['route', '-n'])
        operation = arguments[2]
        self.assertEqual(arguments[3], '-ifscope', 'must never modify the ordinary VPN default')
        interface = arguments[4]
        self.assertEqual(arguments[5], 'default')
        gateway = self.routes.get(interface)
        if operation == 'get':
            output = f'gateway: {gateway}\ninterface: {interface}\nflags: <UP,GATEWAY,IFSCOPE>\n' if gateway else ''
            return types.SimpleNamespace(returncode=0 if gateway else 1, stdout=output, stderr='')
        self.mutations.append(arguments)
        if operation == 'add':
            if gateway or self.fail_add:
                return types.SimpleNamespace(returncode=1, stdout='', stderr='File exists' if gateway else 'unreachable')
            self.routes[interface] = arguments[6]
        elif operation == 'delete':
            self.assertEqual(gateway, arguments[6], 'must not delete another gateway')
            del self.routes[interface]
        else:
            self.fail(operation)
        return types.SimpleNamespace(returncode=0, stdout='', stderr='')

    def call(self, name, arguments):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.module[name](arguments)

    def test_missing_scoped_route_is_added_and_refresh_is_idempotent(self):
        self.call('cmd_protect_on', ['192.0.2.1', 'en0'])
        self.assertEqual(self.routes.get('en0'), '192.0.2.1')
        self.assertTrue(Path(self.module['LAN_PROTECT_STATE']).is_file())
        self.call('cmd_protect_on', ['192.0.2.1', 'en0'])
        self.assertEqual(len(self.mutations), 1)
        self.call('cmd_protect_off', [])
        self.assertNotIn('en0', self.routes)
        self.assertFalse(Path(self.module['LAN_PROTECT_STATE']).exists())

    def test_preexisting_scoped_route_is_preserved_on_disconnect(self):
        self.routes['en0'] = '192.0.2.1'
        self.call('cmd_protect_on', ['192.0.2.1', 'en0'])
        self.call('cmd_protect_off', [])
        self.assertEqual(self.routes['en0'], '192.0.2.1')
        self.assertEqual(self.mutations, [])

    def test_network_change_removes_only_owned_old_route(self):
        self.call('cmd_protect_on', ['192.0.2.1', 'en0'])
        self.call('cmd_protect_on', ['198.51.100.1', 'en7'])
        self.assertEqual(self.routes, {'en7': '198.51.100.1'})

    def test_admin_replacement_is_not_removed(self):
        self.call('cmd_protect_on', ['192.0.2.1', 'en0'])
        self.routes['en0'] = '192.0.2.254'
        self.call('cmd_protect_off', [])
        self.assertEqual(self.routes['en0'], '192.0.2.254')

    def test_refresh_restores_disappeared_owned_route(self):
        self.call('cmd_protect_on', ['192.0.2.1', 'en0'])
        self.routes.clear()
        self.call('cmd_protect_on', ['192.0.2.1', 'en0'])
        self.assertEqual(self.routes, {'en0': '192.0.2.1'})

    def test_failed_route_creation_does_not_claim_success_or_ownership(self):
        self.fail_add = True
        with self.assertRaises(SystemExit):
            self.call('cmd_protect_on', ['192.0.2.1', 'en0'])
        self.assertFalse(Path(self.module['LAN_PROTECT_STATE']).exists())

    def test_different_preexisting_gateway_is_not_overwritten(self):
        self.routes['en0'] = '192.0.2.254'
        with self.assertRaises(SystemExit):
            self.call('cmd_protect_on', ['192.0.2.1', 'en0'])
        self.assertEqual(self.routes['en0'], '192.0.2.254')
        self.assertEqual(self.mutations, [])


if __name__ == '__main__':
    unittest.main()
