"""Recovery at the actual shell boundary, including DNS-cache IPs after fw4 reload."""
import unittest
import test_path_runtime as runtime


@unittest.skipUnless(runtime.SHELL, 'POSIX shell required')
class PolicyRuntimeTests(unittest.TestCase):
    run_shell = runtime.RouterRuntimeTests.run_shell

    def test_busy_once_worker_cannot_unlock_another_writer(self):
        lines = self.run_shell(r'''
mkdir -p "$SV_RUN/ru.lock"
echo 12345 > "$SV_RUN/ru.lock/pid"
sv_ru_unlock
cat "$SV_RUN/ru.lock/pid"
''', library='ru-direct.sh')
        self.assertEqual(lines, ['12345'])

    def test_restore_large_cache_validates_in_one_batch(self):
        lines = self.run_shell(r'''
printf '192.0.2.1\n999.0.0.1\nnot-an-ip\n' > "$SV_RUN/sv_ru.ips"
printf '198.51.100.2\n' > "$SV_RUN/sv_ru_vpn.ips"
sv_is_ipv4() { echo per-address-fork; return 1; }
nft() { test "$1" = -f || exit 1; cat "$2"; }
sv_ru_restore_sets
''', library='ru-direct.sh')
        self.assertEqual(lines, ['add element inet fw4 sv_ru { 192.0.2.1 }',
                                 'add element inet fw4 sv_ru_vpn { 198.51.100.2 }'])

    def test_repair_restores_cached_ips_and_seeds_vpn_without_dns_restart(self):
        lines = self.run_shell(r'''
sv_ru_enabled() { return 0; }
sv_ru_policy_ready() { return 1; }
sv_ru_ensure_nft() { echo repair-nft; }
sv_ru_ensure_route() { echo repair-route; }
sv_ru_restore_sets() { echo cached-ips; }
sv_ru_seed_vpn_ips() { echo seed-vpn; }
sv_ru_snapshot_sets() { echo save-ips; }
sv_ru_maintain
''', library='ru-direct.sh')
        self.assertEqual(lines, ['repair-nft', 'cached-ips', 'repair-route', 'seed-vpn', 'save-ips'])

    def test_wan_route_refresh_does_not_delete_active_rule_or_flush_table(self):
        lines = self.run_shell(r'''
sv_ru_wan_dev() { echo wan; }
sv_ru_wan_gw() { echo 192.0.2.1; }
ip() { if [ "$*" = 'rule show' ]; then echo '162: from all fwmark 0x162 lookup 162'; else echo "$*"; fi; }
sv_ru_ensure_route
''', library='ru-direct.sh')
        self.assertTrue(any('route replace default via 192.0.2.1' in line for line in lines))
        self.assertFalse(any('flush' in line or 'rule del' in line or 'rule add' in line for line in lines))

    def test_policy_download_skips_error_body_and_uses_first_valid_cell(self):
        lines = self.run_shell(r'''
. "$SV_LIB/routing-policy.sh"
sv_policy_bases() { printf 'hive\ncell1\ncell2\n'; }
sv_hive_timeout_for() { echo 1; }
sv_policy_validate() { grep -q valid "$1"; }
wget() { shift; shift; out="$1"; for arg in "$@"; do url="$arg"; done; echo "$url"; case "$url" in cell1*) echo valid > "$out" ;; *) echo error > "$out" ;; esac; }
sv_policy_fetch
cat "$SV_VAR/routing-policy.json"
''', library='ru-direct.sh')
        self.assertIn('hive/api/vpn/routing-policy', lines)
        self.assertIn('cell1/api/vpn/routing-policy', lines)
        self.assertNotIn('cell2/api/vpn/routing-policy', lines)
        self.assertEqual(lines[-1], 'valid')

    def test_network_failure_keeps_last_good_policy(self):
        lines = self.run_shell(r'''
. "$SV_LIB/routing-policy.sh"
echo saved > "$SV_VAR/routing-policy.json"
sv_policy_bases() { echo offline; }
sv_hive_timeout_for() { echo 1; }
wget() { return 1; }
sv_policy_fetch || true
cat "$SV_VAR/routing-policy.json"
''', library='ru-direct.sh')
        self.assertEqual(lines, ['saved'])


if __name__ == '__main__':
    unittest.main()
