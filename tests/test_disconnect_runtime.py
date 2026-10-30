"""Exercise disconnect and the still-running policy worker at router boundaries."""
import unittest
import test_path_runtime as runtime


@unittest.skipUnless(runtime.SHELL, "POSIX shell required")
class DisconnectRuntimeTests(unittest.TestCase):
    run_shell = runtime.RouterRuntimeTests.run_shell

    fixture = r'''
export SV_RUN
SV_RU_NFT="$SV_RUN/ru.nft"
SV_CATALOG_SERVICE="$SV_RUN/dns-service"
printf '#!/bin/sh\nrm -f "$SV_RUN/catalog-dns.ready"\n' > "$SV_CATALOG_SERVICE"
chmod +x "$SV_CATALOG_SERVICE"
printf '1.1.1.1\n' > "$SV_RUN/catalog-dns.upstream"
touch "$SV_RUN/catalog-dns.ready" "$SV_RUN/path.up" "$SV_RUN/connected"
touch "$SV_RUN/dhcp.silent_ru" "$SV_RUN/dhcp.silent_ru_vpn" "$SV_RU_NFT"
mkdir -p "$SV_VAR/dns.before"
printf '9.9.9.9\n' > "$SV_VAR/dns.before/server"
printf '0\n' > "$SV_VAR/dns.before/noresolv"
uci() {
 case "$*" in
  '-q get silent-vpn.main.ru_direct') echo 1 ;;
  '-q get dhcp.@dnsmasq[0].server') echo '127.0.0.1#15354' ;;
  '-q delete dhcp.silent_ru'|'-q delete dhcp.silent_ru_vpn') rm -f "$SV_RUN/$3" ;;
  'commit dhcp') return "${FAIL_DNS_COMMIT:-0}" ;;
 esac
}
ip() { case "$*" in 'rule del lookup 201'|'rule del pref 202 lookup 201') return 1 ;; esac; }
nft() { :; }
ifdown() { :; }
sv_path_ip() { echo ip; }
sv_path_dns_restart() { :; }
sv_path_kernel_restore() { :; }
sv_path_offload_restore() { :; }
sv_path_fw_drop_files() { :; }
sv_ru_firewall_restart() { :; }
sv_hive_disconnect() { :; }
sv_cloak_stop() { :; }
'''

    def test_disconnect_removes_bypass_runtime_without_changing_saved_preference(self):
        lines = self.run_shell(self.fixture + r'''
sv_disconnect_full || exit 1
test ! -f "$SV_RUN/path.up" || exit 1
test ! -f "$SV_RUN/connected" || exit 1
test ! -f "$SV_RU_NFT" || { echo residual-firewall; exit 1; }
test ! -f "$SV_RUN/dhcp.silent_ru" || { echo residual-dns; exit 1; }
test ! -f "$SV_RUN/dhcp.silent_ru_vpn" || exit 1
test ! -f "$SV_RUN/catalog-dns.ready" || exit 1
test ! -d "$SV_VAR/dns.before" || exit 1
test "$(uci -q get silent-vpn.main.ru_direct)" = 1 || exit 1
echo stopped
''', library="session.sh")
        self.assertEqual(lines, ["stopped"])

    def test_worker_does_not_reinstall_policy_or_dns_while_vpn_is_off(self):
        lines = self.run_shell(r'''
cat > "$SV_LIB/routing-policy.sh" <<'EOF'
sv_policy_remember_applied() { :; }
sv_policy_fetch() { echo unexpected-fetch; }
sv_policy_use_cache() { :; }
EOF
uci() { echo 1; }
jsonfilter() { echo revision; }
sv_ru_ensure_nft() { echo residual-firewall; }
sv_ru_write_dns() { echo residual-dns; }
sv_ru_seed_vpn_ips() { :; }
sv_ru_maintain() { echo residual-routes; }
sv_ru_refresh
echo stopped
''', library="ru-direct.sh")
        self.assertEqual(lines, ["stopped"])

    def test_disconnect_reports_failed_dns_restoration_after_stopping_transport(self):
        lines = self.run_shell(self.fixture + r'''
FAIL_DNS_COMMIT=1
sv_cloak_stop() { echo transport-stopped; }
if sv_disconnect_full; then echo false-success; else echo restore-failed; fi
test ! -f "$SV_RUN/path.up" || exit 1
test -d "$SV_VAR/dns.before" || exit 1
''', library="session.sh")
        self.assertEqual(lines, ["transport-stopped", "restore-failed"])

    def test_fetch_started_before_disconnect_cannot_reactivate_bypass(self):
        lines = self.run_shell(r'''
touch "$SV_RUN/path.up"
cat > "$SV_LIB/routing-policy.sh" <<'EOF'
sv_policy_remember_applied() { :; }
sv_policy_fetch() { rm -f "$SV_RUN/path.up"; }
sv_policy_use_cache() { echo stale-policy-applied; }
EOF
uci() { echo 1; }
sv_ru_maintain() { echo residual-routes; }
sv_ru_refresh
test ! -d "$SV_RUN/ru.lock" || exit 1
echo stopped
''', library="ru-direct.sh")
        self.assertEqual(lines, ["stopped"])

    def test_firewall_reload_does_not_restore_bypass_after_disconnect(self):
        lines = self.run_shell(r'''
uci() { echo 1; }
sv_ru_snapshot_sets() { echo unexpected-snapshot; }
sv_ru_ensure_nft() { echo residual-firewall; }
sv_ru_restore_sets() { echo residual-sets; }
sv_ru_firewall_restart() { :; }
sv_ru_firewall_reload || exit 1
echo stopped
''', library="ru-direct.sh")
        self.assertEqual(lines, ["stopped"])

    def test_failed_dns_commit_still_stops_native_resolver_and_keeps_backup(self):
        lines = self.run_shell(self.fixture + r'''
FAIL_DNS_COMMIT=1
. "$SV_LIB/catalog-dns.sh"
if sv_catalog_dns_stop; then exit 1; fi
test ! -f "$SV_RUN/catalog-dns.ready" || exit 1
test -f "$SV_RUN/catalog-dns.upstream" || exit 1
echo stopped-with-recovery-backup
''', library="session.sh")
        self.assertEqual(lines, ["stopped-with-recovery-backup"])


if __name__ == "__main__":
    unittest.main()
