#!/bin/sh
# Remove Silent VPN from OpenWrt: files, WG/UCI, DNS, uhttpd door, packages.
# Self-contained: works even if the agent is already half-deleted.

if [ "$(id -u 2>/dev/null || echo 1)" != 0 ]; then
	echo "Нужен root. Подключитесь: ssh root@IP-роутера" >&2
	exit 1
fi

# Preserve the legacy no-argument full removal; keeping data is explicit.
SV_KEEP_DATA=0
if [ "$#" -gt 1 ]; then
	echo "usage: sh silent-vpn-uninstall [--keep-data|--purge]" >&2
	exit 2
fi
case "${1:-}" in
	""|--purge) ;;
	--keep-data) SV_KEEP_DATA=1 ;;
	*)
		echo "usage: sh silent-vpn-uninstall [--keep-data|--purge]" >&2
		exit 2
		;;
esac

echo "Silent VPN — удаление"

if [ -f /usr/lib/silent-vpn/update.sh ]; then
	SV_RUN=/var/run/silent-vpn
	. /usr/lib/silent-vpn/update.sh
	if sv_update_busy; then
		echo "Дождитесь завершения обновления и повторите удаление." >&2
		exit 1
	fi
fi

if [ -x /etc/init.d/silent-vpn-policy ]; then
	/etc/init.d/silent-vpn-policy stop >/dev/null 2>&1 || true
	/etc/init.d/silent-vpn-policy disable >/dev/null 2>&1 || true
fi

if [ -x /usr/sbin/silent-vpn-ctl ]; then
	/usr/sbin/silent-vpn-ctl disconnect >/dev/null 2>&1 || true
fi

if [ -x /etc/init.d/silent-vpn ]; then
	/etc/init.d/silent-vpn stop >/dev/null 2>&1 || true
	/etc/init.d/silent-vpn disable >/dev/null 2>&1 || true
fi
if [ -x /etc/init.d/silent-vpn-dns ]; then
	/etc/init.d/silent-vpn-dns stop >/dev/null 2>&1 || true
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
nft delete set inet fw4 sv_ru_vpn 2>/dev/null || true

uci -q delete network.svpath
uci -q delete network.svpath_peer
uci -q delete network.sv_lan_ok
uci -q delete firewall.svpath
uci -q delete firewall.sv_lan_to_path
uci -q commit network
uci -q commit firewall
uci -q delete dhcp.silent_ru
uci -q delete dhcp.silent_ru_vpn
rm -f /etc/nftables.d/90-silent-ru.nft

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

rm -rf /usr/lib/silent-vpn /usr/sbin/silent-vpn-ctl /usr/sbin/silent-vpn-policy /usr/sbin/silent-vpn-update \
	/usr/bin/spass /usr/bin/svpass /usr/bin/svcloak /usr/bin/wdtt-client /www/silent-vpn \
	/www/cgi-bin/silent-entry /www/cgi-bin/silent-api \
	/etc/init.d/silent-vpn /etc/init.d/silent-vpn-policy /etc/init.d/silent-vpn-dns \
	/etc/hotplug.d/iface/99-silent-vpn /etc/uci-defaults/99-silent-vpn \
	/var/run/silent-vpn /tmp/dnsmasq.d/silent-vpn.conf /tmp/dnsmasq.d/silent-ru.conf \
	/var/log/silent-cloak.log /var/log/silent-vpn.log /var/log/silent-vpn.log.tmp /tmp/sv-fw.log

if [ "$SV_KEEP_DATA" != 1 ]; then
	rm -rf /etc/silent-vpn /etc/config/silent-vpn
fi

/etc/init.d/firewall reload >/dev/null 2>&1 || true
/etc/init.d/dnsmasq restart >/dev/null 2>&1 || true
/etc/init.d/uhttpd restart >/dev/null 2>&1 || true

if command -v apk >/dev/null 2>&1; then
	apk del kmod-wireguard wireguard-tools ip-full >/dev/null 2>&1 || true
elif command -v opkg >/dev/null 2>&1; then
	opkg remove kmod-wireguard wireguard-tools ip-full >/dev/null 2>&1 || true
fi

# path.sh creates this alias; package removal only restores its own /sbin/ip.
if [ "$(readlink /usr/bin/ip 2>/dev/null)" = /usr/libexec/ip-full ] && [ ! -x /usr/libexec/ip-full ]; then
	ln -sf /bin/busybox /usr/bin/ip
fi

if [ "$SV_KEEP_DATA" = 1 ]; then
	echo "Готово. Silent VPN снят. Данные входа и настройки сохранены."
else
	echo "Готово. Silent VPN снят вместе с данными входа и настройками."
fi
exec rm -f /tmp/sv-rm.sh /usr/sbin/silent-vpn-uninstall
