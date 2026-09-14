#!/bin/sh
# One-shot OpenWrt install: check CPU, deps, panel, wdtt, then wipe /tmp copies.
set -e

PKG="${SILENT_OPENWRT_PKG:-https://silentvpn3.github.io/silent-vpn-openwrt.tgz}"

sv_slot() {
	m="$(uname -m 2>/dev/null || true)"
	case "$m" in
		aarch64|arm64) echo aarch64 ;;
		armv7*|armv6*|arm) echo arm ;;
		mipsel*|mips*) echo mipsel ;;
		x86_64|amd64) echo x86_64 ;;
		*) echo "" ;;
	esac
}

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

sv_fetch() {
	url="$1"
	out="$2"
	if command -v wget >/dev/null 2>&1; then
		wget -O "$out" "$url" && return 0
		wget --no-check-certificate -O "$out" "$url" && return 0
	fi
	if command -v uclient-fetch >/dev/null 2>&1; then
		uclient-fetch -O "$out" "$url" && return 0
	fi
	echo "Не удалось скачать: $url" >&2
	exit 1
}

if [ "$(id -u 2>/dev/null || echo 1)" != 0 ]; then
	echo "Нужен root. В Сервисы → Терминал вы уже root." >&2
	exit 1
fi

slot="$(sv_slot)"
if [ -z "$slot" ]; then
	echo "Архитектура $(uname -m) не поддерживается (нужны aarch64, arm, mipsel, x86_64)." >&2
	exit 1
fi
echo "CPU: $(uname -m) → $slot"

sv_pkg_update
sv_pkg_add wget ca-bundle

cd /tmp
rm -rf silent-vpn Silent-openwrt silent-vpn-openwrt.tgz
sv_fetch "$PKG" silent-vpn-openwrt.tgz
tar -xzf silent-vpn-openwrt.tgz
if [ -d silent-vpn ]; then
	WORKDIR=/tmp/silent-vpn
elif [ -d Silent-openwrt ]; then
	WORKDIR=/tmp/Silent-openwrt
else
	echo "В архиве нет silent-vpn/" >&2
	exit 1
fi

if [ ! -f "$WORKDIR/files/usr/lib/silent-vpn/wdtt/wdtt-client.$slot" ]; then
	echo "Нет модуля обхода для архитектуры $slot." >&2
	rm -rf "$WORKDIR" /tmp/silent-vpn-openwrt.tgz
	exit 1
fi

sh "$WORKDIR/install.sh"
cd /tmp
rm -rf silent-vpn Silent-openwrt silent-vpn-openwrt.tgz
exec rm -f /tmp/sv.sh
