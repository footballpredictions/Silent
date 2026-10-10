#!/bin/sh
# Private Keenetic adapter. Never changes main default, WAN, NDM config or other VPNs.
set -eu
export PATH=${SVK_PATH:-/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin}
OP=${1:-check}; LAN=${2:-}; LAN_IP=${3:-}; PREFIX=${4:-}; PORT=${5:-8787}
ADDR=${6:-}; MTU=${7:-1280}
IF=svkeen; TABLE=20513; MARK=0x53000000/0xff000000
RUN=${SVK_RUN:-/opt/var/run/silent-keenetic}
mkdir -p "$RUN"
release() { rm -f "$RUN/lock/pid"; rmdir "$RUN/lock" 2>/dev/null || true; }
if [ "$OP" != check ]; then
    tries=0
    until mkdir "$RUN/lock" 2>/dev/null; do
        owner=$(cat "$RUN/lock/pid" 2>/dev/null || true)
        case "$owner" in ''|*[!0-9]*) ;; *) if ! kill -0 "$owner" 2>/dev/null; then release; continue; fi ;; esac
        case "$OP" in restore|ensure) exit 0 ;; esac
        tries=$((tries+1)); [ "$tries" -lt 8 ] || { echo 'Сетевой адаптер занят'; exit 1; }
        sleep 1
    done
    echo $$ > "$RUN/lock/pid"
    trap release EXIT
fi

chain() {
    bin=$1; table=$2; name=$3
    "$bin" -w 2 -t "$table" -N "$name" 2>/dev/null || "$bin" -w 2 -t "$table" -S "$name" >/dev/null
    "$bin" -w 2 -t "$table" -F "$name"
}
jump() {
    bin=$1; table=$2; parent=$3; child=$4
    "$bin" -w 2 -t "$table" -C "$parent" -j "$child" 2>/dev/null || "$bin" -w 2 -t "$table" -I "$parent" 1 -j "$child"
}
drop_chain() {
    bin=$1; table=$2; parent=$3; child=$4
    while "$bin" -w 2 -t "$table" -C "$parent" -j "$child" 2>/dev/null; do
        "$bin" -w 2 -t "$table" -D "$parent" -j "$child" || return 1
    done
    "$bin" -w 2 -t "$table" -F "$child" 2>/dev/null || true
    "$bin" -w 2 -t "$table" -X "$child" 2>/dev/null || true
}
rules() {
    only=${1:-all}
    if [ "$only" = all ] || [ "$only" = mangle ]; then
        chain iptables mangle SVK_M
        for net in 0.0.0.0/8 10.0.0.0/8 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4; do
            iptables -w 2 -t mangle -A SVK_M -d "$net" -j RETURN
        done
        iptables -w 2 -t mangle -A SVK_M -m set --match-set svk_direct dst -j RETURN
        iptables -w 2 -t mangle -A SVK_M -i "$LAN" -s "$PREFIX" -j MARK --set-xmark "$MARK"
        jump iptables mangle PREROUTING SVK_M
    fi
    if [ "$only" = all ] || [ "$only" = nat ]; then
        chain iptables nat SVK_N
        for proto in udp tcp; do
            iptables -w 2 -t nat -A SVK_N -i "$LAN" -s "$PREFIX" -p "$proto" --dport 53 -j DNAT --to-destination "$LAN_IP:15353"
        done
        jump iptables nat PREROUTING SVK_N
        chain iptables nat SVK_S
        iptables -w 2 -t nat -A SVK_S -s "$PREFIX" -o "$IF" -j MASQUERADE
        jump iptables nat POSTROUTING SVK_S
    fi
    if [ "$only" = all ] || [ "$only" = filter ]; then
        chain iptables filter SVK_F
        iptables -w 2 -A SVK_F -i "$LAN" -s "$PREFIX" -o "$IF" -j ACCEPT
        iptables -w 2 -A SVK_F -i "$IF" -o "$LAN" -d "$PREFIX" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
        iptables -w 2 -A SVK_F -i "$IF" -j DROP
        jump iptables filter FORWARD SVK_F
        chain iptables filter SVK_I
        iptables -w 2 -A SVK_I -i "$LAN" -s "$PREFIX" -d "$LAN_IP" -p tcp -m multiport --dports "$PORT,15353" -j ACCEPT
        iptables -w 2 -A SVK_I -i "$LAN" -s "$PREFIX" -d "$LAN_IP" -p udp --dport 15353 -j ACCEPT
        iptables -w 2 -A SVK_I -i "$IF" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
        iptables -w 2 -A SVK_I -i "$IF" -j DROP
        jump iptables filter INPUT SVK_I
    fi
    if [ "$only" = all ] || [ "$only" = ipv6 ]; then
        chain ip6tables filter SVK_V6
        ip6tables -w 2 -A SVK_V6 -i "$LAN" -j REJECT
        jump ip6tables filter FORWARD SVK_V6
    fi
}
cleanup() {
    failed=0
    # Detach LAN policy first. No broad ip rule/table/firewall flushes.
    ip rule del pref 51 fwmark "$MARK" table "$TABLE" 2>/dev/null || true
    if [ -r "$RUN/address" ]; then
        old=$(cat "$RUN/address"); old=${old%/*}
        ip rule del pref 52 from "$old/32" table "$TABLE" 2>/dev/null || true
    fi
    rm -f "$RUN/active"
    drop_chain iptables mangle PREROUTING SVK_M || failed=1
    drop_chain iptables nat PREROUTING SVK_N || failed=1
    drop_chain iptables nat POSTROUTING SVK_S || failed=1
    drop_chain iptables filter FORWARD SVK_F || failed=1
    drop_chain iptables filter INPUT SVK_I || failed=1
    drop_chain ip6tables filter FORWARD SVK_V6 || failed=1
    ip route del 10.66.66.1/32 dev "$IF" 2>/dev/null || true
    ip route flush table "$TABLE" dev "$IF" 2>/dev/null || true
    ipset destroy svk_direct 2>/dev/null || true
    rm -f "$RUN/address"
    return "$failed"
}
check() {
    [ "$(id -u)" = 0 ] || { echo 'Нужен root shell Entware'; return 1; }
    [ -c /dev/net/tun ] || { echo 'Нужен компонент TUN (например OpenVPN/IPsec) и /dev/net/tun'; return 1; }
    for bin in ip iptables ip6tables ipset ping; do command -v "$bin" >/dev/null || { echo "Нет $bin; установите зависимости Entware"; return 1; }; done
    ip -4 addr show dev "$LAN" | grep -F "inet $LAN_IP/" >/dev/null || { echo 'LAN IPv4 не принадлежит выбранному интерфейсу'; return 1; }
    ip rule show >/dev/null
    if ip rule show | awk '($1 == "51:" || $1 == "52:") && $0 !~ /lookup 20513/ {bad=1} END {exit !bad}'; then
        echo 'Приоритеты ip rule 51/52 заняты другим ПО'; return 1
    fi
    foreign=$(ip route show table "$TABLE" 2>/dev/null | grep -v "dev $IF" || true)
    [ -z "$foreign" ] || { echo 'Таблица маршрутизации 20513 занята'; return 1; }
    # iptables extension probes are read-only and detect missing modules early.
    iptables -w 2 -t mangle -S >/dev/null
    iptables -w 2 -t nat -S >/dev/null
    ip6tables -w 2 -S >/dev/null
    [ "$(cat /proc/sys/net/ipv4/ip_forward)" = 1 ] || { echo 'IPv4 forwarding выключен'; return 1; }
}
case "$OP" in
    check) check ;;
    prepare)
        printf '%s\n' "$ADDR" > "$RUN/address"
        ip addr add "$ADDR" dev "$IF"
        ip link set dev "$IF" mtu "$MTU" up
        # Only our new interface sysctl, no all/default/WAN mutation.
        echo 2 > "/proc/sys/net/ipv4/conf/$IF/rp_filter"
        ip route replace default dev "$IF" table "$TABLE"
        ip route replace "$PREFIX" dev "$LAN" table "$TABLE"
        ip route add 10.66.66.1/32 dev "$IF"
        ip rule add pref 52 from "${ADDR%/*}/32" table "$TABLE"
        # DNS resolver sockets bind to WG's address + interface.
        ipset create svk_direct hash:ip family inet maxelem 131072 -exist
        # Allow replies to the readiness probe before activating any LAN route.
        chain iptables filter SVK_I
        iptables -w 2 -A SVK_I -i "$IF" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
        iptables -w 2 -A SVK_I -i "$IF" -j DROP
        jump iptables filter INPUT SVK_I
        ;;
    ready)
        n=0
        until ping -I "$IF" -c 1 -W 2 10.66.66.1 >/dev/null 2>&1; do
            n=$((n+1)); [ "$n" -lt 5 ] || exit 1
        done
        ;;
    up)
        # Roll back a partially installed firewall if any required extension is missing.
        trap 'cleanup; release' EXIT HUP INT TERM
        rules all
        ip rule add pref 51 fwmark "$MARK" table "$TABLE"
        touch "$RUN/active"
        trap release EXIT
        trap - HUP INT TERM
        ;;
    restore)
        [ -f "$RUN/active" ] || exit 0
        ip link show "$IF" >/dev/null 2>&1 || exit 0
        case "${6:-all}" in mangle|nat|filter|ipv6|all) rules "${6:-all}" ;; *) exit 0 ;; esac
        ;;
    ensure)
        [ -f "$RUN/active" ] || exit 0
        if ! iptables -w 2 -t mangle -C PREROUTING -j SVK_M 2>/dev/null ||
           ! iptables -w 2 -t nat -C PREROUTING -j SVK_N 2>/dev/null ||
           ! iptables -w 2 -t filter -C FORWARD -j SVK_F 2>/dev/null ||
           ! ip6tables -w 2 -t filter -C FORWARD -j SVK_V6 2>/dev/null; then
            rules all
        fi
        ;;
    down) cleanup ;;
    *) echo 'check|prepare|ready|up|restore|down' >&2; exit 2 ;;
esac
