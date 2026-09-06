"""Базовая гигиена соты: включённый фаервол, TTL наружу 64, egress без IPv6.

До 2026-09-06 сота после подключения жила с выключенным ufw и пустым `iptables
INPUT`: наружу торчало всё, что слушало на 0.0.0.0. Этот модуль строит bash-блок,
который закрывает такую соту сразу при провижининге
(`hive_provision_service.provision_cell_via_ssh`) и может быть применён к уже
работающей соте: `python scripts/deploy_ai_cell.py harden --host <ip>`.

Инварианты (.cursor/rules/vpn-safety.mdc):
  * 22/tcp, 56000/udp, 56001/udp остаются открытыми — на них держатся клиенты
    1.0.160/1.0.161, wdtt при этом не трогаем и не рестартим;
  * ufw включается только после `DEFAULT_FORWARD_POLICY=ACCEPT`, иначе на соте
    умирает транзит клиентского трафика;
  * порт cell-agent на обычной соте остаётся публичным намеренно: клиенты ходят
    на него как на запасной API, когда Улей недоступен (`standby_api_urls`).
    Сужает его только AI-профиль (`ai_exit_node.hygiene_script`) — сота с
    `ai_exit` из списка standby исключена.
"""
from __future__ import annotations

import re

HARDEN_ROOT = "/opt/silent-vpn/hardening"
HARDEN_UNIT = "silent-cell-hardening"
CLIENT_NET = "10.66.0.0/16"

#: Порты, которые обязаны остаться доступными снаружи (иначе падают старые клиенты).
KEEP_OPEN_UDP = (56000, 56001)
KEEP_OPEN_TCP = (22,)

_BASELINE_SH = r"""#!/bin/bash
# Сгенерировано backend/app/services/cell_hardening.py. Идемпотентно, безопасно повторять.
set -u
PATH="$PATH:/usr/sbin:/sbin"
IPV6_MODE="__IPV6_MODE__"
WAN="$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')"

# TTL наружу = 64: иначе по TTL видно ОС клиента (Windows 128, Android 64)
# и сколько хопов он прошёл до соты.
if [ -n "$WAN" ]; then
  modprobe xt_HL 2>/dev/null || true
  iptables -t mangle -C POSTROUTING -o "$WAN" -j TTL --ttl-set 64 2>/dev/null \
    || iptables -t mangle -A POSTROUTING -o "$WAN" -j TTL --ttl-set 64 2>/dev/null \
    || echo "[harden] TTL-таргет недоступен, пропускаем"
fi

# IPv6 наружу: клиентам отдаём только IPv4, чтобы A и AAAA не давали разное гео.
if [ "$IPV6_MODE" = "off" ] && command -v ip6tables >/dev/null 2>&1; then
  ip6tables -C FORWARD -j DROP 2>/dev/null || ip6tables -A FORWARD -j DROP
  ip6tables -C OUTPUT -d 2000::/3 -j REJECT 2>/dev/null || ip6tables -A OUTPUT -d 2000::/3 -j REJECT
fi

# Если на соте стоит AI-профиль — его правила строже, переигрываем их следом.
[ -x /opt/silent-vpn/ai-exit/10-hygiene.sh ] && /opt/silent-vpn/ai-exit/10-hygiene.sh >/dev/null 2>&1
exit 0
"""


def _validate_port(value: int, what: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"{what}: ожидается порт 1..65535, получено {value!r}")
    return port


def _validate_net(value: str) -> str:
    net = (value or "").strip()
    if not re.fullmatch(r"[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}", net):
        raise ValueError(f"vpn_net: ожидается IPv4/CIDR, получено {value!r}")
    return net


def baseline_setup_block(
    *,
    agent_port: int = 9100,
    vpn_net: str = CLIENT_NET,
    ipv6_mode: str = "off",
) -> str:
    """Bash-блок гигиены: кладёт скрипт, включает ufw, вешает юнит и применяет всё.

    Вставляется в скрипт провижининга и запускается фазой `harden`. Ничего не
    рестартит из VPN-сервисов: ufw только добавляет свои цепочки.
    """
    if ipv6_mode not in ("off", "keep"):
        raise ValueError("ipv6_mode: off | keep")
    port = _validate_port(agent_port, "agent_port")
    net = _validate_net(vpn_net)
    body = _BASELINE_SH.replace("__IPV6_MODE__", ipv6_mode)
    allow_tcp = "\n".join(f"  ufw allow {p}/tcp >/dev/null 2>&1 || true" for p in KEEP_OPEN_TCP)
    allow_udp = "\n".join(f"  ufw allow {p}/udp >/dev/null 2>&1 || true" for p in KEEP_OPEN_UDP)

    return f"""
echo "[harden] базовая гигиена соты..."
mkdir -p {HARDEN_ROOT}
cat > {HARDEN_ROOT}/10-baseline.sh << 'BASELINEEOS'
{body}BASELINEEOS
chmod 755 {HARDEN_ROOT}/10-baseline.sh

# glibc: предпочитать IPv4 — иначе часть соединений уходит по IPv6 с другим гео.
if [ "{ipv6_mode}" = "off" ]; then
  grep -q '^precedence ::ffff:0:0/96  100' /etc/gai.conf 2>/dev/null \
    || echo 'precedence ::ffff:0:0/96  100' >> /etc/gai.conf
fi

# ufw: до включения обязателен ACCEPT в FORWARD, иначе умрёт транзит клиентов.
if command -v ufw >/dev/null 2>&1; then
  sed -i 's/^DEFAULT_FORWARD_POLICY=.*/DEFAULT_FORWARD_POLICY="ACCEPT"/' /etc/default/ufw 2>/dev/null || true
{allow_tcp}
{allow_udp}
  ufw allow {port}/tcp >/dev/null 2>&1 || true
  ufw allow from {net} >/dev/null 2>&1 || true
  if ufw status 2>/dev/null | head -1 | grep -qi inactive; then
    ufw --force enable >/dev/null 2>&1 || true
  fi
  ufw status 2>/dev/null | head -12
fi

cat > /etc/systemd/system/{HARDEN_UNIT}.service << 'HARDENEOS'
[Unit]
Description=Silent VPN cell baseline hardening (idempotent)
After=network-online.target ufw.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c 'for f in {HARDEN_ROOT}/[0-9]*.sh; do [ -x "$f" ] && "$f"; done; exit 0'

[Install]
WantedBy=multi-user.target
HARDENEOS
systemctl daemon-reload
systemctl enable {HARDEN_UNIT} >/dev/null 2>&1 || true
{HARDEN_ROOT}/10-baseline.sh
echo "[harden] ufw: $(ufw status 2>/dev/null | head -1)"
"""


def harden_script(
    *,
    agent_port: int = 9100,
    vpn_net: str = CLIENT_NET,
    ipv6_mode: str = "off",
) -> str:
    """Готовый скрипт для запуска по SSH на уже подключённой соте."""
    head = 'set -u\nexport DEBIAN_FRONTEND=noninteractive\nPATH="$PATH:/usr/sbin:/sbin"\n'
    tail = (
        '\necho "=== TTL ==="; iptables -t mangle -S POSTROUTING | grep -- "--ttl-set" || echo "(нет)"\n'
        'echo "=== ipv6 ==="; ip6tables -S FORWARD 2>/dev/null | tail -2 || echo "(нет ip6tables)"\n'
        'echo "=== done ==="\n'
    )
    return head + baseline_setup_block(
        agent_port=agent_port, vpn_net=vpn_net, ipv6_mode=ipv6_mode
    ) + tail
