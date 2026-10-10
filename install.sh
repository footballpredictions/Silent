#!/bin/sh
# Run from an extracted release on an Entware filesystem, never OpenWrt.
set -eu
umask 077
export PATH=/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEST=/opt/lib/silent-keenetic
CONFIG=/opt/etc/silent-keenetic/config.json
LAN=${SVK_LAN_INTERFACE:-br0}

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
kernel=$(uname -r); major=${kernel%%.*}; rest=${kernel#*.}; minor=${rest%%.*}
if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 2 ]; }; then
    echo "Ядро $kernel слишком старое: Go-транспорт требует Linux 3.2+."; exit 1
fi
SLOT=$(arch) || { echo "CPU $(uname -m) не поддерживается"; exit 1; }
[ -x "$ROOT/bin/$SLOT/silent-keenetic" ] && [ -x "$ROOT/bin/$SLOT/spass" ] || { echo "В архиве нет сборки $SLOT"; exit 1; }
if [ "${1:-}" != '--no-deps' ]; then
    /opt/bin/opkg update
    /opt/bin/opkg install ip-full ipset iptables
fi
if ! ip -4 addr show dev "$LAN" >/dev/null 2>&1; then
    if ip -4 addr show dev br-lan >/dev/null 2>&1; then LAN=br-lan; else echo 'Укажите SVK_LAN_INTERFACE=<основной LAN bridge>'; exit 1; fi
fi
LAN_CIDR=$(ip -o -4 addr show dev "$LAN" | awk '{print $4; exit}')
LAN_IP=${LAN_CIDR%/*}
PREFIX=$(ip -4 route show dev "$LAN" proto kernel | awk '$1 ~ /\// {print $1; exit}')
[ -n "$PREFIX" ] || { echo 'Не найдена IPv4 подсеть LAN'; exit 1; }
for path in "$DEST" /opt/etc/silent-keenetic /opt/etc/init.d /opt/etc/ndm/netfilter.d; do mkdir -p "$path"; done

# Backup the previous install before touching it. Do not preserve other packages in this archive.
if [ -f "$DEST/silent-keenetic" ]; then
    BACKUP=/opt/var/backups/silent-keenetic-$(date +%Y%m%d-%H%M%S)
    mkdir -p "$BACKUP"
    cp -a "$DEST" "$BACKUP/runtime"
    cp -a /opt/etc/silent-keenetic "$BACKUP/config"
    [ ! -f /opt/etc/init.d/S99silent-keenetic ] || cp /opt/etc/init.d/S99silent-keenetic "$BACKUP/"
    [ ! -f /opt/etc/ndm/netfilter.d/100-silent-keenetic.sh ] || cp /opt/etc/ndm/netfilter.d/100-silent-keenetic.sh "$BACKUP/"
    /opt/etc/init.d/S99silent-keenetic stop
    echo "Предыдущая установка: $BACKUP"
fi
rollback() {
    code=$?
    [ "$code" = 0 ] && return
    trap - EXIT
    set +e
    echo 'Установка не завершена; очищаю частичную установку.' >&2
    [ ! -x "$DEST/silent-keenetic" ] || "$DEST/silent-keenetic" --cleanup
    if [ -n "${BACKUP:-}" ]; then
        cp -a "$BACKUP/runtime/." "$DEST/"
        cp -a "$BACKUP/config/." /opt/etc/silent-keenetic/
        [ ! -f "$BACKUP/S99silent-keenetic" ] || cp "$BACKUP/S99silent-keenetic" /opt/etc/init.d/
        [ ! -f "$BACKUP/100-silent-keenetic.sh" ] || cp "$BACKUP/100-silent-keenetic.sh" /opt/etc/ndm/netfilter.d/
        /opt/etc/init.d/S99silent-keenetic start
        echo "Предыдущая версия восстановлена из $BACKUP" >&2
    else
        rm -f /opt/etc/init.d/S99silent-keenetic /opt/etc/ndm/netfilter.d/100-silent-keenetic.sh
        rm -rf /opt/lib/silent-keenetic
        echo "Конфигурация сохранена: $CONFIG" >&2
    fi
    exit "$code"
}
trap rollback EXIT
cp "$ROOT/bin/$SLOT/silent-keenetic" "$DEST/silent-keenetic"
cp "$ROOT/bin/$SLOT/spass" "$DEST/spass"
cp "$ROOT/files/network.sh" "$DEST/network.sh"
cp "$ROOT/files/guard.sh" "$DEST/guard.sh"
cp "$ROOT/files/ru-direct.domains" "$DEST/ru-direct.domains"
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
/opt/etc/init.d/S99silent-keenetic start
echo 'Установлено. Откройте адрес панели выше и войдите в свой аккаунт Silent VPN.'
