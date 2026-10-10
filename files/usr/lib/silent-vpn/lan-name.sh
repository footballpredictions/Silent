# Bind {lan-ip}.silent.vpn and silent.vpn to the current LAN IPv4 via dnsmasq.

. "$SV_LIB/common.sh"

SV_DNSMASQ_SNIPPET="/tmp/dnsmasq.d/silent-vpn.conf"

sv_lan_apply_dns() {
	local ip host addrs addr
	ip="$(sv_lan_ip | tr -d ' \t\r\n')"
	case "$ip" in
		""|*[!0-9.]*) return 1 ;;
	esac
	host="${ip}.${SV_ZONE}"
	# UCI only. A file in dnsmasq's conf-dir is deleted when dnsmasq restarts.
	addrs="$(uci -q get dhcp.@dnsmasq[0].address 2>/dev/null || true)"
	for addr in $addrs; do
		case "$addr" in
			*silent.vpn*) uci -q del_list dhcp.@dnsmasq[0].address="$addr" || true ;;
		esac
	done
	uci add_list dhcp.@dnsmasq[0].address="/${host}/${ip}" || return 1
	uci add_list dhcp.@dnsmasq[0].address="/${SV_ZONE}/${ip}" || return 1
	uci -q del_list dhcp.@dnsmasq[0].rebind_domain='silent.vpn' || true
	uci add_list dhcp.@dnsmasq[0].rebind_domain='silent.vpn' || return 1
	uci commit dhcp || return 1
	if [ -x /etc/init.d/dnsmasq ]; then
		/etc/init.d/dnsmasq restart >/dev/null 2>&1 || true
	fi
	sv_log "lan name ${host} -> ${ip}"
}

sv_lan_host_matches() {
	local host
	host="$(echo "$1" | tr 'A-Z' 'a-z' | cut -d: -f1 | sed 's/\.$//')"
	[ "$host" = "$SV_ZONE" ] && return 0
	echo "$host" | grep -q "\.${SV_ZONE}$"
}
