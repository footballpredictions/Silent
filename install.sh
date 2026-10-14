#!/bin/sh
# Run from an extracted release on an Entware filesystem, never OpenWrt.
set -eu
umask 077
export PATH=/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEST=/opt/lib/silent-keenetic
CONFIG=/opt/etc/silent-keenetic/config.json
LAN=${SVK_LAN_INTERFACE:-br0}
OTA=0
NO_DEPS=0
for arg in "$@"; do
    case "$arg" in
        --no-deps) NO_DEPS=1 ;;
        --ota) OTA=1; NO_DEPS=1 ;;
        *) echo "Неизвестный аргумент: $arg"; exit 2 ;;
    esac
done

arch() {
    cpu=$(uname -m)
    case "$cpu" in
        aarch64|arm64) echo aarch64 ;;
        armv7*|armv8l) echo armv7 ;;
        armv5*|armv6*|arm) echo armv5 ;;
        mips*)
            # uname often says mips even on little endian. Detect actual ELF EI_DATA.
            data=$(od -An -tu1 -j5 -N1 /bin/sh | tr -d ' \n')
            case "$data" in 1) echo mipsel ;; 2) echo mips ;; *) return 1 ;; esac ;;
        x86_64|amd64) echo x86_64 ;;
        i386|i486|i586|i686) echo i386 ;;
        *) return 1 ;;
    esac
}

[ "$(id -u)" = 0 ] || { echo 'Запустите из root shell Entware'; exit 1; }
[ -x /opt/bin/opkg ] || { echo 'Сначала настройте Entware в KeeneticOS (USB или поддерживаемая NAND).'; exit 1; }
[ -d /opt/etc/ndm ] || { echo 'Не найдена среда NDM Keenetic; этот архив не предназначен для OpenWrt.'; exit 1; }
if [ "$OTA" = 0 ] && [ -f /opt/etc/silent-keenetic/update.lock/pid ]; then
    worker=$(cat /opt/etc/silent-keenetic/update.lock/pid)
    case "$worker" in ''|*[!0-9]*|0|1) ;; *) kill -0 "$worker" 2>/dev/null && { echo 'Дождитесь завершения обновления'; exit 1; } ;; esac
fi
kernel=$(uname -r); major=${kernel%%.*}; rest=${kernel#*.}; minor=${rest%%.*}
if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 2 ]; }; then
    echo "Ядро $kernel слишком старое: Go-транспорт требует Linux 3.2+."; exit 1
fi
SLOT=$(arch) || { echo "CPU $(uname -m) не поддерживается"; exit 1; }
[ -x "$ROOT/bin/$SLOT/silent-keenetic" ] && [ -x "$ROOT/bin/$SLOT/spass" ] || { echo "В архиве нет сборки $SLOT"; exit 1; }
[ "$(cat "$ROOT/ARCH")" = "$SLOT" ] || [ "$(cat "$ROOT/ARCH")" = universal ] || { echo 'ARCH не совпадает с CPU'; exit 1; }
if [ "$NO_DEPS" = 0 ]; then
    /opt/bin/opkg update
    /opt/bin/opkg install ip-full ipset iptables
fi
if [ -f "$CONFIG" ]; then
    # Existing LAN selection and password are authoritative during upgrades.
    LAN_CIDR=''; LAN_IP=''; PREFIX=''
elif ! ip -4 addr show dev "$LAN" >/dev/null 2>&1; then
    if ip -4 addr show dev br-lan >/dev/null 2>&1; then LAN=br-lan; else echo 'Укажите SVK_LAN_INTERFACE=<основной LAN bridge>'; exit 1; fi
fi
if [ ! -f "$CONFIG" ]; then
    LAN_CIDR=$(ip -o -4 addr show dev "$LAN" | awk '{print $4; exit}')
    LAN_IP=${LAN_CIDR%/*}
    PREFIX=$(ip -4 route show dev "$LAN" proto kernel | awk '$1 ~ /\// {print $1; exit}')
    [ -n "$PREFIX" ] || { echo 'Не найдена IPv4 подсеть LAN'; exit 1; }
fi
for path in "$DEST" /opt/etc/silent-keenetic /opt/etc/init.d /opt/etc/ndm/netfilter.d; do mkdir -p "$path"; done
needed=$(du -sk "$ROOT/bin/$SLOT" "$ROOT/files" | awk '{n+=$1} END {print n+4096}')
old=$(du -sk "$DEST" /opt/etc/silent-keenetic | awk '{n+=$1} END {print n}')
free=$(df -Pk "$DEST" | awk 'END {print $4}')
required=$needed
[ "$OTA" = 1 ] || required=$((needed+old))
[ "$free" -ge "$required" ] || { echo 'Недостаточно места для установки и отката'; exit 1; }
BACKUP=''
STOPPED=0
MODIFIED=0
rollback() {
    code=$?
    [ "$code" = 0 ] && return
    trap - EXIT
    set +e
    echo 'Установка не завершена; очищаю частичную установку.' >&2
    if [ "$MODIFIED" = 1 ] && [ -d "$BACKUP/runtime" ]; then
        [ ! -x "$DEST/silent-keenetic" ] || "$DEST/silent-keenetic" --cleanup
        # Remove only new runtime files absent in the previous version.
        for name in VERSION ARCH PACKAGE.json ru-vpn.domains; do
            [ -e "$BACKUP/runtime/$name" ] || rm -f "$DEST/$name"
        done
        for file in "$BACKUP/runtime/"*; do
            cp -a "$file" "$DEST/$(basename "$file").rollback" && mv -f "$DEST/$(basename "$file").rollback" "$DEST/$(basename "$file")"
        done
        # Config was never overwritten; shutdown may have refreshed the token.
        [ ! -f "$BACKUP/S99silent-keenetic" ] || cp "$BACKUP/S99silent-keenetic" /opt/etc/init.d/
        [ ! -f "$BACKUP/100-silent-keenetic.sh" ] || cp "$BACKUP/100-silent-keenetic.sh" /opt/etc/ndm/netfilter.d/
        echo "Предыдущая версия восстановлена из $BACKUP" >&2
    elif [ "$MODIFIED" = 1 ]; then
        rm -f /opt/etc/init.d/S99silent-keenetic /opt/etc/ndm/netfilter.d/100-silent-keenetic.sh
        rm -rf /opt/lib/silent-keenetic
        echo "Конфигурация сохранена: $CONFIG" >&2
    fi
    if [ "$OTA" = 0 ] && [ "$STOPPED" = 1 ] && [ -x /opt/etc/init.d/S99silent-keenetic ]; then /opt/etc/init.d/S99silent-keenetic start; fi
    exit "$code"
}
trap rollback EXIT
trap 'exit 1' HUP INT TERM
if [ -f "$DEST/silent-keenetic" ]; then
    if [ "$OTA" = 0 ]; then STOPPED=1; /opt/etc/init.d/S99silent-keenetic stop; fi
    if [ "$OTA" = 1 ]; then BACKUP="$ROOT/.rollback"; else mkdir -p /opt/var/backups; BACKUP=$(mktemp -d /opt/var/backups/silent-keenetic-XXXXXX); fi
    mkdir -p "$BACKUP"
    cp -a "$DEST" "$BACKUP/runtime"
    cp -a /opt/etc/silent-keenetic "$BACKUP/config"
    [ ! -f /opt/etc/init.d/S99silent-keenetic ] || cp /opt/etc/init.d/S99silent-keenetic "$BACKUP/"
    [ ! -f /opt/etc/ndm/netfilter.d/100-silent-keenetic.sh ] || cp /opt/etc/ndm/netfilter.d/100-silent-keenetic.sh "$BACKUP/"
fi
MODIFIED=1
# Atomic replacement permits a detached old updater to keep running its inode.
for binary in silent-keenetic spass; do
    cp "$ROOT/bin/$SLOT/$binary" "$DEST/$binary.new"
    chmod 755 "$DEST/$binary.new"
    mv -f "$DEST/$binary.new" "$DEST/$binary"
done
for file in network.sh guard.sh ru-direct.domains ru-vpn.domains; do cp "$ROOT/files/$file" "$DEST/$file"; done
cp "$ROOT/VERSION" "$DEST/VERSION"
printf '%s\n' "$SLOT" > "$DEST/ARCH"
cp "$ROOT/PACKAGE.json" "$DEST/PACKAGE.json"
cp "$ROOT/uninstall.sh" "$DEST/uninstall.sh"
chmod 755 "$DEST/silent-keenetic" "$DEST/spass" "$DEST/network.sh" "$DEST/guard.sh" "$DEST/uninstall.sh"
if [ ! -f "$CONFIG" ]; then
    "$DEST/silent-keenetic" --init-lan "$LAN" --lan-ip "$LAN_IP" --lan-prefix "$PREFIX"
else
    echo "Конфигурация и пароль панели сохранены: $CONFIG"
fi
"$DEST/silent-keenetic" --check
cp "$ROOT/files/S99silent-keenetic" /opt/etc/init.d/S99silent-keenetic
cp "$ROOT/files/100-silent-keenetic.sh" /opt/etc/ndm/netfilter.d/100-silent-keenetic.sh
chmod 755 /opt/etc/init.d/S99silent-keenetic /opt/etc/ndm/netfilter.d/100-silent-keenetic.sh
if [ "$OTA" = 0 ]; then /opt/etc/init.d/S99silent-keenetic start; fi
echo 'Установлено. Откройте адрес панели выше и войдите в свой аккаунт Silent VPN.'
