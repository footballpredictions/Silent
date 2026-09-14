#!/bin/sh
# Universal Silent VPN installer for OpenWrt (any CPU).

set -e

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DEPS="kmod-wireguard wireguard-tools ip-full wget ca-bundle uhttpd jsonfilter iw"

sv_pkg_kind() {
	rel=""
	if [ -r /etc/openwrt_release ]; then
		rel="$(. /etc/openwrt_release >/dev/null 2>&1 && printf '%s' "$DISTRIB_RELEASE")"
	fi
	major="${rel%%.*}"
	has_apk=0
	has_opkg=0
	has_apk_db=0
	if command -v apk >/dev/null 2>&1; then has_apk=1; fi
	if command -v opkg >/dev/null 2>&1; then has_opkg=1; fi
	if [ -d /etc/apk ] || [ -d /lib/apk ]; then has_apk_db=1; fi

	if [ -n "$major" ] && [ "$major" -ge 25 ] 2>/dev/null; then
		if [ "$has_apk" = 1 ]; then echo apk; return; fi
		if [ "$has_opkg" = 1 ]; then echo opkg; return; fi
		echo ""; return
	fi
	if [ -n "$major" ] && [ "$major" -eq "$major" ] 2>/dev/null; then
		if [ "$has_opkg" = 1 ]; then echo opkg; return; fi
		if [ "$has_apk" = 1 ]; then echo apk; return; fi
		echo ""; return
	fi
	if [ "$has_apk" = 1 ] && [ "$has_apk_db" = 1 ]; then echo apk; return; fi
	if [ "$has_opkg" = 1 ]; then echo opkg; return; fi
	if [ "$has_apk" = 1 ]; then echo apk; return; fi
	echo ""
}

sv_require_pkg() {
	SV_PKG="$(sv_pkg_kind)"
	if [ -z "$SV_PKG" ]; then
		echo "Нужен OpenWrt с opkg (23/24) или apk (25+)." >&2
		exit 1
	fi
}

sv_pkg_update() {
	sv_require_pkg
	echo "пакеты: $SV_PKG"
	if [ "$SV_PKG" = apk ]; then
		apk update
	else
		opkg update
	fi
}

sv_pkg_add() {
	sv_require_pkg
	if [ "$SV_PKG" = apk ]; then
		apk add "$@"
	else
		opkg install "$@"
	fi
}

sv_wdtt_slot() {
	m="$(uname -m 2>/dev/null || true)"
	case "$m" in
		aarch64|arm64) echo aarch64 ;;
		armv7*|armv6*|arm) echo arm ;;
		mipsel*|mips*) echo mipsel ;;
		x86_64|amd64) echo x86_64 ;;
		*) echo "" ;;
	esac
}

require_arch() {
	slot="$(sv_wdtt_slot)"
	src="$ROOT/files/usr/lib/silent-vpn/wdtt/wdtt-client.$slot"
	if [ -z "$slot" ] || [ ! -f "$src" ]; then
		echo "Архитектура $(uname -m) не поддерживается. Нужны aarch64, arm, mipsel, x86_64." >&2
		exit 1
	fi
	SV_WDTT_SLOT="$slot"
	SV_WDTT_SRC="$src"
}

install_deps() {
	echo "Silent VPN — зависимости"
	sv_require_pkg
	if [ "$(id -u 2>/dev/null || echo 1)" != 0 ]; then
		echo "Нужен root. В Сервисы → Терминал вы уже root." >&2
		exit 1
	fi
	sv_pkg_update
	sv_pkg_add $DEPS
}

install_wdtt() {
	rm -f /usr/bin/wdtt-client /usr/bin/svcloak /usr/bin/svpass
	cp -a "$SV_WDTT_SRC" /usr/bin/spass
	chmod 0755 /usr/bin/spass
	echo "обход: /usr/bin/spass ($SV_WDTT_SLOT)"
}

install_files() {
	if [ "$(id -u 2>/dev/null || echo 1)" != 0 ]; then
		echo "Нужен root. В Сервисы → Терминал вы уже root." >&2
		exit 1
	fi
	require_arch
	echo "Silent VPN — установка из $ROOT ($SV_WDTT_SLOT)"
	mkdir -p /usr/lib/silent-vpn /www/silent-vpn /www/cgi-bin /etc/silent-vpn \
		/etc/uci-defaults /etc/hotplug.d/iface /etc/init.d /usr/sbin

	cp -a "$ROOT/files/usr/lib/silent-vpn/." /usr/lib/silent-vpn/
	rm -rf /usr/lib/silent-vpn/wdtt
	cp -a "$ROOT/files/usr/sbin/silent-vpn-ctl" /usr/sbin/silent-vpn-ctl
	cp -a "$ROOT/files/www/cgi-bin/." /www/cgi-bin/
	cp -a "$ROOT/web/." /www/silent-vpn/
	rm -f /www/silent-vpn/toggle-demo.html
	cp -a "$ROOT/files/etc/init.d/silent-vpn" /etc/init.d/silent-vpn
	cp -a "$ROOT/files/etc/config/silent-vpn" /etc/config/silent-vpn
	cp -a "$ROOT/files/etc/hotplug.d/iface/99-silent-vpn" /etc/hotplug.d/iface/99-silent-vpn
	cp -a "$ROOT/files/etc/uci-defaults/99-silent-vpn" /etc/uci-defaults/99-silent-vpn
	if [ -f "$ROOT/uninstall.sh" ]; then
		cp -a "$ROOT/uninstall.sh" /usr/sbin/silent-vpn-uninstall
		chmod 0755 /usr/sbin/silent-vpn-uninstall
	fi
	install_wdtt

	chmod 0755 /usr/sbin/silent-vpn-ctl /www/cgi-bin/silent-entry /www/cgi-bin/silent-api \
		/etc/init.d/silent-vpn /etc/hotplug.d/iface/99-silent-vpn

	sh /etc/uci-defaults/99-silent-vpn || true
	/etc/init.d/silent-vpn enable
	/etc/init.d/silent-vpn start
	/etc/init.d/uhttpd restart >/dev/null 2>&1 || true

	url="$(/usr/sbin/silent-vpn-ctl lan-url 2>/dev/null || echo "http://$(uci -q get network.lan.ipaddr).silent.vpn")"
	echo
	echo "Готово: $url"
	echo "Войдите аккаунтом Silent и включите тумблер."
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
		require_arch
		install_deps
		install_files
		;;
	uninstall)
		sh "$ROOT/uninstall.sh"
		;;
	*)
		echo "usage: sh install.sh [deps|install|all|uninstall]" >&2
		exit 2
		;;
esac
