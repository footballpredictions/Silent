# RU services via WAN (router analogue of app exclusions).
# DNS → nft set sv_ru → fwmark → table 162 (WAN). Rest stays in WG.

. "$SV_LIB/common.sh"
. "$SV_LIB/catalog-dns.sh"

SV_RU_LIST="${SV_RU_LIST:-$SV_LIB/ru-direct.domains}"
SV_RU_VPN_LIST="${SV_RU_VPN_LIST:-$SV_LIB/ru-vpn.domains}"
SV_RU_DNS="/tmp/dnsmasq.d/silent-ru.conf"
SV_RU_NFT="${SV_RU_NFT:-/etc/nftables.d/90-silent-ru.nft}"
SV_RU_TABLE="${SV_RU_TABLE:-162}"
SV_RU_MARK="${SV_RU_MARK:-0x162}"
SV_RU_PRIO="${SV_RU_PRIO:-162}"

sv_ru_enabled() {
	[ "$(uci -q get silent-vpn.main.ru_direct 2>/dev/null)" = "1" ]
}

sv_ru_wan_route() {
	local routes
	# netifd's interface named "wan" can be down while a modem/WWAN is online.
	# Our tunnel never changes main's default. Take device and gateway from the
	# same live default route, so a reconnect cannot mix two different uplinks.
	routes="$(ip -4 route show table main default 2>/dev/null)" || return 1
	printf '%s\n' "$routes" | awk -v tunnel="$SV_WG_IF" '
		$1 == "default" {
			dev = ""; gw = "-"; metric = 0; bad = 0
			for (i = 2; i <= NF; i++) {
				if ($i == "dev") dev = $(i + 1)
				if ($i == "via") gw = $(i + 1)
				if ($i == "metric") metric = $(i + 1) + 0
				if ($i == "linkdown" || $i == "dead" || $i == "nexthop") bad = 1
			}
			if (bad || dev == "" || dev == "lo" || dev == tunnel) next
			if (!found || metric < best) {
				found = 1; best = metric; result = dev " " gw
			}
		}
		END { if (found) print result; else exit 1 }
	'
}

sv_ru_wan_dev() {
	local route
	route="$(sv_ru_wan_route)" || return 1
	printf '%s\n' "${route%% *}"
}

sv_ru_wan_gw() {
	local route gw
	route="$(sv_ru_wan_route)" || return 1
	gw="${route#* }"
	[ "$gw" = - ] || [ "$gw" = 0.0.0.0 ] || printf '%s\n' "$gw"
}

sv_ru_clear_policy() {
	ip rule del fwmark "$SV_RU_MARK" lookup "$SV_RU_TABLE" 2>/dev/null || true
	ip route flush table "$SV_RU_TABLE" 2>/dev/null || true
	nft flush set inet fw4 sv_ru 2>/dev/null || true
	nft flush set inet fw4 sv_ru_vpn 2>/dev/null || true
	nft flush chain inet fw4 silent_ru_mark 2>/dev/null || true
	nft flush chain inet fw4 silent_ru_out 2>/dev/null || true
	rm -f "$SV_RU_NFT"
}

sv_ru_ensure_nft() {
	local current legacy=0 ips="" txn snapshot
	current="$(nft list set inet fw4 sv_ru 2>/dev/null)" || current=""
	# Browser DNS caches and open connections can outlive a set timeout.
	# Keep learned addresses until bypass is disabled, not for a fixed hour.
	case "$current" in *timeout*) legacy=1 ;; esac
	[ -n "$current" ] || \
		nft add set inet fw4 sv_ru '{ type ipv4_addr; }' || return 1
	nft list set inet fw4 sv_ru_vpn >/dev/null 2>&1 || \
		nft add set inet fw4 sv_ru_vpn '{ type ipv4_addr; }' || return 1
	nft list chain inet fw4 silent_ru_mark >/dev/null 2>&1 || \
		nft add chain inet fw4 silent_ru_mark '{ type filter hook prerouting priority -150; policy accept; }' || return 1
	nft list chain inet fw4 silent_ru_out >/dev/null 2>&1 || \
		nft add chain inet fw4 silent_ru_out '{ type route hook output priority -150; policy accept; }' || return 1
	mkdir -p "$SV_RUN" || return 1
	txn="$SV_RUN/ru-policy.nft"
	snapshot="$SV_RUN/ru-set.json"
	if [ "$legacy" = 1 ]; then
		nft -j list set inet fw4 sv_ru > "$snapshot" || return 1
		if grep -q '"elem"' "$snapshot"; then
			ips="$(jsonfilter -i "$snapshot" -e '@.nftables[*].set.elem[*].elem.val')" || { rm -f "$snapshot"; return 1; }
			ips="$(printf '%s' "$ips" | tr '\n' ',')"
		fi
		rm -f "$snapshot"
	fi
	# A single kernel transaction preserves routes and learned IPs during migration.
	{
		echo 'flush chain inet fw4 silent_ru_mark'
		echo 'flush chain inet fw4 silent_ru_out'
		if [ "$legacy" = 1 ]; then
			echo 'delete set inet fw4 sv_ru'
			echo 'add set inet fw4 sv_ru { type ipv4_addr; }'
			[ -z "$ips" ] || echo "add element inet fw4 sv_ru { $ips }"
		fi
		echo "add rule inet fw4 silent_ru_mark ip daddr @sv_ru ip daddr != @sv_ru_vpn counter meta mark set $SV_RU_MARK"
		echo "add rule inet fw4 silent_ru_out ip daddr @sv_ru ip daddr != @sv_ru_vpn counter meta mark set $SV_RU_MARK"
	} > "$txn"
	if ! nft -f "$txn"; then rm -f "$txn"; return 1; fi
	rm -f "$txn"
	mkdir -p "$(dirname "$SV_RU_NFT")" || return 1
	cat > "$SV_RU_NFT" <<EOF
set sv_ru { type ipv4_addr; }
set sv_ru_vpn { type ipv4_addr; }
chain silent_ru_mark {
 type filter hook prerouting priority -150; policy accept;
 ip daddr @sv_ru ip daddr != @sv_ru_vpn counter meta mark set $SV_RU_MARK
}
chain silent_ru_out {
 type route hook output priority -150; policy accept;
 ip daddr @sv_ru ip daddr != @sv_ru_vpn counter meta mark set $SV_RU_MARK
}
EOF
}

sv_ru_ensure_route() {
	local route dev gw
	route="$(sv_ru_wan_route)" || return 1
	dev="${route%% *}"
	gw="${route#* }"
	if [ "$gw" != - ] && [ "$gw" != 0.0.0.0 ]; then
		# The gateway is already reachable through this device in main. Table
		# 162 owns only a default; onlink avoids depending on a copied LAN route.
		ip route replace default via "$gw" dev "$dev" onlink table "$SV_RU_TABLE" 2>/dev/null || return 1
	else
		ip route replace default dev "$dev" table "$SV_RU_TABLE" 2>/dev/null || return 1
	fi
	ip rule show | grep -q "fwmark $SV_RU_MARK lookup $SV_RU_TABLE" || \
		ip rule add fwmark "$SV_RU_MARK" lookup "$SV_RU_TABLE" pref "$SV_RU_PRIO" 2>/dev/null || return 1
}

sv_ru_policy_ready() {
	nft list chain inet fw4 silent_ru_mark 2>/dev/null | grep -q 'ip daddr != @sv_ru_vpn' && \
		nft list chain inet fw4 silent_ru_out 2>/dev/null | grep -q 'ip daddr != @sv_ru_vpn'
}

sv_ru_snapshot_sets() {
	local set tmp
	for set in sv_ru sv_ru_vpn; do
		tmp="$SV_RUN/$set.ips.new"
		nft -j list set inet fw4 "$set" > "$tmp.json" 2>/dev/null || continue
		jsonfilter -i "$tmp.json" -e '@.nftables[*].set.elem[*]' > "$tmp" 2>/dev/null
		rm -f "$tmp.json"
		# Keep old addresses if a firewall reload just emptied the sets.
		cat "$SV_RUN/$set.ips" "$tmp" 2>/dev/null | sort -u > "$tmp.all"
		mv "$tmp.all" "$SV_RUN/$set.ips"
		rm -f "$tmp"
	done
}

sv_ru_restore_sets() {
	local set txn code=0
	txn="$(mktemp "$SV_RUN/ru-restore.XXXXXX")" || return 1
	for set in sv_ru sv_ru_vpn; do
		[ -s "$SV_RUN/$set.ips" ] || continue
		# One parser per set, not a fork/awk process for every cached address.
		awk -F. -v set="$set" '
		NF == 4 {
		 valid=1
		 for(i=1;i<=4;i++) if($i !~ /^[0-9]+$/ || $i+0>255) valid=0
		 if(valid) printf "add element inet fw4 %s { %s }\n",set,$0
		}' "$SV_RUN/$set.ips" >> "$txn"
	done
	[ ! -s "$txn" ] || nft -f "$txn" 2>/dev/null || code=$?
	rm -f "$txn"
	return "$code"
}

sv_ru_lock() {
	local owner
	mkdir -p "$SV_RUN"
	if ! mkdir "$SV_RUN/ru.lock" 2>/dev/null; then
		owner="$(cat "$SV_RUN/ru.lock/pid" 2>/dev/null)"
		case "$owner" in ''|*[!0-9]*|0) return 1 ;; esac
		kill -0 "$owner" 2>/dev/null && return 1
		rm -f "$SV_RUN/ru.lock/pid"
		rmdir "$SV_RUN/ru.lock" 2>/dev/null || return 1
		mkdir "$SV_RUN/ru.lock" 2>/dev/null || return 1
	fi
	echo "$$" > "$SV_RUN/ru.lock/pid"
}

sv_ru_unlock() {
	[ "$(cat "$SV_RUN/ru.lock/pid" 2>/dev/null)" = "$$" ] || return 0
	rm -f "$SV_RUN/ru.lock/pid"
	rmdir "$SV_RUN/ru.lock" 2>/dev/null || true
}

sv_ru_lock_wait() {
	local attempt=0
	while ! sv_ru_lock; do
		[ "$attempt" -lt 10 ] || return 1
		attempt=$((attempt + 1))
		sleep 1
	done
}

sv_ru_firewall_restart() {
	/etc/init.d/firewall reload >/dev/null 2>&1
}

sv_ru_firewall_reload() {
	local code=0
	sv_ru_lock_wait || return 1
	# fw4 recreates our included sets empty. Save the latest DNS answers before
	# that happens; phones/browsers can keep using them without another lookup.
	if sv_ru_enabled; then sv_ru_snapshot_sets; fi
	sv_ru_firewall_restart || code=$?
	if sv_ru_enabled; then
		sv_ru_ensure_nft && sv_ru_restore_sets || code=1
	fi
	sv_ru_unlock
	return "$code"
}

sv_ru_maintain() {
	sv_ru_enabled || return 0
	if ! sv_ru_policy_ready; then
		sv_ru_ensure_nft || return 1
	fi
	# Restore addresses even when fw4 recreated the included empty sets/chains.
	sv_ru_restore_sets || return 1
	sv_ru_ensure_route || return 1
	sv_ru_seed_vpn_ips
	sv_ru_snapshot_sets
}

sv_ru_write_dns() {
	local d cr
	if sv_catalog_dns_selected; then
		sv_catalog_dns_bind || return 1
		uci -q delete dhcp.silent_ru || true
		uci -q delete dhcp.silent_ru_vpn || true
		uci commit dhcp
		return
	fi
	sv_catalog_dns_stop || return 1
	# Accept Windows domain lists without copying CR into dnsmasq's UCI rules.
	cr="$(printf '\r')"
	uci -q delete dhcp.silent_ru || true
	uci set dhcp.silent_ru=ipset || return 1
	uci set dhcp.silent_ru.table_family=inet || return 1
	uci set dhcp.silent_ru.table=fw4 || return 1
	uci set dhcp.silent_ru.family=4 || return 1
	uci add_list dhcp.silent_ru.name=sv_ru || return 1
	while read -r d || [ -n "$d" ]; do
		d="${d%"$cr"}"
		case "$d" in ''|\#*) continue ;; esac
		uci add_list "dhcp.silent_ru.domain=$d" || return 1
	done < "$SV_RU_LIST"
	uci -q delete dhcp.silent_ru_vpn || true
	if [ -s "$SV_RU_VPN_LIST" ]; then
		uci set dhcp.silent_ru_vpn=ipset || return 1
		uci set dhcp.silent_ru_vpn.table_family=inet || return 1
		uci set dhcp.silent_ru_vpn.table=fw4 || return 1
		uci set dhcp.silent_ru_vpn.family=4 || return 1
		uci add_list dhcp.silent_ru_vpn.name=sv_ru_vpn || return 1
		while read -r d || [ -n "$d" ]; do
			d="${d%"$cr"}"
			case "$d" in ''|\#*) continue ;; esac
			uci add_list "dhcp.silent_ru_vpn.domain=$d" || return 1
		done < "$SV_RU_VPN_LIST"
	fi
	uci commit dhcp
}

sv_ru_seed_vpn_ips() {
	local d cr ip
	[ -s "$SV_RU_VPN_LIST" ] || return 0
	cr="$(printf '\r')"
	# Seed before DNS restarts, so clients with cached answers also get the exception.
	while read -r d || [ -n "$d" ]; do
		d="${d%"$cr"}"
		case "$d" in ''|\#*) continue ;; esac
		for ip in $(nslookup -type=A "$d" 127.0.0.1 2>/dev/null | awk '
			/^Name:/ { answer = 1 }
			answer && /^Address[^:]*:/ { sub(/^[^:]*:[ \t]*/, ""); print $1 }
		'); do
			sv_is_ipv4 "$ip" || continue
			nft add element inet fw4 sv_ru_vpn "{ $ip }" 2>/dev/null || true
		done
	done < "$SV_RU_VPN_LIST"
}

sv_ru_apply_inner() {
	if ! sv_ru_enabled; then
		sv_catalog_dns_stop || return 1
		rm -f "$SV_RU_DNS"
		uci -q delete dhcp.silent_ru || true
		uci -q delete dhcp.silent_ru_vpn || true
		uci commit dhcp
		sv_ru_clear_policy
		rm -f "$SV_RUN/sv_ru.ips" "$SV_RUN/sv_ru_vpn.ips" "$SV_RUN/policy.applied"
		/etc/init.d/dnsmasq restart >/dev/null 2>&1 || true
		sv_log "ru-direct off"
		return 0
	fi
	if [ -f "$SV_LIB/routing-policy.sh" ]; then
		. "$SV_LIB/routing-policy.sh"
		# The policy daemon refreshes in the background. A reconnect must not wait
		# for every public fallback when a last-good policy is already available.
		if ! { [ -s "$SV_VAR/routing-policy.json" ] && sv_policy_validate "$SV_VAR/routing-policy.json"; }; then
			sv_policy_fetch || true
		fi
		sv_policy_use_cache || return 1
	fi
	dnsmasq --version 2>/dev/null | grep -q ' nftset ' || { sv_log "ru-direct needs dnsmasq-full with nftset"; return 1; }
	sv_ru_ensure_nft || return 1
	sv_ru_ensure_route || return 1
	sv_ru_write_dns || return 1
	sv_ru_restore_sets || return 1
	sv_ru_seed_vpn_ips
	sv_ru_snapshot_sets
	/etc/init.d/dnsmasq restart >/dev/null 2>&1 || return 1
	if [ -s "$SV_VAR/routing-policy.json" ]; then
		jsonfilter -i "$SV_VAR/routing-policy.json" -e '@.revision' > "$SV_RUN/policy.applied"
	fi
	sv_log "ru-direct on table=$SV_RU_TABLE mark=$SV_RU_MARK"
}

sv_ru_apply() {
	local code
	sv_ru_lock_wait || return 1
	sv_ru_apply_inner
	code=$?
	sv_ru_unlock
	return "$code"
}

sv_ru_refresh() {
	local now last revision applied
	sv_ru_enabled || return 0
	. "$SV_LIB/routing-policy.sh"
	now="$(date +%s)"
	last="$(cat "$SV_RUN/policy.fetched" 2>/dev/null)"
	case "$last" in ''|*[!0-9]*) last=0 ;; esac
	if [ "$((now - last))" -ge 300 ]; then
		sv_policy_fetch || true
		echo "$now" > "$SV_RUN/policy.fetched"
	fi
	# Network failover must not hold the writer lock needed by a reconnect.
	sv_ru_lock || return 0
	if ! sv_ru_enabled; then sv_ru_unlock; return 0; fi
	sv_policy_use_cache
	revision="$(jsonfilter -i "$SV_VAR/routing-policy.json" -e '@.revision' 2>/dev/null)"
	applied="$(cat "$SV_RUN/policy.applied" 2>/dev/null)"
	if [ -n "$revision" ] && [ "$revision" != "$applied" ]; then
		# Rebuild only when admin changed the list. No periodic DNS/service restart.
		if sv_ru_ensure_nft && sv_ru_write_dns; then
			nft flush set inet fw4 sv_ru 2>/dev/null || true
			nft flush set inet fw4 sv_ru_vpn 2>/dev/null || true
			rm -f "$SV_RUN/sv_ru.ips" "$SV_RUN/sv_ru_vpn.ips"
			sv_ru_seed_vpn_ips
			if /etc/init.d/dnsmasq restart >/dev/null 2>&1; then
				echo "$revision" > "$SV_RUN/policy.applied"
			fi
		fi
	fi
	sv_ru_maintain
	sv_ru_unlock
}

sv_ru_set() {
	local on="$1" previous code=0
	case "$on" in 0|1) ;; *) return 1 ;; esac
	sv_ru_lock || return 1
	previous="$(uci -q get silent-vpn.main.ru_direct 2>/dev/null)"
	case "$previous" in 0|1) ;; *) previous=0 ;; esac
	uci -q set silent-vpn.main.ru_direct="$on" && \
		uci -q commit silent-vpn && sv_ru_apply_inner || code=$?
	if [ "$code" != 0 ]; then
		uci -q set silent-vpn.main.ru_direct="$previous"
		uci -q commit silent-vpn
		sv_ru_apply_inner >/dev/null 2>&1 || true
	fi
	sv_ru_unlock
	return "$code"
}
