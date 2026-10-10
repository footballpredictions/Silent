# RU services via WAN (router analogue of app exclusions).
# DNS → nft set sv_ru → fwmark → table 162 (WAN). Rest stays in WG.

. "$SV_LIB/common.sh"

SV_RU_LIST="${SV_RU_LIST:-$SV_LIB/ru-direct.domains}"
SV_RU_DNS="/tmp/dnsmasq.d/silent-ru.conf"
SV_RU_NFT="${SV_RU_NFT:-/etc/nftables.d/90-silent-ru.nft}"
SV_RU_TABLE="${SV_RU_TABLE:-162}"
SV_RU_MARK="${SV_RU_MARK:-0x162}"
SV_RU_PRIO="${SV_RU_PRIO:-162}"

sv_ru_enabled() {
	[ "$(uci -q get silent-vpn.main.ru_direct 2>/dev/null)" = "1" ]
}

sv_ru_wan_dev() {
	local d
	d="$(ifstatus wan 2>/dev/null | jsonfilter -e '@.l3_device' 2>/dev/null || true)"
	[ -n "$d" ] || d="$(ifstatus wan 2>/dev/null | jsonfilter -e '@.device' 2>/dev/null || true)"
	[ -n "$d" ] || d="$(uci -q get network.wan.device 2>/dev/null || true)"
	[ -n "$d" ] || d="$(uci -q get network.wan.ifname 2>/dev/null || true)"
	[ -n "$d" ] && echo "$d"
}

sv_ru_wan_gw() {
	local g
	g="$(ifstatus wan 2>/dev/null | jsonfilter -e '@.route[0].nexthop' 2>/dev/null || true)"
	[ -n "$g" ] || g="$(ifstatus wan 2>/dev/null | jsonfilter -e '@.inactive.route[0].nexthop' 2>/dev/null || true)"
	[ -n "$g" ] || g="$(uci -q get network.wan.gateway 2>/dev/null || true)"
	[ -n "$g" ] && echo "$g"
}

sv_ru_clear_policy() {
	ip rule del fwmark "$SV_RU_MARK" lookup "$SV_RU_TABLE" 2>/dev/null || true
	ip route flush table "$SV_RU_TABLE" 2>/dev/null || true
	nft flush set inet fw4 sv_ru 2>/dev/null || true
	nft flush chain inet fw4 silent_ru_mark 2>/dev/null || true
	nft flush chain inet fw4 silent_ru_out 2>/dev/null || true
	rm -f "$SV_RU_NFT"
}

sv_ru_ensure_nft() {
	nft list set inet fw4 sv_ru >/dev/null 2>&1 || \
		nft add set inet fw4 sv_ru '{ type ipv4_addr; flags timeout; timeout 1h; }' 2>/dev/null || \
		nft add set inet fw4 sv_ru '{ type ipv4_addr; }' 2>/dev/null || true
	nft list chain inet fw4 silent_ru_mark >/dev/null 2>&1 || \
		nft add chain inet fw4 silent_ru_mark '{ type filter hook prerouting priority -150; policy accept; }' || return 1
	nft flush chain inet fw4 silent_ru_out 2>/dev/null || true
	nft delete chain inet fw4 silent_ru_out 2>/dev/null || true
	nft add chain inet fw4 silent_ru_out '{ type route hook output priority -150; policy accept; }' || return 1
	# fw4 reload can preserve the chain declaration but discard runtime rules.
	nft flush chain inet fw4 silent_ru_mark || return 1
	nft flush chain inet fw4 silent_ru_out || return 1
	nft add rule inet fw4 silent_ru_mark ip daddr @sv_ru counter meta mark set "$SV_RU_MARK" || return 1
	nft add rule inet fw4 silent_ru_out ip daddr @sv_ru counter meta mark set "$SV_RU_MARK" || return 1
	mkdir -p "$(dirname "$SV_RU_NFT")" || return 1
	cat > "$SV_RU_NFT" <<EOF
set sv_ru { type ipv4_addr; flags timeout; timeout 1h; }
chain silent_ru_mark {
 type filter hook prerouting priority -150; policy accept;
 ip daddr @sv_ru counter meta mark set $SV_RU_MARK
}
chain silent_ru_out {
 type route hook output priority -150; policy accept;
 ip daddr @sv_ru counter meta mark set $SV_RU_MARK
}
EOF
}

sv_ru_ensure_route() {
	local dev gw
	dev="$(sv_ru_wan_dev)" || true
	gw="$(sv_ru_wan_gw)" || true
	[ -n "$dev" ] || return 0
	ip route flush table "$SV_RU_TABLE" 2>/dev/null || true
	if [ -n "$gw" ]; then
		ip route replace default via "$gw" dev "$dev" table "$SV_RU_TABLE" 2>/dev/null || true
	else
		ip route replace default dev "$dev" table "$SV_RU_TABLE" 2>/dev/null || true
	fi
	ip rule del fwmark "$SV_RU_MARK" lookup "$SV_RU_TABLE" 2>/dev/null || true
	ip rule add fwmark "$SV_RU_MARK" lookup "$SV_RU_TABLE" pref "$SV_RU_PRIO" 2>/dev/null || true
}

sv_ru_write_dns() {
	local d
	uci -q delete dhcp.silent_ru || true
	uci set dhcp.silent_ru=ipset || return 1
	uci set dhcp.silent_ru.table_family=inet || return 1
	uci set dhcp.silent_ru.table=fw4 || return 1
	uci set dhcp.silent_ru.family=4 || return 1
	uci add_list dhcp.silent_ru.name=sv_ru || return 1
	while read -r d || [ -n "$d" ]; do
		case "$d" in ''|\#*) continue ;; esac
		uci add_list "dhcp.silent_ru.domain=$d" || return 1
	done < "$SV_RU_LIST"
	uci commit dhcp
}

sv_ru_apply() {
	if ! sv_ru_enabled; then
		rm -f "$SV_RU_DNS"
		uci -q delete dhcp.silent_ru || true
		uci commit dhcp
		sv_ru_clear_policy
		/etc/init.d/dnsmasq restart >/dev/null 2>&1 || true
		sv_log "ru-direct off"
		return 0
	fi
	dnsmasq --version 2>/dev/null | grep -q ' nftset ' || { sv_log "ru-direct needs dnsmasq-full with nftset"; return 1; }
	sv_ru_ensure_nft || return 1
	sv_ru_ensure_route || return 1
	sv_ru_write_dns || return 1
	/etc/init.d/dnsmasq restart >/dev/null 2>&1 || return 1
	sv_log "ru-direct on table=$SV_RU_TABLE mark=$SV_RU_MARK"
}

sv_ru_set() {
	local on="$1"
	uci -q set silent-vpn.main.ru_direct="$on"
	uci -q commit silent-vpn
	sv_ru_apply
}
