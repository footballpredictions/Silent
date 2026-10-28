#!/bin/sh
# Shared router bootstrap dispatches here only inside Keenetic's Entware shell.
set -eu
umask 077
export PATH=/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin
[ "$(id -u)" = 0 ] || { echo 'Войдите в root shell Entware'; exit 1; }
[ -x /opt/bin/opkg ] && [ -d /opt/etc/ndm ] || { echo 'Сначала настройте Entware и подключитесь к его SSH (порт 22 или 222).'; exit 1; }
case "$(uname -m)" in
    aarch64|arm64) slot=aarch64 ;;
    armv7*|armv8l) slot=armv7 ;;
    armv5*|armv6*|arm) slot=armv5 ;;
    mips*) case "$(od -An -tu1 -j5 -N1 /bin/sh | tr -d ' \n')" in 1) slot=mipsel ;; 2) slot=mips ;; *) echo 'Неизвестный MIPS ABI'; exit 1 ;; esac ;;
    x86_64|amd64) slot=x86_64 ;;
    i386|i486|i586|i686) slot=i386 ;;
    *) echo 'CPU не поддерживается'; exit 1 ;;
esac
/opt/bin/opkg update
/opt/bin/opkg install jq ca-bundle wget-ssl ip-full ipset iptables
for cmd in jq wget sha256sum tar; do command -v "$cmd" >/dev/null || { echo "Не найдена команда $cmd"; exit 1; }; done
mkdir -p /opt/share
STAGE=$(mktemp -d /opt/share/silent-keenetic-install.XXXXXX)
cleanup() { [ -z "${STAGE:-}" ] || rm -rf "$STAGE"; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
wget -q -O "$STAGE/releases.json" https://silentvpn3.github.io/releases.json
jq -e --arg arch "$slot" '.keenetic.arches[$arch]' "$STAGE/releases.json" > "$STAGE/info.json"
version=$(jq -r '.version' "$STAGE/info.json")
sha=$(jq -r '.sha256' "$STAGE/info.json")
size=$(jq -r '.size' "$STAGE/info.json")
unpacked=$(jq -r '.unpacked_size' "$STAGE/info.json")
printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || exit 1
printf '%s\n' "$sha" | grep -Eq '^[0-9a-f]{64}$' || exit 1
jq -e --arg arch "$slot" '.platform=="keenetic" and .arch==$arch and (.build_id|test("^[0-9a-f]{64}$")) and (.size|type)=="number" and .size>0 and .size<=67108864 and (.unpacked_size|type)=="number" and .unpacked_size>0 and .unpacked_size<=268435456' "$STAGE/info.json" >/dev/null
needed=$(( (size+unpacked*2+1023)/1024+8192 ))
free=$(df -Pk "$STAGE" | awk 'END {print $4}')
[ "$free" -ge "$needed" ] || { echo "Недостаточно места на накопителе Entware: нужно ${needed} KB"; exit 1; }
available=$(awk '/^MemAvailable:/ {a=$2} /^MemFree:/ {f=$2} END {print a ? a : f}' /proc/meminfo)
[ "$available" -ge 32768 ] || { echo 'Для установки нужно от 32 МБ свободной RAM'; exit 1; }
url="https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v$version/silent-vpn-keenetic-$version-$slot.tar.gz"
echo "Keenetic: скачивание $slot, версия $version"
wget -O "$STAGE/package.tar.gz" "$url"
[ "$(wc -c < "$STAGE/package.tar.gz" | tr -d ' ')" = "$size" ] || { echo 'Размер пакета не совпал'; exit 1; }
[ "$(sha256sum "$STAGE/package.tar.gz" | awk '{print $1}')" = "$sha" ] || { echo 'SHA256 пакета не совпал'; exit 1; }
prefix="silent-vpn-keenetic-$version"
# Reject links, devices, traversal and foreign roots before extracting anything.
tar -tzf "$STAGE/package.tar.gz" > "$STAGE/members"
awk -v prefix="$prefix/" 'index($0,prefix)!=1 || /(^|\/)\.\.?(\/|$)/ || /\\/ {bad=1} END {exit bad}' "$STAGE/members"
tar -tvzf "$STAGE/package.tar.gz" > "$STAGE/modes"
awk 'substr($0,1,1)!="-" {bad=1} END {exit bad}' "$STAGE/modes"
tar -xzf "$STAGE/package.tar.gz" -C "$STAGE"
work="$STAGE/$prefix"
[ "$(cat "$work/ARCH")" = "$slot" ] && [ "$(cat "$work/VERSION")" = "$version" ] || { echo 'Неверный ARCH/VERSION'; exit 1; }
jq -e --arg arch "$slot" --arg version "$version" --arg build "$(jq -r .build_id "$STAGE/info.json")" '.schema_version==1 and .platform=="keenetic" and .arch==$arch and .version==$version and .build_id==$build' "$work/PACKAGE.json" >/dev/null
sh "$work/install.sh" --no-deps
echo 'Готово. Временные файлы установки удаляются.'
