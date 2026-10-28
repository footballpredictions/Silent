"""Recovery at the actual shell boundary, including DNS-cache IPs after fw4 reload."""
import unittest
import shlex
import test_path_runtime as runtime


@unittest.skipUnless(runtime.SHELL, 'POSIX shell required')
class PolicyRuntimeTests(unittest.TestCase):
    run_shell = runtime.RouterRuntimeTests.run_shell

    def test_reconnect_restores_cached_destinations_before_reporting_ready(self):
        # A reconnect reloads fw4; the browser still holds its DNS answers.
        lines = self.run_shell(r'''
sed 's|/etc/init.d/dnsmasq restart|test_dns_restart|g' "$SV_LIB/ru-direct.sh" > "$SV_RUN/ru-fixture.sh"
. "$SV_RUN/ru-fixture.sh"
rm "$SV_LIB/routing-policy.sh"
printf '192.0.2.7\n' > "$SV_RUN/sv_ru.ips"
printf '198.51.100.8\n' > "$SV_RUN/sv_ru_vpn.ips"
sv_ru_enabled() { return 0; }
dnsmasq() { echo 'options: nftset DHCP'; }
sv_ru_ensure_nft() { :; }
sv_ru_ensure_route() { :; }
sv_ru_write_dns() { :; }
sv_ru_seed_vpn_ips() { :; }
sv_ru_snapshot_sets() { :; }
test_dns_restart() { :; }
nft() { [ "$1" = -f ] || exit 1; cat "$2" >> "$SV_RUN/restored"; }
sv_ru_apply || exit 1
test ! -f "$SV_RUN/restored" || cat "$SV_RUN/restored"
echo ready
''', library='ru-direct.sh')
        self.assertEqual(lines, ['add element inet fw4 sv_ru { 192.0.2.7 }',
                                 'add element inet fw4 sv_ru_vpn { 198.51.100.8 }', 'ready'])

    def test_reconnect_uses_valid_cached_policy_without_network_wait(self):
        lines = self.run_shell(r'''
sed 's|/etc/init.d/dnsmasq restart|test_dns_restart|g' "$SV_LIB/ru-direct.sh" > "$SV_RUN/ru-fixture.sh"
. "$SV_RUN/ru-fixture.sh"
cat > "$SV_LIB/routing-policy.sh" <<'EOF'
sv_policy_validate() { return 0; }
sv_policy_use_cache() { return 0; }
sv_policy_fetch() { echo unexpected-network-wait; return 1; }
EOF
echo cached-policy > "$SV_VAR/routing-policy.json"
sv_ru_enabled() { return 0; }
dnsmasq() { echo 'options: nftset DHCP'; }
sv_ru_ensure_nft() { :; }
sv_ru_ensure_route() { :; }
sv_ru_write_dns() { :; }
sv_ru_seed_vpn_ips() { :; }
sv_ru_snapshot_sets() { :; }
sv_ru_restore_sets() { :; }
jsonfilter() { echo revision; }
test_dns_restart() { :; }
sv_ru_apply || exit 1
echo ready
''', library='ru-direct.sh')
        self.assertEqual(lines, ['ready'])

    def test_connect_cannot_report_success_if_bypass_failed(self):
        lines = self.run_shell(r'''
cat > "$SV_LIB/ru-direct.sh" <<'EOF'
sv_ru_apply() { return 1; }
EOF
sv_hive_register_device() { echo fixture; }
jsonfilter() { echo fixture; }
sv_cloak_start() { :; }
sv_cloak_wait() { :; }
sv_path_up_from_json() { touch "$SV_RUN/path.up"; }
sv_path_clear() { rm -f "$SV_RUN/path.up"; }
sv_cloak_stop() { :; }
sv_hive_connect() { :; }
if sv_connect_full; then echo connected-without-bypass; else echo failed; fi
test ! -f "$SV_RUN/connected" || echo false-connected-marker
''', library='session.sh')
        self.assertEqual(lines, ['failed'])

    def test_firewall_reload_preserves_recent_dns_answers_before_next_poll(self):
        lines = self.run_shell(r'''
sv_ru_enabled() { return 0; }
echo 192.0.2.9 > "$SV_RUN/live"
sv_ru_snapshot_sets() { cat "$SV_RUN/live" >> "$SV_RUN/sv_ru.ips"; }
sv_ru_ensure_nft() { :; }
sv_ru_restore_sets() { cat "$SV_RUN/sv_ru.ips" > "$SV_RUN/live"; }
sv_ru_firewall_restart() { : > "$SV_RUN/live"; }
sv_ru_firewall_reload || exit 1
cat "$SV_RUN/live"
test ! -d "$SV_RUN/ru.lock" || exit 1
''', library='ru-direct.sh')
        self.assertEqual(lines, ['192.0.2.9'])

    def test_background_fetch_does_not_block_reconnect_writer(self):
        lines = self.run_shell(r'''
cat > "$SV_LIB/routing-policy.sh" <<'EOF'
sv_policy_fetch() {
  if [ -d "$SV_RUN/ru.lock" ]; then echo writer-blocked-during-network; fi
  return 1
}
sv_policy_use_cache() { :; }
EOF
sv_ru_enabled() { return 0; }
jsonfilter() { :; }
sv_ru_maintain() { :; }
sv_ru_refresh
test ! -d "$SV_RUN/ru.lock" || exit 1
echo ready
''', library='ru-direct.sh')
        self.assertEqual(lines, ['ready'])

    def test_rejected_cached_ip_restore_is_reported_and_tempfile_removed(self):
        lines = self.run_shell(r'''
echo 192.0.2.7 > "$SV_RUN/sv_ru.ips"
nft() { return 1; }
if sv_ru_restore_sets; then echo false-success; else echo failed; fi
for file in "$SV_RUN"/ru-restore.*; do [ ! -e "$file" ] || echo leaked-tempfile; done
''', library='ru-direct.sh')
        self.assertEqual(lines, ['failed'])

    def test_connect_waits_for_active_policy_writer_and_then_applies_bypass(self):
        lines = self.run_shell(r'''
mkdir -p "$SV_RUN/ru.lock"
echo $$ > "$SV_RUN/ru.lock/pid"
sleep() { rm -f "$SV_RUN/ru.lock/pid"; rmdir "$SV_RUN/ru.lock"; }
sv_ru_apply_inner() { echo bypass-applied; }
sv_ru_apply || exit 1
test ! -d "$SV_RUN/ru.lock" || exit 1
''', library='ru-direct.sh')
        self.assertEqual(lines, ['bypass-applied'])

    def test_firewall_reload_failure_unlocks_and_preserves_saved_addresses(self):
        lines = self.run_shell(r'''
sv_ru_enabled() { return 0; }
echo 192.0.2.9 > "$SV_RUN/sv_ru.ips"
sv_ru_snapshot_sets() { :; }
sv_ru_ensure_nft() { :; }
sv_ru_restore_sets() { :; }
sv_ru_firewall_restart() { return 1; }
if sv_ru_firewall_reload; then echo false-success; else echo failed; fi
cat "$SV_RUN/sv_ru.ips"
test ! -d "$SV_RUN/ru.lock" || exit 1
''', library='ru-direct.sh')
        self.assertEqual(lines, ['failed', '192.0.2.9'])

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

    def test_simultaneous_downloads_publish_complete_cache_without_shared_tempfile(self):
        lines = self.run_shell(r'''
. "$SV_LIB/routing-policy.sh"
sv_policy_bases() { echo fixture; }
sv_policy_validate() { grep -q valid "$1"; }
sv_hive_timeout_for() { echo 1; }
wget() { echo valid > "$3"; }
cp() {
  command cp "$@" || return 1
  echo "$2" >> "$SV_RUN/copies"
  while [ "$(wc -l < "$SV_RUN/copies")" -lt 2 ]; do sleep 0.02; done
}
sv_policy_fetch & first=$!
sv_policy_fetch & second=$!
wait "$first" || exit 1
wait "$second" || exit 1
test "$(sort -u "$SV_RUN/copies" | wc -l)" -eq 2 || exit 1
cat "$SV_VAR/routing-policy.json"
for file in "$SV_VAR"/routing-policy.*; do
  [ "$file" = "$SV_VAR/routing-policy.json" ] || echo leaked-cache-file
done
''', library='ru-direct.sh')
        self.assertEqual(lines, ['valid'])


@unittest.skipUnless(runtime.SHELL, 'POSIX shell required')
class AdditivePolicyRuntimeTests(unittest.TestCase):
    run_shell = runtime.RouterRuntimeTests.run_shell

    def refresh(self, preserve):
        return self.run_shell(r'''
sed 's|/etc/init.d/dnsmasq restart|test_dns_restart|g' "$SV_LIB/ru-direct.sh" > "$SV_RUN/refresh-fixture.sh"
. "$SV_RUN/refresh-fixture.sh"
cat > "$SV_LIB/routing-policy.sh" <<'EOF'
sv_policy_remember_applied() { :; }
sv_policy_preserves_applied() { return ''' + ('0' if preserve else '1') + r'''; }
sv_policy_use_cache() { :; }
EOF
sv_ru_enabled() { return 0; }
sv_ru_lock() { return 0; }
sv_ru_unlock() { :; }
sv_ru_ensure_nft() { :; }
sv_ru_write_dns() { :; }
sv_ru_seed_vpn_ips() { :; }
sv_ru_maintain() { :; }
test_dns_restart() { echo dns-restarted; }
jsonfilter() { echo new-revision; }
nft() { echo "$*"; }
echo old-revision > "$SV_RUN/policy.applied"
date +%s > "$SV_RUN/policy.fetched"
echo cached-client-ip > "$SV_RUN/sv_ru.ips"
sv_ru_refresh
if [ -s "$SV_RUN/sv_ru.ips" ]; then echo cached-route-retained; else echo cached-route-deleted; fi
''', library='ru-direct.sh')

    def test_new_direct_rule_does_not_flush_existing_cached_client_routes(self):
        lines = self.refresh(True)
        self.assertIn('cached-route-retained', lines)
        self.assertFalse(any('flush set' in line for line in lines), lines)

    def test_restrictive_rule_change_still_invalidates_owned_sets(self):
        lines = self.refresh(False)
        self.assertIn('cached-route-deleted', lines)
        self.assertIn('flush set inet fw4 sv_ru', lines)
        self.assertIn('flush set inet fw4 sv_ru_vpn', lines)

    def test_applied_snapshot_tracks_only_the_generation_that_was_applied(self):
        lines = self.run_shell(r'''
jsonfilter() { sed -n 's/.*"revision":"\([^"]*\)".*/\1/p' "$2"; }
echo old > "$SV_RUN/policy.applied"
echo '{"revision":"new"}' > "$SV_VAR/routing-policy.json"
sv_policy_remember_applied || exit 1
test ! -f "$SV_RUN/policy.applied.json" || exit 2
echo '{"revision":"old"}' > "$SV_VAR/routing-policy.json"
sv_policy_remember_applied || exit 3
cat "$SV_RUN/policy.applied.json"
echo '{"revision":"new"}' > "$SV_VAR/routing-policy.json"
sv_policy_remember_applied || exit 4
cat "$SV_RUN/policy.applied.json"
echo new > "$SV_RUN/policy.applied"
sv_policy_remember_applied || exit 5
cat "$SV_RUN/policy.applied.json"
''', library='routing-policy.sh')
        self.assertEqual(lines,['{"revision":"old"}','{"revision":"old"}','{"revision":"new"}'])

    def test_stale_applied_snapshot_never_authorizes_preservation(self):
        lines = self.run_shell(r'''
jsonfilter() { sed -n 's/.*"revision":"\([^"]*\)".*/\1/p' "$2"; }
printf '#!/bin/sh\necho invoked > "$SV_RUN/comparator-called"\nexit 0\n' > "$SV_LIB/silent-dns"
chmod +x "$SV_LIB/silent-dns"
export SV_RUN
echo current > "$SV_RUN/policy.applied"
echo '{"revision":"older"}' > "$SV_RUN/policy.applied.json"
echo '{"revision":"next"}' > "$SV_VAR/routing-policy.json"
if sv_policy_preserves_applied next; then exit 1; fi
test ! -e "$SV_RUN/comparator-called" || exit 2
echo '{"revision":"current"}' > "$SV_RUN/policy.applied.json"
if sv_policy_preserves_applied different-generation; then exit 3; fi
test ! -e "$SV_RUN/comparator-called" || exit 4
sv_policy_preserves_applied next || exit 5
test -e "$SV_RUN/comparator-called" || exit 6
echo safe
''', library='routing-policy.sh')
        self.assertEqual(lines,['safe'])


if __name__ == '__main__':
    unittest.main()
