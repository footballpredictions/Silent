#!/bin/sh
# Universal Silent VPN installer for OpenWrt (any CPU). Scripts + web only.

set -e

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DEPS="kmod-wireguard wireguard-tools wget ca-bundle uhttpd jsonfilter"

install_deps() {
	echo "Silent VPN — зависимости"
	if ! command -v opkg >/dev/null 2>&1; then
		echo "Нужен OpenWrt с opkg." >&2
		exit 1
	fi
	opkg update
	opkg install $DEPS
	echo "Зависимости готовы."
}

install_files() {
	echo "Silent VPN — установка из $ROOT"
	mkdir -p /usr/lib/silent-vpn /www/silent-vpn /www/cgi-bin /etc/silent-vpn \
		/etc/uci-defaults /etc/hotplug.d/iface /etc/init.d /usr/sbin

	cp -a "$ROOT/files/usr/lib/silent-vpn/." /usr/lib/silent-vpn/
	cp -a "$ROOT/files/usr/sbin/silent-vpn-ctl" /usr/sbin/silent-vpn-ctl
	cp -a "$ROOT/files/www/cgi-bin/." /www/cgi-bin/
	cp -a "$ROOT/web/." /www/silent-vpn/
	rm -f /www/silent-vpn/toggle-demo.html
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
	echo "Готово. С телефона или ПК в той же Wi‑Fi откройте:"
	echo "  $url"
	echo "Войдите аккаунтом Silent и включите тумблер."
	echo "LuCI по-прежнему на http://$(uci -q get network.lan.ipaddr)/"
}

cmd="${1:-all}"
case "$cmd" in
	deps)
		install_deps
		;;
	install|--skip-deps)
		install_files
		;;
	all|"")
		install_deps
		install_files
		;;
	*)
		echo "usage: sh install.sh [deps|install|all]" >&2
		exit 2
		;;
esac
