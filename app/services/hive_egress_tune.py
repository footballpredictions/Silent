"""Egress PMTU/TTL как на быстрых сотах: TCPMSS clamp, probing, без IPv6, TTL 64.

Не копирует AI TPROXY и не поднимает wdtt0 MTU (это только игровая сота 2).
wdtt не рестартим. SILENT_DENY не трогаем.
"""
from __future__ import annotations

INNER_SH = r"""#!/bin/bash
# Сгенерировано app/services/hive_egress_tune.py. Идемпотентно.
# SILENT_DENY не трогаем. wdtt не рестартим.
set -u
PATH="$PATH:/usr/sbin:/sbin"
WAN="$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')"

sysctl -w net.ipv4.tcp_mtu_probing=1 >/dev/null 2>&1 || true
sysctl -w net.ipv4.tcp_slow_start_after_idle=0 >/dev/null 2>&1 || true
sysctl -w net.ipv4.ip_no_pmtu_disc=0 >/dev/null 2>&1 || true
sysctl -w net.ipv4.icmp_echo_ignore_all=0 >/dev/null 2>&1 || true
# DTLS воркеры: короткий UDP conntrack и backlog=1000 роняют рамп (53/63).
sysctl -w net.netfilter.nf_conntrack_udp_timeout=120 >/dev/null 2>&1 || true
sysctl -w net.netfilter.nf_conntrack_udp_timeout_stream=180 >/dev/null 2>&1 || true
sysctl -w net.core.netdev_max_backlog=16384 >/dev/null 2>&1 || true
sysctl -w net.ipv4.udp_rmem_min=8192 >/dev/null 2>&1 || true
sysctl -w net.ipv4.udp_wmem_min=8192 >/dev/null 2>&1 || true

iptables -t mangle -C FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null \
  || iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

if [ -n "$WAN" ]; then
  modprobe xt_HL 2>/dev/null || true
  iptables -t mangle -C POSTROUTING -o "$WAN" -j TTL --ttl-set 64 2>/dev/null \
    || iptables -t mangle -A POSTROUTING -o "$WAN" -j TTL --ttl-set 64 2>/dev/null \
    || echo "[egress-pmtu] TTL target missing"
fi

if command -v ip6tables >/dev/null 2>&1; then
  ip6tables -C FORWARD -j DROP 2>/dev/null || ip6tables -A FORWARD -j DROP
  ip6tables -C OUTPUT -d 2000::/3 -j REJECT 2>/dev/null || ip6tables -A OUTPUT -d 2000::/3 -j REJECT
fi

mkdir -p /etc/sysctl.d
cat > /etc/sysctl.d/99-silent-egress-pmtu.conf <<'SYS'
net.ipv4.tcp_mtu_probing=1
net.ipv4.tcp_slow_start_after_idle=0
net.ipv4.ip_no_pmtu_disc=0
net.ipv4.icmp_echo_ignore_all=0
net.netfilter.nf_conntrack_udp_timeout=120
net.netfilter.nf_conntrack_udp_timeout_stream=180
net.core.netdev_max_backlog=16384
net.ipv4.udp_rmem_min=8192
net.ipv4.udp_wmem_min=8192
SYS
sysctl -p /etc/sysctl.d/99-silent-egress-pmtu.conf >/dev/null 2>&1 || true
exit 0
"""

INSTALL_SH = r"""#!/bin/bash
set -u
PATH="$PATH:/usr/sbin:/sbin"
ROOT=/opt/silent-vpn/egress-pmtu
mkdir -p "$ROOT"
cat > "$ROOT/10-tune.sh" <<'INNER'
__INNER__
INNER
chmod 755 "$ROOT/10-tune.sh"
"$ROOT/10-tune.sh"

cat > /etc/systemd/system/silent-egress-pmtu.service <<EOF
[Unit]
Description=Silent VPN egress PMTU/TTL (idempotent)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$ROOT/10-tune.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload >/dev/null 2>&1 || true
systemctl enable silent-egress-pmtu.service >/dev/null 2>&1 || true

echo "=== wdtt (must stay active, untouched) ==="
systemctl is-active wdtt
echo "=== mangle TCPMSS ==="
iptables -t mangle -S FORWARD 2>/dev/null | grep -i TCPMSS || echo "(нет)"
echo "=== TTL ==="
iptables -t mangle -S POSTROUTING 2>/dev/null | grep -- "--ttl-set" || echo "(нет)"
echo "=== sysctl ==="
sysctl net.ipv4.tcp_mtu_probing net.ipv4.tcp_slow_start_after_idle net.ipv4.ip_no_pmtu_disc \
  net.netfilter.nf_conntrack_udp_timeout net.netfilter.nf_conntrack_udp_timeout_stream \
  net.core.netdev_max_backlog net.ipv4.udp_rmem_min 2>/dev/null || true
echo "=== done ==="
"""


def tune_script() -> str:
    return INSTALL_SH.replace("__INNER__", INNER_SH.rstrip("\n"))
