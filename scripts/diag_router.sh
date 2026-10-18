#!/bin/sh
# Silent VPN — диагностика OpenWrt (Cudy TR3000 / 25.x и др.).
# Только чтение. Секреты (пароль, токен, PrivateKey) в отчёт не пишутся.
# Код VPN / маршруты / файрвол не меняет.

set -u

OUT="${1:-}"
STAMP="$(date '+%Y%m%d-%H%M%S' 2>/dev/null || echo now)"
if [ -z "$OUT" ]; then
	OUT="/tmp/silent-vpn-diag-${STAMP}.txt"
fi

SV_LIB="/usr/lib/silent-vpn"
SV_VAR="/etc/silent-vpn"
SV_RUN="/var/run/silent-vpn"
WG_IF="svpath"

redact() {
	sed \
		-e 's/[Pp]rivate[Kk]ey.*/PrivateKey ***/g' \
		-e 's/[Pp]reshared[Kk]ey.*/PresharedKey ***/g' \
		-e 's/[Bb]earer [^ ]*/Bearer ***/g' \
		-e 's/"access_token":"[^"]*"/"access_token":"***"/g' \
		-e 's/"refresh_token":"[^"]*"/"refresh_token":"***"/g' \
		-e 's/password[=:].*/password ***/g' \
		-e 's/-password [^ ]*/-password ***/g' \
		-e 's/-vk [^ ]*/-vk ***/g'
}

section() {
	printf '\n======== %s ========\n' "$1"
}

have() {
	command -v "$1" >/dev/null 2>&1
}

run() {
	printf '\n--- %s ---\n' "$*"
	# shellcheck disable=SC2086
	eval "$@" 2>&1 | redact || printf '(exit %s)\n' "$?"
}

safe_cat() {
	f="$1"
	printf '\n--- file %s ---\n' "$f"
	if [ -f "$f" ]; then
		# Never dump WG conf / turn conf / token files raw.
		case "$f" in
			*wg*.conf|*wg-turn*|*access_token*|*refresh_token*|*password*)
				printf '(скрыто: секреты)\n'
				ls -la "$f" 2>&1 || true
				;;
			*)
				redact < "$f"
				;;
		esac
	else
		printf '(нет файла)\n'
	fi
}

{
	section "meta"
	echo "stamp=$(date -Iseconds 2>/dev/null || date)"
	echo "out=$OUT"
	echo "uname=$(uname -a 2>/dev/null)"
	echo "openwrt=$(cat /etc/openwrt_release 2>/dev/null | tr '\n' ' ')"
	echo "board=$(cat /tmp/sysinfo/board_name 2>/dev/null || cat /tmp/sysinfo/model 2>/dev/null)"
	echo "model=$(cat /tmp/sysinfo/model 2>/dev/null)"
	echo "uptime=$(cat /proc/uptime 2>/dev/null)"
	run "free -m"
	run "df -h / /overlay /tmp /usr 2>/dev/null || df -h"

	section "silent-vpn package"
	if [ -r "$SV_LIB/VERSION" ]; then
		echo "installed_version=$(cat "$SV_LIB/VERSION")"
	else
		echo "installed_version=(нет $SV_LIB/VERSION)"
	fi
	run "ls -la /usr/sbin/silent-vpn* /usr/lib/silent-vpn 2>/dev/null | head -n 80"
	run "/etc/init.d/silent-vpn enabled; echo enabled_exit=\$?"
	run "/etc/init.d/silent-vpn-policy enabled; echo policy_enabled_exit=\$?"
	run "ls -la $SV_VAR $SV_RUN 2>/dev/null"
	run "ls -la $SV_RUN 2>/dev/null"
	echo "flags: connected=$([ -f $SV_RUN/connected ] && echo yes || echo no) path.up=$([ -f $SV_RUN/path.up ] && echo yes || echo no) lan.prefix=$([ -f $SV_RUN/lan.prefix ] && cat $SV_RUN/lan.prefix || echo no)"

	section "uci silent-vpn (без секретов)"
	if have uci; then
		uci show silent-vpn 2>/dev/null | redact || echo "(uci silent-vpn пуст)"
		echo "ru_direct=$(uci -q get silent-vpn.main.ru_direct 2>/dev/null)"
		echo "dns_preset=$(uci -q get silent-vpn.main.dns_preset 2>/dev/null)"
		echo "preferred_server=$(uci -q get silent-vpn.main.preferred_server 2>/dev/null)"
		echo "kill_switch=$(uci -q get silent-vpn.main.kill_switch 2>/dev/null)"
		echo "route_lan=$(uci -q get silent-vpn.main.route_lan 2>/dev/null)"
		echo "enabled=$(uci -q get silent-vpn.main.enabled 2>/dev/null)"
		echo "app_version=$(uci -q get silent-vpn.main.app_version 2>/dev/null)"
	else
		echo "uci missing"
	fi

	section "processes"
	run "ps w 2>/dev/null | grep -E 'silent|spass|wireguard|dnsmasq|uhttpd' | grep -v grep"
	run "pgrep -a spass 2>/dev/null; pgrep -a silent-vpn 2>/dev/null"

	section "network / wan / lan"
	run "uci -q get network.lan.ipaddr; uci -q get network.lan.device; uci -q get network.wan.device; uci -q get network.wan.proto"
	run "ip -4 addr show"
	run "ip -4 route show"
	run "ip rule show"
	run "ip route show table 201 2>/dev/null || echo 'table 201 empty'"
	run "ip route show table 162 2>/dev/null || echo 'table 162 empty'"
	DEV="$(uci -q get network.lan.device 2>/dev/null || echo br-lan)"
	LAN="$(cat "$SV_RUN/lan.prefix" 2>/dev/null || true)"
	BASE=""
	if [ -n "$LAN" ]; then
		BASE="${LAN%/*}"
		BASE="${BASE%.*}.50"
	fi
	if [ -n "$BASE" ]; then
		run "ip route get 8.8.8.8 from $BASE iif $DEV 2>/dev/null"
		run "ip route get 1.1.1.1 from $BASE iif $DEV 2>/dev/null"
		# Typical RU CDN probe (Yandex) — should be WAN/table162 if ru-direct on
		run "ip route get 77.88.8.8 from $BASE iif $DEV 2>/dev/null"
	fi
	run "ip route get 8.8.8.8 2>/dev/null"
	run "ip route get 10.66.66.1 2>/dev/null"

	section "wireguard / cloak"
	run "ip link show $WG_IF 2>/dev/null || echo 'no $WG_IF'"
	run "ip -4 addr show dev $WG_IF 2>/dev/null"
	if have wg; then
		# Public fields only — no dump of private key.
		run "wg show $WG_IF 2>/dev/null"
		run "wg show $WG_IF latest-handshakes 2>/dev/null"
		run "wg show $WG_IF transfer 2>/dev/null"
		run "wg show $WG_IF endpoints 2>/dev/null"
		run "wg show $WG_IF allowed-ips 2>/dev/null"
	else
		echo "wg tool missing"
	fi
	run "ss -lun 2>/dev/null | grep 9000 || netstat -lun 2>/dev/null | grep 9000 || echo 'no :9000'"
	safe_cat /etc/silent-vpn/wg-turn.conf
	safe_cat /etc/silent-vpn/wg.conf

	section "firewall / nat / ru sets"
	run "uci -q get firewall.@defaults[0].flow_offloading; uci -q get firewall.@defaults[0].flow_offloading_hw"
	run "uci show firewall | grep -E 'svpath|silent|flow_offload|masq' | redact"
	if have nft; then
		run "nft list chain inet fw4 srcnat 2>/dev/null | grep -E 'svpath|silent|masq|snat' || true"
		run "nft list chain inet fw4 forward 2>/dev/null | grep -E 'svpath|silent|br-lan' || true"
		run "nft list chain inet fw4 mangle_forward 2>/dev/null | grep -E 'svpath|silent|mss' || true"
		run "nft list set inet fw4 sv_ru 2>/dev/null | head -n 40"
		run "nft list set inet fw4 sv_ru_vpn 2>/dev/null | head -n 40"
		run "nft list chain inet fw4 silent_ru_mark 2>/dev/null"
		run "nft list chain inet fw4 silent_ru_out 2>/dev/null"
		# Element counts without dumping every IP if huge
		echo "sv_ru_elems=$(nft list set inet fw4 sv_ru 2>/dev/null | grep -c 'elements\|[0-9]\+\.[0-9]' || echo 0)"
		echo "sv_ru_vpn_elems=$(nft list set inet fw4 sv_ru_vpn 2>/dev/null | grep -c 'elements\|[0-9]\+\.[0-9]' || echo 0)"
	else
		echo "nft missing"
	fi
	run "ls -la /usr/share/nftables.d/chain-pre/srcnat /usr/share/nftables.d/chain-pre/forward /usr/share/nftables.d/chain-post/mangle_forward 2>/dev/null"

	section "kernel / sysctl"
	run "cat /proc/sys/net/ipv4/ip_forward"
	run "cat /proc/sys/net/ipv4/conf/all/rp_filter; cat /proc/sys/net/ipv4/conf/default/rp_filter; cat /proc/sys/net/ipv4/conf/$WG_IF/rp_filter 2>/dev/null"
	run "sysctl net.ipv4.conf.all.rp_filter net.ipv4.ip_forward 2>/dev/null"

	section "dns / panel name"
	LANIP="$(uci -q get network.lan.ipaddr 2>/dev/null | cut -d/ -f1)"
	echo "lan_ip=${LANIP:-unknown}"
	run "uci show dhcp | grep -E 'address|rebind|silent|dnsmasq|server|noresolv|resolvfile' | head -n 60"
	run "cat /tmp/resolv.conf.d/resolv.conf.auto 2>/dev/null || cat /tmp/resolv.conf.auto 2>/dev/null || true"
	run "cat /etc/resolv.conf 2>/dev/null || true"
	# BAD_CONFIG on PC often = local name not in dnsmasq / rebind / DNS via tunnel.
	run "nslookup silent.vpn 127.0.0.1 2>/dev/null || true"
	if [ -n "$LANIP" ]; then
		run "nslookup ${LANIP}.silent.vpn 127.0.0.1 2>/dev/null || true"
		run "nslookup ${LANIP}.silent.vpn 2>/dev/null || true"
	fi
	run "nslookup chatgpt.com 127.0.0.1 2>/dev/null || true"
	run "nslookup telegram.org 127.0.0.1 2>/dev/null || true"
	run "nslookup ya.ru 127.0.0.1 2>/dev/null || true"

	section "connectivity probes (через svpath если есть)"
	if ip link show "$WG_IF" >/dev/null 2>&1; then
		run "ping -I $WG_IF -c 2 -W 3 10.66.66.1"
		run "ping -I $WG_IF -c 2 -W 3 1.1.1.1"
	else
		echo "svpath down — ping -I пропущен"
	fi
	run "ping -c 2 -W 3 1.1.1.1"
	run "ping -c 2 -W 3 77.88.8.8"
	# HTTP: Telegram / ChatGPT / Yandex / Google — только код/ошибка
	if have wget; then
		run "wget -qO /dev/null -T 5 -S https://1.1.1.1 2>&1 | head -n 15"
		run "wget -qO /dev/null -T 5 -S https://telegram.org 2>&1 | head -n 15"
		run "wget -qO /dev/null -T 5 -S https://chatgpt.com 2>&1 | head -n 15"
		run "wget -qO /dev/null -T 5 -S https://ya.ru 2>&1 | head -n 15"
		run "wget -qO /dev/null -T 5 -S https://www.google.com 2>&1 | head -n 15"
		if [ -n "$LANIP" ]; then
			run "wget -qO /dev/null -T 3 -S http://${LANIP}/ 2>&1 | head -n 15"
			run "wget -qO /dev/null -T 3 -S http://${LANIP}.silent.vpn/ 2>&1 | head -n 15"
		fi
	fi

	section "ctl status"
	if [ -x /usr/sbin/silent-vpn-ctl ]; then
		run "/usr/sbin/silent-vpn-ctl status"
		run "/usr/sbin/silent-vpn-ctl lan-url"
	else
		echo "silent-vpn-ctl missing"
	fi

	section "policy / routing cache"
	run "ls -la $SV_VAR/policy* $SV_RUN/policy* $SV_VAR/routing* $SV_RUN/*policy* 2>/dev/null"
	safe_cat "$SV_VAR/routing-policy.json"
	safe_cat "$SV_RUN/policy.revision"
	run "logread -e silent 2>/dev/null | tail -n 80 || true"
	run "logread -e spass 2>/dev/null | tail -n 40 || true"
	run "logread -e OOM 2>/dev/null | tail -n 20 || true"
	run "dmesg 2>/dev/null | grep -iE 'oom|out of memory|wireguard|svpath' | tail -n 40 || true"

	section "uhttpd / panel reachability from router"
	run "uci show uhttpd 2>/dev/null | head -n 40"
	run "wget -qO- -T 3 http://127.0.0.1/cgi-bin/silent-api/status 2>&1 | redact | head -n 20"
	if [ -n "$LANIP" ]; then
		run "wget -qO- -T 3 http://${LANIP}/cgi-bin/silent-api/status 2>&1 | redact | head -n 20"
	fi

	section "end"
	echo "ok"
	echo "report=$OUT"
} > "$OUT" 2>&1

# Also print path for the user pasting from SSH.
echo "Готово. Отчёт: $OUT"
echo "Размер: $(wc -c < "$OUT" 2>/dev/null || echo '?') байт"
echo "Скопируйте файл с ПК, например:"
echo "  scp root@IP_РОУТЕРА:$OUT ."
echo "Или выведите в терминал:"
echo "  cat $OUT"
exit 0
