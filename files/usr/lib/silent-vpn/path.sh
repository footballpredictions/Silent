# WireGuard path via UCI. AllowedIPs match PC Linux: /1+/1, LAN stays local.

. "$SV_LIB/common.sh"

# LAN clients only. Never install 0.0.0.0/1 on the main table: that blackholes the router itself.
SV_LAN_TABLE="201"

sv_path_ip() {
	if [ -x /usr/libexec/ip-full ]; then
		echo /usr/libexec/ip-full
	else
		echo ip
	fi
}

sv_path_drop_blackhole() {
	local ipb
	ipb="$(sv_path_ip)"
	"$ipb" route del 0.0.0.0/1 dev "$SV_WG_IF" 2>/dev/null || true
	"$ipb" route del 128.0.0.0/1 dev "$SV_WG_IF" 2>/dev/null || true
	"$ipb" route del 10.66.66.1/32 dev "$SV_WG_IF" 2>/dev/null || true
	while "$ipb" rule del lookup "$SV_LAN_TABLE" 2>/dev/null; do :; done
	if [ -s "$SV_RUN/lan.prefix" ]; then
		"$ipb" rule del to "$(cat "$SV_RUN/lan.prefix")" lookup main pref 50 2>/dev/null || true
	fi
	rm -f "$SV_RUN/lan.prefix" "$SV_RUN/path.up"
	"$ipb" route flush table "$SV_LAN_TABLE" 2>/dev/null || true
}

sv_path_clear() {
	sv_path_dns_restore
	sv_path_drop_blackhole
	sv_path_kernel_restore
	sv_path_offload_restore
	sv_path_fw_drop_files
	/etc/init.d/firewall reload >/dev/null 2>&1 || true
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

sv_path_lan_clients() {
	local lan dev ipb
	ipb="$(sv_path_ip)"
	dev="$(uci -q get network.lan.device 2>/dev/null || true)"
	[ -n "$dev" ] || dev="br-lan"
	# Kernel subnet only. A /32 of the router itself must not be the selector:
	# replies from 192.168.1.1 would be pushed into the tunnel and the cable dies.
	lan="$("$ipb" -4 route show dev "$dev" proto kernel 2>/dev/null | awk '/^[0-9]+\./ { print $1; exit }')"
	case "$lan" in
		""|*/32)
			sv_log "lan prefix missing ($lan)"
			return 1
			;;
		*/*) ;;
		*)
			sv_log "lan prefix not a subnet ($lan)"
			return 1
			;;
	esac
	mkdir -p "$SV_RUN"
	printf '%s\n' "$lan" > "$SV_RUN/lan.prefix"
	"$ipb" rule del to "$lan" lookup main pref 50 2>/dev/null || true
	"$ipb" rule add to "$lan" lookup main pref 50 || return 1
	"$ipb" route replace "$lan" dev "$dev" table "$SV_LAN_TABLE" || return 1
	"$ipb" route replace default dev "$SV_WG_IF" scope global table "$SV_LAN_TABLE" || return 1
	# Router-originated API requests do not match iif br-lan. Route just the
	# tunnel gateway in main; WAN/TURN sockets and the LAN panel stay on WAN.
	"$ipb" route replace 10.66.66.1/32 dev "$SV_WG_IF" || return 1
	"$ipb" rule add from "$lan" iif "$dev" lookup "$SV_LAN_TABLE" pref "$SV_LAN_TABLE" || return 1
	sv_log "lan $lan iif $dev -> table $SV_LAN_TABLE"
	sv_log "rule50 $("$ipb" rule show pref 50 2>&1 | tr '\n' '; ')"
	sv_log "rule201 $("$ipb" rule show pref "$SV_LAN_TABLE" 2>&1 | tr '\n' '; ')"
	sv_log "t201 $("$ipb" route show table "$SV_LAN_TABLE" 2>&1 | tr '\n' '; ')"
}

sv_path_wait_gateway() {
	local attempt=1 pong
	# A WG handshake can precede stable DTLS data workers. One lost packet
	# must not tear down a working session; keep the readiness gate bounded.
	while [ "$attempt" -le 5 ]; do
		if pong="$(ping -I "$SV_WG_IF" -c 1 -W 3 10.66.66.1 2>&1)"; then
			sv_log "ping ok attempt=$attempt: $(printf '%s' "$pong" | tr '\n' ' ')"
			return 0
		fi
		sv_log "gateway not ready attempt=$attempt: $(printf '%s' "$pong" | tr '\n' ' ')"
		[ "$attempt" -lt 5 ] && sleep 1
		attempt=$((attempt + 1))
	done
	sv_log "gateway unavailable after 5 attempts"
	return 1
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
	sv_log "addr ${addr:-none}"
	ip link set dev "$SV_WG_IF" mtu 1280
	ip link set "$SV_WG_IF" up
	sysctl -w net.ipv4.conf."$SV_WG_IF".rp_filter=2 >/dev/null 2>&1 || true
	sv_path_ensure_fw
	uci commit firewall
	i=0
	hs=0
	while [ "$i" -lt 15 ]; do
		hs="$(wg show "$SV_WG_IF" latest-handshakes 2>/dev/null | awk '{print $2}')"
		[ -n "$hs" ] && [ "$hs" != "0" ] && break
		i=$((i + 1))
		sleep 1
	done
	sv_log "handshake ${hs:-0} after ${i}s"
	sv_log "xfer $(wg show "$SV_WG_IF" transfer 2>&1 | tr '\n' ' ')"
	if [ -z "$hs" ] || [ "$hs" = "0" ]; then
		sv_log "no handshake"
		return 1
	fi
	sv_path_wait_gateway || return 1
	sv_path_fw_pass || return 1
	sv_path_kernel_fix || return 1
	sv_path_drop_blackhole
	sv_path_lan_clients || { sv_path_drop_blackhole; return 1; }
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
	fi
	# The link is created with ip, not netifd. fw4 only NATs a device it can see.
	uci set firewall."$SV_WG_ZONE".masq='1'
	uci set firewall."$SV_WG_ZONE".mtu_fix='1'
	uci -q del_list firewall."$SV_WG_ZONE".device="$SV_WG_IF"
	uci add_list firewall."$SV_WG_ZONE".device="$SV_WG_IF"
	uci -q del_list firewall."$SV_WG_ZONE".network="$SV_WG_IF"
	uci add_list firewall."$SV_WG_ZONE".network="$SV_WG_IF"
	if ! uci -q get firewall.sv_lan_to_path >/dev/null; then
		uci set firewall.sv_lan_to_path=forwarding
		uci set firewall.sv_lan_to_path.src='lan'
		uci set firewall.sv_lan_to_path.dest="$SV_WG_ZONE"
	fi
}

sv_path_fw_drop_files() {
	rm -f /usr/share/nftables.d/chain-pre/srcnat/01-silent-masq.nft \
		/usr/share/nftables.d/chain-pre/forward/01-silent-fwd.nft \
		/usr/share/nftables.d/chain-post/mangle_forward/01-silent-mss.nft
}

sv_path_fw_write() {
	local dev dir snat
	dev="$(uci -q get network.lan.device 2>/dev/null || true)"
	[ -n "$dev" ] || dev="br-lan"
	snat="$(ip -4 -o addr show dev "$SV_WG_IF" 2>/dev/null | awk '{print $4; exit}')"
	snat="${snat%%/*}"
	dir="/usr/share/nftables.d/chain-pre"
	mkdir -p "$dir/srcnat" "$dir/forward" /usr/share/nftables.d/chain-post/mangle_forward || return 1
	if [ -n "$snat" ]; then
		printf '%s\n' "oifname \"$SV_WG_IF\" snat ip to $snat comment \"silent-vpn\"" > "$dir/srcnat/01-silent-masq.nft"
	else
		printf '%s\n' "oifname \"$SV_WG_IF\" masquerade comment \"silent-vpn\"" > "$dir/srcnat/01-silent-masq.nft"
	fi
	# Accept both ways. A reply that conntrack calls invalid never matches
	# "established", and fw4 then drops it after the bytes already hit svpath.
	# UDP/443 is HTTP/3: it does not fit the tunnel MTU, so the browser must use TCP.
	printf '%s\n%s\n%s\n' \
		"iifname \"$dev\" oifname \"$SV_WG_IF\" udp dport 443 reject comment \"silent-vpn-quic\"" \
		"iifname \"$dev\" oifname \"$SV_WG_IF\" counter accept comment \"silent-vpn\"" \
		"iifname \"$SV_WG_IF\" oifname \"$dev\" counter accept comment \"silent-vpn\"" \
		> "$dir/forward/01-silent-fwd.nft"
	printf '%s\n' "oifname \"$SV_WG_IF\" tcp flags syn tcp option maxseg size set 1160 comment \"silent-vpn-mss\"" \
		> /usr/share/nftables.d/chain-post/mangle_forward/01-silent-mss.nft
	sv_log "fw files lan=$dev snat=${snat:-masq}"
}

sv_path_fw_seen() {
	local dev forward
	dev="$(uci -q get network.lan.device 2>/dev/null || true)"
	[ -n "$dev" ] || dev="br-lan"
	nft list chain inet fw4 srcnat 2>/dev/null | grep -F "oifname \"$SV_WG_IF\"" | grep -e masquerade -e snat >/dev/null || return 1
	forward="$(nft list chain inet fw4 forward 2>/dev/null)" || return 1
	printf '%s\n' "$forward" | grep -F "iifname \"$dev\" oifname \"$SV_WG_IF\"" | grep -q accept || return 1
	printf '%s\n' "$forward" | grep -F "iifname \"$SV_WG_IF\" oifname \"$dev\"" | grep -q accept
}

sv_path_offload_off() {
	local sw hw
	sw="$(uci -q get firewall.@defaults[0].flow_offloading 2>/dev/null || echo 0)"
	hw="$(uci -q get firewall.@defaults[0].flow_offloading_hw 2>/dev/null || echo 0)"
	mkdir -p "$SV_RUN"
	if [ ! -f "$SV_RUN/flow.off" ]; then
		printf '%s\n%s\n' "$sw" "$hw" > "$SV_RUN/flow.off"
		sv_log "flow offload sw=$sw hw=$hw -> off"
	fi
	uci set firewall.@defaults[0].flow_offloading='0'
	uci set firewall.@defaults[0].flow_offloading_hw='0'
	uci commit firewall
}

sv_path_offload_restore() {
	local sw hw
	[ -f "$SV_RUN/flow.off" ] || return 0
	sw="$(sed -n '1p' "$SV_RUN/flow.off")"
	hw="$(sed -n '2p' "$SV_RUN/flow.off")"
	[ -n "$sw" ] || sw=0
	[ -n "$hw" ] || hw=0
	uci set firewall.@defaults[0].flow_offloading="$sw"
	uci set firewall.@defaults[0].flow_offloading_hw="$hw"
	uci commit firewall
	rm -f "$SV_RUN/flow.off"
	sv_log "flow offload restored sw=$sw hw=$hw"
}

sv_path_kernel_save() {
	local key file value
	[ -f "$SV_RUN/kernel.before" ] && return 0
	mkdir -p "$SV_RUN" || return 1
	: > "$SV_RUN/kernel.before" || return 1
	for key in net.ipv4.ip_forward net.ipv4.conf.all.rp_filter net.ipv4.conf.default.rp_filter; do
		file="${SV_PROC_SYS:-/proc/sys}/$(printf '%s' "$key" | tr . /)"
		value="$(cat "$file" 2>/dev/null)" || { rm -f "$SV_RUN/kernel.before"; return 1; }
		printf '%s=%s\n' "$key" "$value" >> "$SV_RUN/kernel.before"
	done
}

sv_path_kernel_restore() {
	local setting
	[ -f "$SV_RUN/kernel.before" ] || return 0
	while read -r setting; do
		sysctl -w "$setting" >/dev/null 2>&1 || sv_log "kernel restore failed: ${setting%%=*}"
	done < "$SV_RUN/kernel.before"
	rm -f "$SV_RUN/kernel.before"
}

sv_path_kernel_fix() {
	local err ipng
	sv_path_kernel_save || { sv_log "kernel snapshot failed"; return 1; }
	sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || sv_log "ip_forward set failed"
	sysctl -w net.ipv4.conf.all.rp_filter=2 >/dev/null 2>&1 || true
	sysctl -w net.ipv4.conf.default.rp_filter=2 >/dev/null 2>&1 || true
	sysctl -w net.ipv4.conf."$SV_WG_IF".rp_filter=2 >/dev/null 2>&1 || true
	nft flush flowtable inet fw4 ft >/dev/null 2>&1 || true
	err="$(nft insert rule inet fw4 mangle_forward oifname "$SV_WG_IF" tcp flags syn tcp option maxseg size set 1200 2>&1)" || sv_log "mss: ${err:-no mangle_forward}"
	sv_log "forward=$(cat /proc/sys/net/ipv4/ip_forward 2>/dev/null) rp_all=$(cat /proc/sys/net/ipv4/conf/all/rp_filter 2>/dev/null) rp_if=$(cat /proc/sys/net/ipv4/conf/$SV_WG_IF/rp_filter 2>/dev/null)"
	sv_log "addr $(ip -4 addr show dev "$SV_WG_IF" 2>&1 | sed -n 's/^ *inet /inet /p' | tr '\n' ' ')"
	ipng="$(ping -I "$SV_WG_IF" -c 1 -W 4 1.1.1.1 2>&1)" || {
		sv_log "inet ping fail: $(printf '%s' "$ipng" | tr '\n' ' ')"
		return 0
	}
	sv_log "inet ping ok: $(printf '%s' "$ipng" | tr '\n' ' ')"
}

sv_status_dump() {
	local lan base dev
	echo "----- сейчас -----"
	echo "forward=$(cat /proc/sys/net/ipv4/ip_forward 2>/dev/null) rp_all=$(cat /proc/sys/net/ipv4/conf/all/rp_filter 2>/dev/null) rp_sv=$(cat /proc/sys/net/ipv4/conf/svpath/rp_filter 2>/dev/null)"
	echo "flow_sw=$(uci -q get firewall.@defaults[0].flow_offloading 2>/dev/null) flow_hw=$(uci -q get firewall.@defaults[0].flow_offloading_hw 2>/dev/null)"
	ip -4 addr show dev svpath 2>&1 | sed -n 's/^ *inet /addr /p'
	echo "t201: $(ip route show table 201 2>&1 | tr '\n' '; ')"
	echo "rules: $(ip rule show 2>&1 | tr '\n' '; ')"
	lan="$(cat "$SV_RUN/lan.prefix" 2>/dev/null || true)"
	dev="$(uci -q get network.lan.device 2>/dev/null || echo br-lan)"
	base="${lan%/*}"
	base="${base%.*}.50"
	if [ -n "$lan" ] && [ -n "$base" ]; then
		echo "routeget: $(ip route get 8.8.8.8 from "$base" iif "$dev" 2>&1 | tr '\n' ' ')"
	fi
	echo "wg: $(wg show svpath 2>&1 | grep -E 'handshake|transfer|endpoint|allowed' | tr '\n' '; ')"
	echo "srcnat: $(nft list chain inet fw4 srcnat 2>/dev/null | grep svpath | tr '\n' '; ')"
	echo "fwd: $(nft list chain inet fw4 forward 2>/dev/null | grep svpath | tr '\n' '; ')"
}

sv_path_fw_pass() {
	local err dev
	dev="$(uci -q get network.lan.device 2>/dev/null || true)"
	[ -n "$dev" ] || dev="br-lan"
	sv_path_offload_off
	sv_path_fw_write || sv_log "fw files not written"
	if /etc/init.d/firewall reload >/dev/null 2>&1; then
		sv_log "firewall reload ok"
	else
		sv_log "firewall reload failed"
		sv_path_fw_drop_files
		/etc/init.d/firewall reload >/dev/null 2>&1 || sv_log "firewall restore failed"
	fi
	if sv_path_fw_seen; then
		sv_log "nat: ok"
		return 0
	fi
	err="$(nft insert rule inet fw4 srcnat oifname "$SV_WG_IF" masquerade comment \"silent-vpn\" 2>&1)" || sv_log "nft srcnat: ${err:-fail}"
	err="$(nft insert rule inet fw4 forward iifname "$dev" oifname "$SV_WG_IF" counter accept comment \"silent-vpn\" 2>&1)" || sv_log "nft forward out: ${err:-fail}"
	err="$(nft insert rule inet fw4 forward iifname "$SV_WG_IF" oifname "$dev" counter accept comment \"silent-vpn\" 2>&1)" || sv_log "nft forward back: ${err:-fail}"
	# insert prepends: put reject last so it precedes the outbound accept.
	err="$(nft insert rule inet fw4 forward iifname "$dev" oifname "$SV_WG_IF" udp dport 443 reject comment \"silent-vpn-quic\" 2>&1)" || sv_log "nft quic: ${err:-fail}"
	if sv_path_fw_seen; then
		sv_log "nat: ok via insert"
		return 0
	fi
	sv_log "nat: FAILED"
	nft list chain inet fw4 srcnat 2>&1 | head -n 15 | while read -r line; do
		sv_log "srcnat $line"
	done
	nft list chain inet fw4 forward 2>&1 | head -n 15 | while read -r line; do
		sv_log "fwd $line"
	done
	return 1
}

sv_path_up_from_json() {
	sv_path_write_conf "$1" || return 1
	sv_path_apply_uci "$1" || return 1
	sv_path_dns_apply "$1"
}

# dnsmasq queries originate on the router and do not match the LAN iif rule.
# Keep upstream DNS in the VPN table without moving WAN/TURN sockets.
sv_path_dns_restart() {
	/etc/init.d/dnsmasq restart >/dev/null 2>&1
}

sv_path_dns_restore() {
	local option value ipb
	[ -d "$SV_VAR/dns.before" ] || return 0
	ipb="$(sv_path_ip)"
	for option in server noresolv; do
		uci -q delete "dhcp.@dnsmasq[0].$option" || true
		if [ -f "$SV_VAR/dns.before/$option" ]; then
			value="$(cat "$SV_VAR/dns.before/$option")"
			if [ "$option" = server ]; then
				for value in $value; do
					uci add_list "dhcp.@dnsmasq[0].server=$value" || return 1
				done
			else
				uci set "dhcp.@dnsmasq[0].$option=$value" || return 1
			fi
		fi
	done
	uci commit dhcp || return 1
	sv_path_dns_restart || return 1
	while "$ipb" rule del pref 202 lookup "$SV_LAN_TABLE" 2>/dev/null; do :; done
	rm -rf "$SV_VAR/dns.before"
	sv_log "dns restored"
}

sv_path_dns_apply() {
	local dns server option ipb
	dns="$(jsonfilter -i "$1" -e '@.wg_dns')"
	if [ "$(uci -q get silent-vpn.main.dns_preset 2>/dev/null)" = custom ]; then
		dns="$(uci -q get silent-vpn.main.dns_custom 2>/dev/null)"
	fi
	[ -n "$dns" ] || dns='1.1.1.1,1.0.0.1'
	dns="$(printf '%s' "$dns" | tr ',' ' ')"
	for server in $dns; do
		sv_is_ipv4 "$server" || { sv_log "dns must be IPv4: $server"; return 1; }
	done
	if [ ! -d "$SV_VAR/dns.before" ]; then
		mkdir -p "$SV_VAR/dns.before" || return 1
		for option in server noresolv; do
			uci -q get "dhcp.@dnsmasq[0].$option" > "$SV_VAR/dns.before/$option" 2>/dev/null || rm -f "$SV_VAR/dns.before/$option"
		done
	fi
	ipb="$(sv_path_ip)"
	while "$ipb" rule del pref 202 lookup "$SV_LAN_TABLE" 2>/dev/null; do :; done
	uci -q delete dhcp.@dnsmasq[0].server || true
	uci set dhcp.@dnsmasq[0].noresolv=1 || return 1
	for server in $dns; do
		"$ipb" rule add to "$server/32" lookup "$SV_LAN_TABLE" pref 202 || return 1
		uci add_list "dhcp.@dnsmasq[0].server=$server" || return 1
	done
	uci commit dhcp || return 1
	sv_path_dns_restart || return 1
	sv_log "dns via tunnel: $dns"
}

sv_path_is_up() {
	[ -f "$SV_RUN/path.up" ] || return 1
	ip link show "$SV_WG_IF" >/dev/null 2>&1
}
