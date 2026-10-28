#!/bin/sh
# Universal router installation/update: detect platform, select CPU, keep user data.
set -e

# Keep the published one-command entry point shared by both router platforms.
if [ -d /opt/etc/ndm ] && [ -x /opt/bin/opkg ]; then
	SVK_HELPER=$(mktemp /tmp/svk-bootstrap.XXXXXX) || exit 1
	trap 'rm -f "$SVK_HELPER"' EXIT
	trap 'exit 1' HUP INT TERM
	wget -O "$SVK_HELPER" https://silentvpn3.github.io/keenetic-install.sh || exit 1
	sh "$SVK_HELPER"
	exit $?
fi

PKG="${SILENT_OPENWRT_PKG:-}"
RELEASES="${SILENT_OPENWRT_RELEASES:-https://silentvpn3.github.io/releases.json}"

sv_slot() {
	m="$(uname -m 2>/dev/null || true)"
	case "$m" in
		aarch64|arm64) echo aarch64 ;;
		armv7l|armv8l) echo arm ;;
		mipsel|mips)
			# uname says 'mips' on both endiannesses; inspect the userspace ELF.
			endian="$(od -An -tu1 -j5 -N1 /bin/busybox 2>/dev/null | tr -d ' ')"
			[ "$endian" = 1 ] && echo mipsel || echo ""
			;;
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

sv_unpack() {
	local archive="$1" stage="$2" arch
	: > "$stage/.exclude-architectures"
	for arch in aarch64 arm mipsel x86_64; do
		if [ "$arch" != "$slot" ]; then
			# BusyBox tar -X matches full member names; GNU glob behavior differs.
			printf 'silent-vpn/files/usr/lib/silent-vpn/wdtt/wdtt-client.%s\nSilent-openwrt/files/usr/lib/silent-vpn/wdtt/wdtt-client.%s\n' "$arch" "$arch" >> "$stage/.exclude-architectures"
		fi
	done
	tar -xzf "$archive" -C "$stage" -X "$stage/.exclude-architectures"
}

sv_remote_cleanup() {
	[ -z "${STAGE:-}" ] || rm -rf "$STAGE"
}

sv_json() { jsonfilter -i "$STAGE/releases.json" -e "@.openwrt.arches.$slot.$1"; }

sv_space() {
	local path="$1" needed="$2" label="$3" free
	free="$(df -Pk "$path" | awk 'END {print $4}')"
	case "$free" in ''|*[!0-9]*) echo "Не удалось проверить место: $path" >&2; return 1 ;; esac
	if [ "$free" -lt "$needed" ]; then
		echo "Недостаточно места ($label): свободно ${free} KB, нужно ${needed} KB." >&2
		return 1
	fi
}

sv_preflight() {
	local compressed="$1" unpacked="$2" extra="${3:-0}" ram_needed flash_needed available
	case "$compressed:$unpacked" in *[!0-9:]*|:*|*:) echo "Некорректные размеры пакета" >&2; return 1 ;; esac
	[ "$compressed" -gt 0 ] && [ "$unpacked" -gt 0 ] || return 1
	ram_needed=$(( (compressed + unpacked + extra + 1023) / 1024 + 8192 ))
	flash_needed=$(( (unpacked + 1023) / 1024 + 8192 ))
	sv_space /tmp "$ram_needed" 'временные файлы' || return 1
	sv_space /usr "$flash_needed" 'установка и зависимости' || return 1
	available="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
	# Older kernels have no MemAvailable; df remains the available guard there.
	if [ -n "$available" ] && [ "$available" -lt "$ram_needed" ]; then
		echo "Недостаточно оперативной памяти: свободно ${available} KB, нужно ${ram_needed} KB." >&2
		return 1
	fi
}

# Also supplies architecture/resource/archive helpers to the panel updater.
if [ "${SILENT_OPENWRT_LIBRARY:-0}" = 1 ]; then return 0; fi

if [ "$(id -u 2>/dev/null || echo 1)" != 0 ]; then
	echo "Нужен root. Подключитесь: ssh root@IP-роутера" >&2
	exit 1
fi

slot="$(sv_slot)"
if [ -z "$slot" ]; then
	echo "Архитектура $(uname -m) не поддерживается (нужны aarch64, arm, mipsel, x86_64)." >&2
	exit 1
fi
echo "CPU: $(uname -m) → $slot"

cd /tmp
# Clean the fixed names used by earlier installers, including failed unpack.
rm -rf silent-vpn Silent-openwrt silent-vpn-openwrt.tgz
STAGE="$(mktemp -d /tmp/sv-install.XXXXXX)"
trap sv_remote_cleanup EXIT
trap 'exit 1' HUP INT TERM
sv_pkg_update
sv_pkg_add wget ca-bundle jsonfilter
if [ -z "$PKG" ]; then
	sv_fetch "${RELEASES}?check=$(date +%s)" "$STAGE/releases.json"
	VERSION="$(sv_json version)"
	PKG="$(sv_json download_url)"
	SIZE="$(sv_json size)"
	UNPACKED="$(sv_json unpacked_size)"
	SHA256="$(sv_json sha256)"
	case "$PKG" in https://github.com/*/releases/download/*) ;; *) echo "Нет опубликованного пакета для $slot." >&2; exit 1 ;; esac
	[ "${#SHA256}" = 64 ] || { echo "Нет контрольной суммы пакета $slot." >&2; exit 1; }
	case "$SHA256" in *[!0-9a-f]*) exit 1 ;; esac
	sv_preflight "$SIZE" "$UNPACKED"
fi
sv_fetch "$PKG" "$STAGE/package.tgz"
if [ -n "${SHA256:-}" ]; then
	printf '%s  %s\n' "$SHA256" "$STAGE/package.tgz" | sha256sum -c -
fi
sv_unpack "$STAGE/package.tgz" "$STAGE"
rm -f "$STAGE/package.tgz"
if [ -d "$STAGE/silent-vpn" ]; then
	WORKDIR="$STAGE/silent-vpn"
elif [ -d "$STAGE/Silent-openwrt" ]; then
	WORKDIR="$STAGE/Silent-openwrt"
else
	echo "В архиве нет silent-vpn/" >&2
	exit 1
fi

if [ -f "$WORKDIR/ARCH" ] && [ "$(cat "$WORKDIR/ARCH")" != "$slot" ]; then
	echo "Архитектура пакета не совпадает с $slot." >&2
	exit 1
fi

if [ -n "${VERSION:-}" ] && [ "$(cat "$WORKDIR/VERSION" 2>/dev/null)" != "$VERSION" ]; then
	echo "Версия архива не совпадает с опубликованной $VERSION." >&2
	exit 1
fi

if [ ! -f "$WORKDIR/files/usr/lib/silent-vpn/wdtt/wdtt-client.$slot" ]; then
	echo "Нет модуля обхода для архитектуры $slot." >&2
	exit 1
fi

SILENT_OPENWRT_STAGE="$STAGE" sh "$WORKDIR/install.sh"
cd /tmp
sv_remote_cleanup
STAGE=""
exec rm -f /tmp/sv.sh
