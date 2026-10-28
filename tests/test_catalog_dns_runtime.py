"""Exercise native DNS ownership/readiness, without touching host networking."""
import unittest
import test_path_runtime as runtime

@unittest.skipUnless(runtime.SHELL,'POSIX shell required')
class CatalogDNSRuntime(unittest.TestCase):
    run_shell=runtime.RouterRuntimeTests.run_shell
    fixture=r'''
export SV_RUN
SV_CATALOG_SERVICE="$SV_RUN/dns-service"
printf '1.1.1.1\n1.0.0.1\n' > "$SV_RUN/servers"
printf '#!/bin/sh\nexit 0\n' > "$SV_LIB/silent-dns"
chmod +x "$SV_LIB/silent-dns"
cat > "$SV_CATALOG_SERVICE" <<'EOF'
#!/bin/sh
case "$1" in
 start) [ "${CATALOG_FAIL_START:-0}" = 1 ] || echo ready > "$SV_RUN/catalog-dns.ready" ;;
 stop) rm -f "$SV_RUN/catalog-dns.ready" ;;
esac
exit 0
EOF
chmod +x "$SV_CATALOG_SERVICE"
uci() {
 case "$1 $2" in
  '-q get') case "$3" in
    silent-vpn.main.routing_profile) echo catalog-test ;;
    'dhcp.@dnsmasq[0].server') paste -sd ' ' "$SV_RUN/servers" ;;
   esac ;;
  '-q delete') : > "$SV_RUN/servers" ;;
  '-q del_list') grep -Fxv '127.0.0.1#15354' "$SV_RUN/servers" > "$SV_RUN/next" || true; mv "$SV_RUN/next" "$SV_RUN/servers" ;;
  'add_list '*) printf '%s\n' "${2#*=}" >> "$SV_RUN/servers" ;;
  'commit dhcp') : ;;
 esac
}
ip() { echo '4: svpath inet 10.66.66.2/32 scope global'; }
sleep() { :; }
'''
    def test_switches_only_after_ready_and_restores_native_dns(self):
        result=self.run_shell(self.fixture+r'''
touch "$SV_RUN/path.up"
sv_catalog_dns_bind || exit 1
test "$(cat "$SV_RUN/servers")" = '127.0.0.1#15354' || exit 1
test "$(cat "$SV_RUN/catalog-dns.source")" = 10.66.66.2 || exit 1
sv_catalog_dns_stop || exit 1
test ! -f "$SV_RUN/catalog-dns.ready" || exit 1
test ! -f "$SV_RUN/catalog-dns.upstream" || exit 1
cat "$SV_RUN/servers"
''',library='catalog-dns.sh')
        self.assertEqual(result,['1.1.1.1','1.0.0.1'])
    def test_unready_resolver_does_not_capture_client_dns(self):
        result=self.run_shell(self.fixture+r'''
touch "$SV_RUN/path.up"
export CATALOG_FAIL_START=1
if sv_catalog_dns_bind; then exit 1; fi
cat "$SV_RUN/servers"
''',library='catalog-dns.sh')
        self.assertEqual(result,['1.1.1.1','1.0.0.1'])
    def test_no_dns_change_before_tunnel_exists(self):
        result=self.run_shell(self.fixture+r'''
sv_catalog_dns_bind || exit 1
test ! -f "$SV_RUN/catalog-dns.upstream" || exit 1
cat "$SV_RUN/servers"
''',library='catalog-dns.sh')
        self.assertEqual(result,['1.1.1.1','1.0.0.1'])
    def test_merged_profile_is_requested_before_legacy_fallback(self):
        result=self.run_shell(self.fixture+r'''
sv_policy_bases() { echo http://fixture; }
sv_policy_validate() { return 0; }
wget() {
 printf '%s\n' "$*" >> "$SV_RUN/fetches"
 case "$*" in *'?profile=catalog-test'*) return 1 ;; esac
 while [ "$1" != -O ]; do shift; done
 echo valid > "$2"
}
sv_policy_fetch || exit 1
test "$(wc -l < "$SV_RUN/fetches")" = 2 || exit 1
head -n 1 "$SV_RUN/fetches" | grep -q '?profile=catalog-test' || exit 1
tail -n 1 "$SV_RUN/fetches" | grep -q '/api/vpn/routing-policy$' || exit 1
echo compatible
''',library='routing-policy.sh')
        self.assertEqual(result,['compatible'])
