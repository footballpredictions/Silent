# WireGuard path via UCI. AllowedIPs match PC Linux: /1+/1, LAN stays local.

. "$SV_LIB/common.sh"

# spass marks its own sockets so TURN does not fall into the tunnel.
SV_BYPASS_MARK="0x53494c"
SV_BYPASS_TABLE="5458252"

sv_path_clear() {
	ip route del 0.0.0.0/1 dev "$SV_WG_IF" 2>/dev/null || true
	ip route del 128.0.0.0/1 dev "$SV_WG_IF" 2>/dev/null || true
	ip rule del fwmark "$SV_BYPASS_MARK" lookup "$SV_BYPASS_TABLE" 2>/dev/null || true
	ip route flush table "$SV_BYPASS_TABLE" 2>/dev/null || true
	ip link del dev "$SV_WG_IF" 2>/dev/null || true
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
Endpoint = 127.0.0.1:9000
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
	case "$addr" in
		""|*/*) ;;
		*) addr="${addr}/32" ;;
	esac

	uci -q delete network."$SV_WG_IF"
	uci set network."$SV_WG_IF"=interface
	uci set network."$SV_WG_IF".proto='wireguard'
	uci set network."$SV_WG_IF".private_key="$priv"
	uci add_list network."$SV_WG_IF".addresses="$addr"
	uci set network."$SV_WG_IF".mtu='1280'

	uci -q delete network."${SV_WG_IF}_peer"
	uci set network."${SV_WG_IF}_peer"=wireguard_"$SV_WG_IF"
	uci set network."${SV_WG_IF}_peer".public_key="$spub"
	# 56000 is the bypass port. WireGuard itself talks only to local spass.
	uci set network."${SV_WG_IF}_peer".endpoint_host='127.0.0.1'
	uci set network."${SV_WG_IF}_peer".endpoint_port='9000'
	uci set network."${SV_WG_IF}_peer".persistent_keepalive='25'
	# Routes are added in sv_path_apply_turn only after a handshake.
	uci set network."${SV_WG_IF}_peer".route_allowed_ips='0'
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
	sv_path_apply_turn
}

sv_path_protect_bypass() {
	local dev gw
	dev="$(sv_ru_wan_dev 2>/dev/null || true)"
	gw="$(sv_ru_wan_gw 2>/dev/null || true)"
	[ -n "$dev" ] || dev="$(ip route show default | awk '{print $5; exit}')"
	[ -n "$gw" ] || gw="$(ip route show default | awk '{print $3; exit}')"
	[ -n "$dev" ] || return 0
	ip route flush table "$SV_BYPASS_TABLE" 2>/dev/null || true
	ip route replace "$gw/32" dev "$dev" table "$SV_BYPASS_TABLE" 2>/dev/null || true
	if [ -n "$gw" ]; then
		ip route replace default via "$gw" dev "$dev" table "$SV_BYPASS_TABLE" 2>/dev/null || true
	else
		ip route replace default dev "$dev" table "$SV_BYPASS_TABLE" 2>/dev/null || true
	fi
	ip rule del fwmark "$SV_BYPASS_MARK" lookup "$SV_BYPASS_TABLE" 2>/dev/null || true
	ip rule add fwmark "$SV_BYPASS_MARK" lookup "$SV_BYPASS_TABLE" pref 50 2>/dev/null || true
}

sv_path_apply_turn() {
	local src addr hs i
	src="/etc/silent-vpn/wg-turn.conf"
	[ -s "$src" ] || { sv_log "no turn conf"; return 1; }
	if [ -x /usr/libexec/ip-full ]; then
		ln -sf /usr/libexec/ip-full /usr/bin/ip
	fi
	umask 077
	awk '
		/^[ \t]*(Address|DNS|MTU)[ \t]*=/ { next }
		/^[ \t]*Endpoint[ \t]*=/ { print "Endpoint = 127.0.0.1:9000"; next }
		{ print }
	' "$src" > /tmp/sv-wg.conf
	chmod 600 /tmp/sv-wg.conf
	ip link show "$SV_WG_IF" >/dev/null 2>&1 || ip link add dev "$SV_WG_IF" type wireguard || {
		rm -f /tmp/sv-wg.conf
		sv_log "no device $SV_WG_IF"
		return 1
	}
	wg syncconf "$SV_WG_IF" /tmp/sv-wg.conf || {
		rm -f /tmp/sv-wg.conf
		sv_log "syncconf failed"
		return 1
	}
	rm -f /tmp/sv-wg.conf
	addr="$(awk '/^[ \t]*Address[ \t]*=/ { print $NF; exit }' "$src")"
	case "$addr" in
		""|*/*) ;;
		*) addr="${addr}/32" ;;
	esac
	ip addr flush dev "$SV_WG_IF"
	[ -n "$addr" ] && ip addr add "$addr" dev "$SV_WG_IF"
	ip link set "$SV_WG_IF" up
	/etc/init.d/firewall reload >/dev/null 2>&1 || true
	i=0
	hs=0
	while [ "$i" -lt 15 ]; do
		hs="$(wg show "$SV_WG_IF" latest-handshakes 2>/dev/null | awk '{print $2}')"
		[ -n "$hs" ] && [ "$hs" != "0" ] && break
		i=$((i + 1))
		sleep 1
	done
	if [ -z "$hs" ] || [ "$hs" = "0" ]; then
		sv_log "no handshake"
		return 1
	fi
	sv_path_protect_bypass
	ip route replace 0.0.0.0/1 dev "$SV_WG_IF"
	ip route replace 128.0.0.0/1 dev "$SV_WG_IF"
	touch "$SV_RUN/path.up"
	sv_log "path up hs=$hs"
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
