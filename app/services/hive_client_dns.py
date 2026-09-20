"""Клиентский DNS с Улья: при выключенном фильтре угроз заворачивать :53 на Cloudflare.

Как на Сервере 4: телефон шлёт на 77.88.8.8 / свой DNS, Улей отвечает через 1.1.1.1.
Фильтр угроз (10.66.66.1) важнее, если тумблер включён.
wdtt не рестартим. SILENT_DENY не трогаем.
"""
from __future__ import annotations

BIN_SYNC = "/usr/local/sbin/silent-threat-dns-sync.sh"

THREAT_DNS_SYNC_SCRIPT = r"""#!/bin/bash
set -euo pipefail
ENV_FILE="/opt/silent-vpn/backend/.env"
COMMENT="SILENT_THREAT_DNS"
CF_COMMENT="SILENT_HIVE_CLIENT_DNS"
GW="10.66.66.1"
CF_DST="1.1.1.1"
SUBNET="10.66.0.0/16"

SECRET=""
if [ -f "$ENV_FILE" ]; then
  SECRET=$(grep -E '^INTERNAL_API_SECRET=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r' | tr -d '"' | tr -d "'")
fi

ENABLED=false
if [ -n "$SECRET" ]; then
  RESP=$(curl -fsS --connect-timeout 3 --max-time 8 \
    -H "X-Internal-Secret: $SECRET" \
    "http://127.0.0.1:8000/api/vpn/internal/threat-filter" || echo '{"enabled":false}')
  ENABLED=$(echo "$RESP" | sed -n 's/.*"enabled"[[:space:]]*:[[:space:]]*\(true\|false\).*/\1/p' | head -1)
  [ -n "$ENABLED" ] || ENABLED=false
fi

ip addr show lo | grep -q "$GW" || ip addr add "$GW/32" dev lo 2>/dev/null || true

del_rules() {
  while iptables -t nat -C PREROUTING -s "$SUBNET" -p udp --dport 53 \
      -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT" 2>/dev/null; do
    iptables -t nat -D PREROUTING -s "$SUBNET" -p udp --dport 53 \
      -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT" || break
  done
  while iptables -t nat -C PREROUTING -s "$SUBNET" -p tcp --dport 53 \
      -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT" 2>/dev/null; do
    iptables -t nat -D PREROUTING -s "$SUBNET" -p tcp --dport 53 \
      -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT" || break
  done
}

add_rules() {
  iptables -t nat -C PREROUTING -s "$SUBNET" -p udp --dport 53 \
    -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT" 2>/dev/null || \
    iptables -t nat -A PREROUTING -s "$SUBNET" -p udp --dport 53 \
      -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT"
  iptables -t nat -C PREROUTING -s "$SUBNET" -p tcp --dport 53 \
    -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT" 2>/dev/null || \
    iptables -t nat -A PREROUTING -s "$SUBNET" -p tcp --dport 53 \
      -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT"
}

del_cf_rules() {
  while iptables -t nat -C PREROUTING -s "$SUBNET" -p udp --dport 53 \
      -j DNAT --to-destination "$CF_DST:53" -m comment --comment "$CF_COMMENT" 2>/dev/null; do
    iptables -t nat -D PREROUTING -s "$SUBNET" -p udp --dport 53 \
      -j DNAT --to-destination "$CF_DST:53" -m comment --comment "$CF_COMMENT" || break
  done
  while iptables -t nat -C PREROUTING -s "$SUBNET" -p tcp --dport 53 \
      -j DNAT --to-destination "$CF_DST:53" -m comment --comment "$CF_COMMENT" 2>/dev/null; do
    iptables -t nat -D PREROUTING -s "$SUBNET" -p tcp --dport 53 \
      -j DNAT --to-destination "$CF_DST:53" -m comment --comment "$CF_COMMENT" || break
  done
}

add_cf_rules() {
  iptables -t nat -C PREROUTING -s "$SUBNET" -p udp --dport 53 \
    -j DNAT --to-destination "$CF_DST:53" -m comment --comment "$CF_COMMENT" 2>/dev/null || \
    iptables -t nat -A PREROUTING -s "$SUBNET" -p udp --dport 53 \
      -j DNAT --to-destination "$CF_DST:53" -m comment --comment "$CF_COMMENT"
  iptables -t nat -C PREROUTING -s "$SUBNET" -p tcp --dport 53 \
    -j DNAT --to-destination "$CF_DST:53" -m comment --comment "$CF_COMMENT" 2>/dev/null || \
    iptables -t nat -A PREROUTING -s "$SUBNET" -p tcp --dport 53 \
      -j DNAT --to-destination "$CF_DST:53" -m comment --comment "$CF_COMMENT"
}

if [ "$ENABLED" = "true" ]; then
  systemctl start silent-threat-dns 2>/dev/null || true
  del_cf_rules
  add_rules
  echo "[threat-dns-sync] enabled=true threat DNAT on, CF off"
else
  del_rules
  add_cf_rules
  echo "[threat-dns-sync] enabled=false CF DNAT $CF_DST"
fi

echo "=== wdtt (must stay active, untouched) ==="
systemctl is-active wdtt || true
echo "=== nat :53 ==="
iptables -t nat -S PREROUTING 2>/dev/null | grep -- "--dport 53" || echo "(нет)"
"""


def threat_dns_sync_script() -> str:
    return THREAT_DNS_SYNC_SCRIPT
