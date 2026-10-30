# Optional typed DNS policy adapter. Owns only its localhost server entry/process.
. "$SV_LIB/common.sh"
SV_CATALOG_SERVICE="${SV_CATALOG_SERVICE:-/etc/init.d/silent-vpn-dns}"
sv_catalog_dns_selected() {
	case "$(uci -q get silent-vpn.main.routing_profile 2>/dev/null)" in
		standard) return 1 ;;
		catalog-test) return 0 ;;
		'') [ -x "$SV_LIB/silent-dns" ] ;;
		*) return 1 ;;
	esac
}
sv_catalog_dns_stop() {
	[ -f "$SV_RUN/catalog-dns.upstream" ] || return 0
	# Stop the resolver even if restoring UCI fails; retain the upstream backup
	# on failure so a subsequent disconnect/recovery can retry restoration.
	if [ -x "$SV_CATALOG_SERVICE" ]; then
		"$SV_CATALOG_SERVICE" stop || return 1
	fi
	rm -f "$SV_RUN/catalog-dns.ready" "$SV_RUN/catalog-dns.source"
	uci -q del_list 'dhcp.@dnsmasq[0].server=127.0.0.1#15354' || true
	if [ -z "$(uci -q get dhcp.@dnsmasq[0].server 2>/dev/null)" ]; then
		for server in $(cat "$SV_RUN/catalog-dns.upstream"); do
			sv_is_ipv4 "$server" || continue
			uci add_list "dhcp.@dnsmasq[0].server=$server" || return 1
		done
	fi
	uci commit dhcp || return 1
	rm -f "$SV_RUN/catalog-dns.ready" "$SV_RUN/catalog-dns.source" "$SV_RUN/catalog-dns.upstream"
}
sv_catalog_dns_bind() {
	local source servers current server i
	# Exclusions can be selected before connecting. Native DNS stays untouched then.
	[ -f "$SV_RUN/path.up" ] || return 0
	[ -x "$SV_LIB/silent-dns" ] && [ -x "$SV_CATALOG_SERVICE" ] || return 1
	source="$(ip -o -4 addr show dev "$SV_WG_IF" | awk '/inet / {split($4,a,"/"); print a[1]; exit}')"
	sv_is_ipv4 "$source" || return 1
	current="$(uci -q get dhcp.@dnsmasq[0].server 2>/dev/null)"
	if [ "$current" = '127.0.0.1#15354' ]; then
		servers="$(cat "$SV_RUN/catalog-dns.upstream" 2>/dev/null)"
	else
		servers="$current"
	fi
	[ -n "$servers" ] || servers='1.1.1.1 1.0.0.1'
	for server in $servers; do sv_is_ipv4 "$server" || return 1; done
	if [ "$(cat "$SV_RUN/catalog-dns.source" 2>/dev/null)" != "$source" ] ||
	   [ "$(cat "$SV_RUN/catalog-dns.upstream" 2>/dev/null)" != "$servers" ]; then
		[ ! -f "$SV_RUN/catalog-dns.source" ] || "$SV_CATALOG_SERVICE" stop
		rm -f "$SV_RUN/catalog-dns.ready"
	fi
	umask 077
	printf '%s\n' "$servers" > "$SV_RUN/catalog-dns.upstream"
	printf '%s\n' "$source" > "$SV_RUN/catalog-dns.source"
	"$SV_CATALOG_SERVICE" start || { sv_catalog_dns_stop; return 1; }
	i=0
	while [ ! -s "$SV_RUN/catalog-dns.ready" ] && [ "$i" -lt 8 ]; do sleep 1; i=$((i+1)); done
	[ -s "$SV_RUN/catalog-dns.ready" ] || { sv_catalog_dns_stop; return 1; }
	# Switch DNS only after the resolver has loaded/validated policy and both listeners.
	uci -q delete 'dhcp.@dnsmasq[0].server' || true
	uci add_list 'dhcp.@dnsmasq[0].server=127.0.0.1#15354' || { sv_catalog_dns_stop; return 1; }
	uci commit dhcp
}
