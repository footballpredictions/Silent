# WireGuard path via UCI. AllowedIPs match PC Linux: /1+/1, LAN stays local.

. "$SV_LIB/common.sh"

sv_path_clear() {
	uci -q delete network."$SV_WG_IF"
	uci -q delete network."${SV_WG_IF}_peer"
	uci -q commit network
	ifdown "$SV_WG_IF" >/dev/null 2>&1 || true
	rm -f "$SV_RUN/path.up" "$SV_VAR/wg.conf"
}

sv_path_write_conf() {
	# stdin unused; args from JSON file $1
	local src="$1" priv addr dns sip sport spub allowed
	priv="$(jsonfilter -i "$src" -e '@.wg_private_key')"
	addr="$(jsonfilter -i "$src" -e '@.wg_address')"
	dns="$(jsonfilter -i "$src" -e '@.wg_dns')"
	if [ "$(uci -q get silent-vpn.main.dns_preset 2>/dev/null)" = "custom" ]; then
		custom="$(uci -q get silent-vpn.main.dns_custom 2>/dev/null || true)"
		[ -n "$custom" ] && dns="$custom"
	fi
	sip="$(jsonfilter -i "$src" -e '@.server_ip')"
	sport="$(jsonfilter -i "$src" -e '@.server_port')"
	spub="$(jsonfilter -i "$src" -e '@.server_public_key')"
	[ -n "$priv" ] && [ -n "$spub" ] && [ -n "$sip" ] || return 1
	[ -n "$dns" ] || dns="1.1.1.1,1.0.0.1"
	if [ -f "$SV_RUN/bootstrap" ]; then
		allowed="10.66.66.0/24"
	else
		allowed="0.0.0.0/1,128.0.0.0/1"
	fi
	cat > "$SV_VAR/wg.conf" <<EOF
[Interface]
PrivateKey = $priv
Address = $addr
DNS = $dns

[Peer]
PublicKey = $spub
Endpoint = ${sip}:${sport}
AllowedIPs = $allowed
PersistentKeepalive = 25
EOF
	chmod 600 "$SV_VAR/wg.conf"
}

sv_path_apply_uci() {
	local priv addr dns sip sport spub
	priv="$(jsonfilter -i "$1" -e '@.wg_private_key')"
	addr="$(jsonfilter -i "$1" -e '@.wg_address')"
	dns="$(jsonfilter -i "$1" -e '@.wg_dns')"
	if [ "$(uci -q get silent-vpn.main.dns_preset 2>/dev/null)" = "custom" ]; then
		custom="$(uci -q get silent-vpn.main.dns_custom 2>/dev/null || true)"
		[ -n "$custom" ] && dns="$custom"
	fi
	sip="$(jsonfilter -i "$1" -e '@.server_ip')"
	sport="$(jsonfilter -i "$1" -e '@.server_port')"
	spub="$(jsonfilter -i "$1" -e '@.server_public_key')"

	uci -q delete network."$SV_WG_IF"
	uci set network."$SV_WG_IF"=interface
	uci set network."$SV_WG_IF".proto='wireguard'
	uci set network."$SV_WG_IF".private_key="$priv"
	uci add_list network."$SV_WG_IF".addresses="$addr"
	uci set network."$SV_WG_IF".mtu='1280'

	uci -q delete network."${SV_WG_IF}_peer"
	uci set network."${SV_WG_IF}_peer"=wireguard_"$SV_WG_IF"
	uci set network."${SV_WG_IF}_peer".public_key="$spub"
	uci set network."${SV_WG_IF}_peer".endpoint_host="$sip"
	uci set network."${SV_WG_IF}_peer".endpoint_port="$sport"
	uci set network."${SV_WG_IF}_peer".persistent_keepalive='25'
	uci set network."${SV_WG_IF}_peer".route_allowed_ips='1'
	if [ -f "$SV_RUN/bootstrap" ]; then
		uci add_list network."${SV_WG_IF}_peer".allowed_ips='10.66.66.0/24'
	else
		uci add_list network."${SV_WG_IF}_peer".allowed_ips='0.0.0.0/1'
		uci add_list network."${SV_WG_IF}_peer".allowed_ips='128.0.0.0/1'
	fi

	# Keep LAN + panel reachable if the default route flips.
	uci -q delete network.sv_lan_ok
	uci set network.sv_lan_ok=route
	uci set network.sv_lan_ok.interface='lan'
	uci set network.sv_lan_ok.target="$(sv_lan_ip)"
	uci set network.sv_lan_ok.netmask='255.255.255.255'

	sv_path_ensure_fw
	uci commit network
	uci commit firewall
	ifup "$SV_WG_IF" >/dev/null 2>&1 || /etc/init.d/network reload >/dev/null 2>&1 || true
	touch "$SV_RUN/path.up"
}

sv_path_ensure_fw() {
	if ! uci -q get firewall."$SV_WG_ZONE" >/dev/null; then
		uci set firewall."$SV_WG_ZONE"=zone
		uci set firewall."$SV_WG_ZONE".name="$SV_WG_ZONE"
		uci set firewall."$SV_WG_ZONE".input='REJECT'
		uci set firewall."$SV_WG_ZONE".output='ACCEPT'
		uci set firewall."$SV_WG_ZONE".forward='REJECT'
		uci set firewall."$SV_WG_ZONE".masq='1'
		uci set firewall."$SV_WG_ZONE".mtu_fix='1'
		uci add_list firewall."$SV_WG_ZONE".network="$SV_WG_IF"
	fi
	if ! uci -q get firewall.sv_lan_to_path >/dev/null; then
		uci set firewall.sv_lan_to_path=forwarding
		uci set firewall.sv_lan_to_path.src='lan'
		uci set firewall.sv_lan_to_path.dest="$SV_WG_ZONE"
	fi
}

sv_path_up_from_json() {
	sv_path_write_conf "$1" || return 1
	sv_path_apply_uci "$1"
}

sv_path_is_up() {
	[ -f "$SV_RUN/path.up" ] || return 1
	ip link show "$SV_WG_IF" >/dev/null 2>&1
}
