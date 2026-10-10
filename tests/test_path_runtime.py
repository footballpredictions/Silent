"""Run packaged shell functions with controlled router command boundaries."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which("sh")
if not SHELL and os.name == "nt":
    candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/sh.exe"
    if candidate.is_file():
        SHELL = str(candidate)


@unittest.skipUnless(SHELL, "POSIX shell required")
class RouterRuntimeTests(unittest.TestCase):
    def test_installer_upgrades_plain_dnsmasq_and_preserves_dhcp_configuration(self):
        definitions = (ROOT / 'install.sh').read_text(encoding='utf-8').split('cmd="${1:-all}"')[0]
        definitions = definitions.replace('/etc/init.d/dnsmasq restart', 'true')
        lines = self.run_shell(definitions + r'''
SV_PKG=apk
SV_DHCP_CONFIG="$SV_RUN/dhcp"
echo original > "$SV_DHCP_CONFIG"
dnsmasq() { if [ -f "$SV_RUN/full" ]; then echo 'options: nftset DHCP'; else echo 'options: no-nftset DHCP'; fi; }
apk() { echo "$*"; touch "$SV_RUN/full"; echo replaced > "$SV_DHCP_CONFIG"; }
install_dns_nftset || exit 1
test "$(cat "$SV_DHCP_CONFIG")" = original || exit 1
install_dns_nftset || exit 1
''')
        self.assertEqual(lines.count('add dnsmasq-full'), 1)

    def test_ru_existing_empty_chains_receive_mark_rules(self):
        lines = self.run_shell(r'''
SV_RU_NFT="$SV_RUN/ru.nft"
nft() { case "$1" in -f) cat "$2" ;; *) echo "$*" ;; esac; }
sv_ru_ensure_nft
''', library='ru-direct.sh')
        self.assertTrue(any('add rule inet fw4 silent_ru_mark' in line for line in lines))
        self.assertTrue(any('add rule inet fw4 silent_ru_out' in line for line in lines))

    def test_ru_dns_domains_use_uci_instead_of_an_unread_snippet(self):
        lines = self.run_shell(r'''
SV_RU_LIST="$SV_RUN/domains"
printf 'ozon.ru\nyandex.ru\n' > "$SV_RU_LIST"
uci() { echo "$*"; }
sv_ru_write_dns
''', library='ru-direct.sh')
        self.assertIn('set dhcp.silent_ru=ipset', lines)
        self.assertIn('add_list dhcp.silent_ru.domain=ozon.ru', lines)
        self.assertIn('add_list dhcp.silent_ru.name=sv_ru', lines)

    def test_ru_dns_windows_domain_list_has_no_carriage_returns_in_uci(self):
        self.run_shell(r'''
SV_RU_LIST="$SV_RUN/domains"
printf '# list\r\nozon.ru\r\n\r\nozone.ru\r\nwbbasket.ru\r\n' > "$SV_RU_LIST"
uci() {
    case "$*" in
        'add_list dhcp.silent_ru.domain='*) printf '%s\n' "$2" >> "$SV_RUN/uci-domains" ;;
    esac
}
sv_ru_write_dns || exit 1
printf 'dhcp.silent_ru.domain=ozon.ru\ndhcp.silent_ru.domain=ozone.ru\ndhcp.silent_ru.domain=wbbasket.ru\n' > "$SV_RUN/expected"
cmp "$SV_RUN/expected" "$SV_RUN/uci-domains"
''', library='ru-direct.sh')

    def test_ru_addresses_do_not_expire_while_browsers_keep_dns_cache(self):
        lines = self.run_shell(r'''
SV_RU_NFT="$SV_RUN/ru.nft"
nft() { case "$1" in -f) cat "$2" ;; *) echo "$*" ;; esac; }
sv_ru_ensure_nft || exit 1
cat "$SV_RU_NFT"
''', library='ru-direct.sh')
        self.assertFalse(any('timeout' in line for line in lines), '\n'.join(lines))

    def test_ru_timed_set_is_migrated_atomically_preserving_learned_addresses(self):
        lines = self.run_shell(r'''
SV_RU_NFT="$SV_RUN/ru.nft"
nft() {
    case "$*" in
        'list set inet fw4 sv_ru') echo 'set sv_ru { type ipv4_addr; timeout 1h; }' ;;
        '-j list set inet fw4 sv_ru') echo '{"nftables":[{"set":{"elem":[{"elem":{"val":"198.18.0.1"}}]}}]}' ;;
        '-f '*) echo ATOMIC; cat "$2" ;;
        *) echo "$*" ;;
    esac
}
jsonfilter() { echo '198.18.0.1'; }
sv_ru_ensure_nft || exit 1
''', library='ru-direct.sh')
        self.assertIn('ATOMIC', lines)
        self.assertIn('delete set inet fw4 sv_ru', lines)
        self.assertTrue(any('add element inet fw4 sv_ru { 198.18.0.1 }' in line for line in lines))
        self.assertLess(lines.index('flush chain inet fw4 silent_ru_mark'), lines.index('delete set inet fw4 sv_ru'))

    def test_gateway_wait_tolerates_initial_packet_loss_but_is_bounded(self):
        for success in (True, False):
            with self.subTest(success=success):
                lines = self.run_shell(r'''
ping() {
    n=$(cat "$SV_RUN/ping.count" 2>/dev/null || echo 0)
    n=$((n + 1)); echo "$n" > "$SV_RUN/ping.count"
    ''' + ('[ "$n" -ge 2 ]' if success else 'return 1') + r'''
}
sleep() { :; }
if sv_path_wait_gateway; then echo ready; else echo unavailable; fi
cat "$SV_RUN/ping.count"
''')
                self.assertEqual(lines, ['ready', '2'] if success else ['unavailable', '5'])

    def test_dns_snapshot_survives_runtime_directory_loss_and_restores_unset_options(self):
        lines = self.run_shell(r'''
SV_VAR="$SV_RUN/persistent"
mkdir -p "$SV_VAR"
jsonfilter() { echo '1.1.1.1'; }
uci() { case "$*" in '-q get '*) return 1 ;; esac; }
ip() { case "$*" in 'rule del pref 202 lookup 201') return 1 ;; esac; }
sv_path_dns_restart() { :; }
sv_path_dns_apply fixture || exit 1
test -d "$SV_VAR/dns.before" || exit 1
test ! -f "$SV_VAR/dns.before/server" || exit 1
test ! -f "$SV_VAR/dns.before/noresolv" || exit 1
SV_RUN="$SV_RUN/new-runtime-after-boot"
sv_path_dns_restore || exit 1
test ! -d "$SV_VAR/dns.before" || exit 1
echo restored
''')
        self.assertEqual(lines, ['restored'])

    def test_ipv4_validation_accepts_addresses_and_rejects_invalid_input(self):
        lines = self.run_shell(r'''
for address in 1.1.1.1 192.168.1.1; do sv_is_ipv4 "$address" || exit 1; done
for address in 256.1.1.1 a.b.c.d 1.1.1 '1.1.1.1/32' ''; do
    if sv_is_ipv4 "$address"; then exit 1; fi
done
echo valid
''')
        self.assertEqual(lines, ['valid'])

    def test_selected_dns_is_used_and_routed_without_changing_wan_default(self):
        commands = self.run_shell(r'''
jsonfilter() { echo '1.1.1.1,1.0.0.1'; }
uci() {
    case "$*" in
        '-q get dhcp.@dnsmasq[0].server') echo '9.9.9.9' ;;
        '-q get dhcp.@dnsmasq[0].noresolv') echo 0 ;;
        '-q get silent-vpn.main.dns_preset') echo server ;;
        *) echo "uci $*" >> "$SV_RUN/commands" ;;
    esac
}
ip() { echo "ip $*" >> "$SV_RUN/commands"; case "$*" in 'rule del pref 202 lookup 201') return 1 ;; esac; }
sv_path_dns_restart() { echo restart >> "$SV_RUN/commands"; }
sv_path_dns_apply fixture || exit 1
sv_path_dns_restore || exit 1
test ! -d "$SV_RUN/dns.before" || exit 1
cat "$SV_RUN/commands"
''')
        self.assertIn('uci set dhcp.@dnsmasq[0].noresolv=1', commands)
        for server in ('1.1.1.1', '1.0.0.1'):
            self.assertIn(f'uci add_list dhcp.@dnsmasq[0].server={server}', commands)
            self.assertIn(f'ip rule add to {server}/32 lookup 201 pref 202', commands)
        self.assertIn('uci add_list dhcp.@dnsmasq[0].server=9.9.9.9', commands)
        self.assertIn('uci set dhcp.@dnsmasq[0].noresolv=0', commands)
        self.assertEqual(commands.count('restart'), 2)
        self.assertFalse(any('route replace default' in command for command in commands))

    def run_shell(self, script, library="path.sh"):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            lib = run / "lib"
            lib.mkdir()
            # Match the release packer's LF conversion, including Windows checkouts.
            for source in (ROOT / "files/usr/lib/silent-vpn").glob("*.sh"):
                (lib / source.name).write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
            environment = os.environ.copy()
            environment.update(SV_LIB=lib.as_posix(), SV_RUN=run.as_posix(), SV_VAR=run.as_posix())
            result = subprocess.run(
                [SHELL, "-c", '. "$SV_LIB/' + library + '"\nsv_log() { :; }\n' + script],
                env=environment, capture_output=True, text=True, encoding='utf-8', timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout.splitlines()

    def test_router_tunnel_api_has_a_route_before_lan_policy(self):
        commands = self.run_shell(r'''
sv_path_ip() { echo ip; }
uci() { echo br-lan; }
ip() {
    printf '%s\n' "$*" >> "$SV_RUN/commands"
    case "$*" in
        '-4 route show dev br-lan proto kernel') echo '192.168.1.0/24 scope link' ;;
    esac
}
sv_path_lan_clients || exit 1
cat "$SV_RUN/commands"
''')
        gateway = "route replace 10.66.66.1/32 dev svpath"
        self.assertIn(gateway, commands)
        self.assertLess(commands.index(gateway), commands.index(
            "rule add from 192.168.1.0/24 iif br-lan lookup 201 pref 201"))
        self.assertFalse(any("route replace default" in c and "table 201" not in c for c in commands))

    def test_cleanup_removes_gateway_route_and_stale_up_marker(self):
        commands = self.run_shell(r'''
sv_path_ip() { echo ip; }
ip() { echo "$*"; case "$*" in 'rule del lookup 201') return 1 ;; esac; }
touch "$SV_RUN/path.up"
sv_path_drop_blackhole
[ ! -f "$SV_RUN/path.up" ] || exit 1
''')
        self.assertIn("route del 10.66.66.1/32 dev svpath", commands)

    def test_forward_accept_requires_both_directions(self):
        verdict = self.run_shell(r'''
uci() { echo br-lan; }
nft() {
    case "$*" in
        'list chain inet fw4 srcnat') echo 'oifname "svpath" masquerade comment "silent-vpn"' ;;
        'list chain inet fw4 forward') echo 'iifname "br-lan" oifname "svpath" counter accept comment "silent-vpn"' ;;
    esac
}
if sv_path_fw_seen; then echo unsafe; else echo incomplete; fi
''')
        self.assertEqual(verdict, ["incomplete"])

    def test_zone_jump_without_nat_is_not_a_ready_path(self):
        verdict = self.run_shell(r'''
uci() { echo br-lan; }
nft() {
    case "$*" in
        'list chain inet fw4 srcnat') echo 'oifname "svpath" jump srcnat_svpath' ;;
        'list chain inet fw4 forward')
            echo 'iifname "br-lan" oifname "svpath" counter accept'
            echo 'iifname "svpath" oifname "br-lan" counter accept' ;;
    esac
}
if sv_path_fw_seen; then echo unsafe; else echo incomplete; fi
''')
        self.assertEqual(verdict, ["incomplete"])

    def test_complete_nat_and_forward_is_ready(self):
        verdict = self.run_shell(r'''
uci() { echo br-lan; }
nft() {
    case "$*" in
        'list chain inet fw4 srcnat') echo 'oifname "svpath" snat ip to 10.66.0.100' ;;
        'list chain inet fw4 forward')
            echo 'iifname "br-lan" oifname "svpath" counter accept'
            echo 'iifname "svpath" oifname "br-lan" counter accept' ;;
    esac
}
if sv_path_fw_seen; then echo ready; else echo incomplete; fi
''')
        self.assertEqual(verdict, ["ready"])

    def test_failed_connect_cleans_partial_path_before_cloak(self):
        for stage in ("start", "wait", "path"):
            with self.subTest(stage=stage):
                events = self.run_shell(r'''
sv_hive_register_device() { echo config; }
jsonfilter() { echo fixture; }
sv_cloak_start() { echo start; [ "''' + stage + r'''" != start ]; }
sv_cloak_wait() { echo wait; [ "''' + stage + r'''" != wait ]; }
sv_path_up_from_json() { touch "$SV_RUN/path.up" "$SV_RUN/connected"; echo path; return 1; }
sv_path_clear() { echo clear; rm -f "$SV_RUN/path.up"; }
sv_cloak_stop() { echo stop; }
if sv_connect_full; then exit 1; fi
[ ! -f "$SV_RUN/path.up" ] && [ ! -f "$SV_RUN/connected" ] || exit 1
''', library="session.sh")
                self.assertEqual(events[-2:], ["clear", "stop"])

    def test_kernel_tuning_restores_original_values(self):
        events = self.run_shell(r'''
SV_PROC_SYS="$SV_RUN/proc"
mkdir -p "$SV_PROC_SYS/net/ipv4/conf/all" "$SV_PROC_SYS/net/ipv4/conf/default"
echo 1 > "$SV_PROC_SYS/net/ipv4/ip_forward"
echo 0 > "$SV_PROC_SYS/net/ipv4/conf/all/rp_filter"
echo 1 > "$SV_PROC_SYS/net/ipv4/conf/default/rp_filter"
sysctl() { echo "$*" >> "$SV_RUN/sysctl.calls"; }
nft() { :; }
ip() { :; }
ping() { :; }
sv_path_kernel_fix >/dev/null
: > "$SV_RUN/sysctl.calls"
sv_path_kernel_restore
[ ! -f "$SV_RUN/kernel.before" ] || exit 1
cat "$SV_RUN/sysctl.calls"
''')
        self.assertEqual(events, ["-w net.ipv4.ip_forward=1", "-w net.ipv4.conf.all.rp_filter=0",
                                  "-w net.ipv4.conf.default.rp_filter=1"])


if __name__ == "__main__":
    unittest.main()
