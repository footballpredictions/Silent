"""Recovery at the actual shell boundary, including DNS-cache IPs after fw4 reload."""
import unittest
import shlex
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
sv_ru_wan_route() { echo 'wan 192.0.2.1'; }
ip() { if [ "$*" = 'rule show' ]; then echo '162: from all fwmark 0x162 lookup 162'; else echo "$*"; fi; }
sv_ru_ensure_route
''', library='ru-direct.sh')
        self.assertTrue(any('route replace default via 192.0.2.1' in line for line in lines))
        self.assertFalse(any('flush' in line or 'rule del' in line or 'rule add' in line for line in lines))

    def wan_commands(self, routes, failure=''):
        return self.run_shell('test_main_defaults=' + shlex.quote(routes) + '\nfailure=' + shlex.quote(failure) + r'''
# Reproduce Cudy: the configured Ethernet WAN is down, the real uplink is mobile.
ifstatus() { echo '{"up":false,"device":"eth0"}'; }
jsonfilter() { cat >/dev/null; case "$*" in *l3_device*|*nexthop*) return 1 ;; *) echo eth0 ;; esac; }
uci() { return 1; }
ip() {
  case "$*" in
    '-4 route show table main default') printf '%s\n' "$test_main_defaults"; return 0 ;;
    'rule show') [ "$failure" = rule ] || echo '162: from all fwmark 0x162 lookup 162'; return 0 ;;
  esac
  echo "$*" >> "$SV_RUN/commands"
  case "$failure:$*" in route:route\ replace*|rule:rule\ add*) return 2 ;; esac
}
sv_ru_ensure_route
echo "result=$?"
[ ! -f "$SV_RUN/commands" ] || cat "$SV_RUN/commands"
''', library='ru-direct.sh')

    def test_mobile_uplink_uses_active_default_not_disabled_ethernet_wan(self):
        lines = self.wan_commands('default via 10.251.94.137 dev wwan0 proto static src 10.251.94.138')
        self.assertEqual(lines[0], 'result=0')
        self.assertTrue(any('via 10.251.94.137 dev wwan0' in line for line in lines), lines)
        self.assertFalse(any('eth0' in line for line in lines), lines)
        self.assertFalse(any('flush' in line for line in lines), lines)

    def test_pppoe_default_without_gateway_is_preserved(self):
        lines = self.wan_commands('default dev pppoe-provider proto static scope link')
        self.assertIn('route replace default dev pppoe-provider table 162', lines)

    def test_lowest_metric_usable_default_wins_and_vpn_is_excluded(self):
        lines = self.wan_commands('default dev svpath metric 1\n'
                                  'default via 192.0.2.1 dev eth0 metric 2 linkdown\n'
                                  'default via 198.51.100.1 dev backup metric 100\n'
                                  'default via 203.0.113.1 dev uplink metric 10')
        self.assertTrue(any('via 203.0.113.1 dev uplink' in line for line in lines), lines)
        self.assertFalse(any('dev eth0' in line or 'dev svpath' in line for line in lines), lines)

    def test_missing_uplink_is_an_error_and_does_not_install_rule(self):
        lines = self.wan_commands('default dev eth0 linkdown\ndefault dev svpath')
        self.assertEqual(lines, ['result=1'])

    def test_rejected_route_is_an_error_and_does_not_install_rule(self):
        lines = self.wan_commands('default via 192.0.2.1 dev eth1', failure='route')
        self.assertEqual(lines[0], 'result=1')
        self.assertFalse(any('rule add' in line for line in lines), lines)

    def test_rejected_rule_is_an_error(self):
        lines = self.wan_commands('default via 192.0.2.1 dev eth1', failure='rule')
        self.assertEqual(lines[0], 'result=1')

    def test_failed_enable_restores_previous_setting_and_releases_writer_lock(self):
        lines = self.run_shell(r'''
echo 0 > "$SV_RUN/enabled"
uci() {
  case "$*" in
    '-q get silent-vpn.main.ru_direct') cat "$SV_RUN/enabled" ;;
    '-q set silent-vpn.main.ru_direct='*) echo "${3##*=}" > "$SV_RUN/enabled" ;;
  esac
}
sv_ru_apply_inner() { [ "$(cat "$SV_RUN/enabled")" = 0 ]; }
sv_ru_set 1
echo "result=$?"
cat "$SV_RUN/enabled"
sv_ru_lock && echo unlocked
sv_ru_unlock
''', library='ru-direct.sh')
        self.assertEqual(lines, ['result=1', '0', 'unlocked'])

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
