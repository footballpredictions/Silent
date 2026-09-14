#!/bin/sh
# Remove Silent VPN from OpenWrt: files, WG/UCI, DNS, uhttpd door, packages.
# Self-contained: works even if the agent is already half-deleted.

if [ "$(id -u 2>/dev/null || echo 1)" != 0 ]; then
	echo "Нужен root. В Сервисы → Терминал вы уже root." >&2
	exit 1
fi

echo "Silent VPN — удаление"

if [ -x /usr/sbin/silent-vpn-ctl ]; then
	/usr/sbin/silent-vpn-ctl disconnect >/dev/null 2>&1 || true
fi

if [ -x /etc/init.d/silent-vpn ]; then
	/etc/init.d/silent-vpn stop >/dev/null 2>&1 || true
	/etc/init.d/silent-vpn disable >/dev/null 2>&1 || true
fi

killall spass >/dev/null 2>&1 || true
killall svpass >/dev/null 2>&1 || true
killall svcloak >/dev/null 2>&1 || true
killall wdtt-client >/dev/null 2>&1 || true
ifdown svpath >/dev/null 2>&1 || true

ip rule del fwmark 0x162 lookup 162 2>/dev/null || true
ip rule del fwmark 0x162 lookup 162 2>/dev/null || true
ip route flush table 162 2>/dev/null || true
nft flush chain inet fw4 silent_ru_mark 2>/dev/null || true
nft flush chain inet fw4 silent_ru_out 2>/dev/null || true
nft delete chain inet fw4 silent_ru_mark 2>/dev/null || true
nft delete chain inet fw4 silent_ru_out 2>/dev/null || true
nft delete set inet fw4 sv_ru 2>/dev/null || true

uci -q delete network.svpath
uci -q delete network.svpath_peer
uci -q delete network.sv_lan_ok
uci -q delete firewall.svpath
uci -q delete firewall.sv_lan_to_path
uci -q commit network
uci -q commit firewall

addrs="$(uci -q get dhcp.@dnsmasq[0].address 2>/dev/null || true)"
for addr in $addrs; do
	case "$addr" in
		*silent.vpn*) uci -q del_list dhcp.@dnsmasq[0].address="$addr" ;;
	esac
done
uci -q commit dhcp

idx="$(uci -q get uhttpd.main.index_page 2>/dev/null || true)"
uci -q delete uhttpd.main.index_page
kept=0
for v in $idx; do
	case "$v" in
		*silent-entry*) continue ;;
	esac
	uci add_list uhttpd.main.index_page="$v"
	kept=1
done
if [ "$kept" = 0 ]; then
	uci add_list uhttpd.main.index_page='cgi-bin/luci'
fi
uci -q commit uhttpd

rm -rf /usr/lib/silent-vpn /usr/sbin/silent-vpn-ctl \
	/usr/bin/spass /usr/bin/svpass /usr/bin/svcloak /usr/bin/wdtt-client /www/silent-vpn \
	/www/cgi-bin/silent-entry /www/cgi-bin/silent-api /etc/silent-vpn \
	/etc/init.d/silent-vpn /etc/config/silent-vpn \
	/etc/hotplug.d/iface/99-silent-vpn /etc/uci-defaults/99-silent-vpn \
	/var/run/silent-vpn /tmp/dnsmasq.d/silent-vpn.conf /tmp/dnsmasq.d/silent-ru.conf \
	/var/log/silent-cloak.log

/etc/init.d/firewall reload >/dev/null 2>&1 || true
/etc/init.d/dnsmasq restart >/dev/null 2>&1 || true
/etc/init.d/uhttpd restart >/dev/null 2>&1 || true

if command -v apk >/dev/null 2>&1; then
	apk del kmod-wireguard wireguard-tools ip-full >/dev/null 2>&1 || true
elif command -v opkg >/dev/null 2>&1; then
	opkg remove kmod-wireguard wireguard-tools ip-full >/dev/null 2>&1 || true
fi

echo "Готово. Silent VPN снят."
exec rm -f /tmp/sv-rm.sh /usr/sbin/silent-vpn-uninstall
