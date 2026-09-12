#!/bin/sh
# Copy Silent VPN onto a live OpenWrt box. Unique installer — not Amnezia/opkg-feed logic.

set -e

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
echo "Silent VPN OpenWrt — install from $ROOT"

need="kmod-wireguard wireguard-tools wget ca-bundle uhttpd jsonfilter"
missing=""
for p in $need; do
	if ! opkg list-installed 2>/dev/null | grep -q "^$p "; then
		missing="$missing $p"
	fi
done
if [ -n "$missing" ]; then
	echo "Installing:$missing"
	opkg update
	opkg install $missing
fi

mkdir -p /usr/lib/silent-vpn /www/silent-vpn /www/cgi-bin /etc/silent-vpn \
	/etc/uci-defaults /etc/hotplug.d/iface /etc/init.d /usr/sbin

cp -a "$ROOT/files/usr/lib/silent-vpn/." /usr/lib/silent-vpn/
cp -a "$ROOT/files/usr/sbin/silent-vpn-ctl" /usr/sbin/silent-vpn-ctl
cp -a "$ROOT/files/www/cgi-bin/." /www/cgi-bin/
cp -a "$ROOT/web/." /www/silent-vpn/
cp -a "$ROOT/files/etc/init.d/silent-vpn" /etc/init.d/silent-vpn
cp -a "$ROOT/files/etc/config/silent-vpn" /etc/config/silent-vpn
cp -a "$ROOT/files/etc/hotplug.d/iface/99-silent-vpn" /etc/hotplug.d/iface/99-silent-vpn
cp -a "$ROOT/files/etc/uci-defaults/99-silent-vpn" /etc/uci-defaults/99-silent-vpn

chmod 0755 /usr/sbin/silent-vpn-ctl /www/cgi-bin/silent-entry /www/cgi-bin/silent-api \
	/etc/init.d/silent-vpn /etc/hotplug.d/iface/99-silent-vpn

sh /etc/uci-defaults/99-silent-vpn || true
/etc/init.d/silent-vpn enable
/etc/init.d/silent-vpn start
/etc/init.d/uhttpd restart >/dev/null 2>&1 || true

url="$(/usr/sbin/silent-vpn-ctl lan-url 2>/dev/null || echo "http://$(uci -q get network.lan.ipaddr).silent.vpn")"
echo
echo "Готово. Откройте с устройства в LAN:"
echo "  $url"
echo "LuCI по-прежнему на http://$(uci -q get network.lan.ipaddr)/"
