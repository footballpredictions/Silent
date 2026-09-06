"""AI-выход: гигиена egress, локальный DNS и транспарентный прокси на одной соте.

Модуль только **строит** bash-скрипты и конфиги и умеет выполнить их по SSH.
Применяется исключительно к соте с флагом `ai_exit` и только явной командой
`scripts/deploy_ai_cell.py` — никакой автоматики в рантайме API.

Инварианты (.cursor/rules/vpn-safety.mdc), которые здесь соблюдаются:
  * `wdtt.service` не рестартим и вообще не трогаем;
  * порты 56000/56001 остаются открытыми — от них зависят клиенты 1.0.160/1.0.161;
  * любое звено в разрыве трафика ставится только с fail-open watchdog:
    цепочка TPROXY подключается watchdog-ом и им же снимается, когда прокси нездоров.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import urlparse

AI_ROOT = "/opt/silent-vpn/ai-exit"
CONF_ROOT = "/etc/silent-ai"
CLIENT_NET = "10.66.0.0/16"
FILTER_DNS_IP = "10.66.66.1"
DNSMASQ_PORT = 5353
TPROXY_PORT = 7895
TPROXY_MARK = 1
TPROXY_TABLE = 100
TPROXY_CHAIN = "SILENT_AI_TP"
SINGBOX_DEFAULT_VERSION = "1.11.15"

#: Домены ИИ-сервисов, для которых включается отдельный маршрут (и, при Ф4, цепочка).
AI_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "openai.com",
    "chatgpt.com",
    "oaistatic.com",
    "oaiusercontent.com",
    "sora.com",
    "anthropic.com",
    "claude.ai",
    "gemini.google.com",
    "aistudio.google.com",
    "generativelanguage.googleapis.com",
    "makersuite.google.com",
    "notebooklm.google.com",
    "labs.google",
    "deepmind.google",
    "perplexity.ai",
    "x.ai",
    "grok.com",
    "mistral.ai",
    "copilot.microsoft.com",
    "githubcopilot.com",
    "cursor.com",
    "cursor.sh",
    "huggingface.co",
    "midjourney.com",
    "suno.com",
    "elevenlabs.io",
)

#: DoT-апстримы резолвера. Anycast, отвечают из США при запросе с US-ноды.
DOT_UPSTREAMS: tuple[tuple[str, str], ...] = (
    ("1.1.1.1", "cloudflare-dns.com"),
    ("1.0.0.1", "cloudflare-dns.com"),
    ("8.8.8.8", "dns.google"),
    ("8.8.4.4", "dns.google"),
)

PHASES = ("audit", "hygiene", "dns", "proxy", "verify", "status", "rollback")


def _render(template: str, values: dict[str, Any]) -> str:
    out = template
    for key, val in values.items():
        out = out.replace(f"@@{key}@@", str(val))
    leftover = re.findall(r"@@[A-Z0-9_]+@@", out)
    if leftover:
        raise ValueError(f"Не заполнены плейсхолдеры: {sorted(set(leftover))}")
    return out


def _validate_ip(value: str, what: str) -> str:
    ip = (value or "").strip()
    if not re.fullmatch(r"[0-9]{1,3}(\.[0-9]{1,3}){3}", ip):
        raise ValueError(f"{what}: ожидается IPv4, получено {value!r}")
    return ip


# --------------------------------------------------------------------------- #
# Общие bash-хелперы, которые нужны почти каждой фазе.
# --------------------------------------------------------------------------- #

BASH_HELPERS = r"""
set -u
export DEBIAN_FRONTEND=noninteractive
PATH="$PATH:/usr/sbin:/sbin"

log() { echo "[ai-exit] $*"; }

pub_ip() {
  local ip
  ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.*src \([0-9.]*\).*/\1/p' | head -1)"
  [ -n "$ip" ] || ip="$(curl -s --max-time 8 https://api.ipify.org 2>/dev/null)"
  echo "$ip"
}

wan_if() { ip -4 route show default 2>/dev/null | awk '{print $5; exit}'; }

# iptables ensure-хелперы: идемпотентно, без дублей.
ipt_app() { local t="$1" c="$2"; shift 2; iptables -t "$t" -C "$c" "$@" 2>/dev/null || iptables -t "$t" -A "$c" "$@"; }
ipt_ins() { local t="$1" c="$2"; shift 2; iptables -t "$t" -C "$c" "$@" 2>/dev/null || iptables -t "$t" -I "$c" 1 "$@"; }
ipt_del() { local t="$1" c="$2"; shift 2; while iptables -t "$t" -C "$c" "$@" 2>/dev/null; do iptables -t "$t" -D "$c" "$@"; done; }
"""


# --------------------------------------------------------------------------- #
# Ф0. Аудит (только чтение)
# --------------------------------------------------------------------------- #

AUDIT_TEMPLATE = r"""
echo "=== host ==="
hostname; uname -srm; head -2 /etc/os-release 2>/dev/null
echo "=== public ip ==="
PUB="$(pub_ip)"; echo "$PUB"; echo "wan_if: $(wan_if)"
echo "=== ip-api ==="
curl -s --max-time 10 "http://ip-api.com/json/$PUB?fields=status,country,city,isp,org,as,reverse,proxy,hosting,query" || true
echo
echo "=== ptr ==="
getent hosts "$PUB" || echo "(getent: нет PTR)"
echo "=== addresses ==="
ip -brief addr
echo "=== ipv6 default ==="
ip -6 route show default 2>/dev/null || true
echo "=== listening (внутри ноды) ==="
ss -lntup 2>/dev/null | head -40
echo "=== ufw ==="
ufw status verbose 2>/dev/null | head -30 || echo "(ufw нет)"
echo "=== iptables INPUT ==="
iptables -S INPUT 2>/dev/null | head -40
echo "=== iptables nat ==="
iptables -t nat -S 2>/dev/null | head -40
echo "=== iptables mangle ==="
iptables -t mangle -S 2>/dev/null | head -40
echo "=== resolv.conf ==="
cat /etc/resolv.conf 2>/dev/null
echo "=== units ==="
for s in wdtt silent-cell-agent unbound dnsmasq sing-box systemd-resolved silent-ai-rules silent-ai-watchdog.timer silent-ai-dnslist.timer; do
  printf '%-26s %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null || echo n/a)"
done
echo "=== wg ==="
wg show 2>/dev/null | head -24
echo "=== mtu ==="
ip -o link show 2>/dev/null | awk '{print $2, $0}' | grep -o '[a-z0-9@.]*: .*mtu [0-9]*' | head -10
echo "=== dns answers (с ноды) ==="
for d in chatgpt.com gemini.google.com claude.ai; do
  printf '%-24s %s\n' "$d" "$(getent ahostsv4 "$d" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ')"
done
echo "=== http (с ноды) ==="
for u in https://chatgpt.com/ https://gemini.google.com/ https://claude.ai/ https://api.openai.com/v1/models; do
  printf '%-40s %s\n' "$u" "$(curl -s -o /dev/null -w 'code=%{http_code} t=%{time_total}s' --max-time 15 "$u" 2>/dev/null)"
done
echo "=== cloudflare trace ==="
curl -s --max-time 10 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null | tr '\n' ' '; echo
echo "=== sysctl ==="
sysctl -n net.ipv4.ip_forward 2>/dev/null | sed 's/^/ip_forward=/'
sysctl -n net.ipv6.conf.all.disable_ipv6 2>/dev/null | sed 's/^/disable_ipv6=/'
echo "=== ai-exit files ==="
ls -la @@AI_ROOT@@ @@CONF_ROOT@@ 2>/dev/null || echo "(ещё не установлено)"
echo "=== done ==="
"""


def audit_script() -> str:
    """Read-only срез ноды: порты, PTR, DNS, ответы ИИ-доменов, наши юниты."""
    return BASH_HELPERS + _render(AUDIT_TEMPLATE, {"AI_ROOT": AI_ROOT, "CONF_ROOT": CONF_ROOT})


# --------------------------------------------------------------------------- #
# Ф1. Гигиена ноды
# --------------------------------------------------------------------------- #

HYGIENE_TEMPLATE = r"""
QUEEN_IP="@@QUEEN_IP@@"
AGENT_PORT="@@AGENT_PORT@@"
IPV6_MODE="@@IPV6_MODE@@"
SSH_ALLOW="@@SSH_ALLOW@@"

mkdir -p @@AI_ROOT@@ @@CONF_ROOT@@
chmod 700 @@CONF_ROOT@@

# --- 1. cell-agent :9100 виден только Улью -------------------------------- #
# Сначала разрешаем Улью, только потом убираем «открыто всем» — порядок важен,
# иначе сота выпадет из мониторинга.
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | head -1 | grep -qi active; then
  ufw --force allow from "$QUEEN_IP" to any port "$AGENT_PORT" proto tcp >/dev/null 2>&1 || true
  for _ in 1 2 3 4 5 6; do
    N="$(ufw status numbered 2>/dev/null | grep -E "^\[[ 0-9]+\][^#]*\<$AGENT_PORT/tcp\>[[:space:]]+ALLOW IN[[:space:]]+Anywhere" | head -1 | sed 's/^\[[[:space:]]*\([0-9]*\)\].*/\1/')"
    [ -n "$N" ] || break
    ufw --force delete "$N" >/dev/null 2>&1 || break
  done
  log "ufw: $AGENT_PORT/tcp только с $QUEEN_IP"
fi

if [ -n "$SSH_ALLOW" ]; then
  # SSH сужаем только если явно передан список — иначе легко потерять доступ.
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | head -1 | grep -qi active; then
    for A in $SSH_ALLOW; do ufw --force allow from "$A" to any port 22 proto tcp >/dev/null 2>&1 || true; done
    for _ in 1 2 3 4 5 6; do
      N="$(ufw status numbered 2>/dev/null | grep -E "^\[[ 0-9]+\][^#]*\<22/tcp\>[[:space:]]+ALLOW IN[[:space:]]+Anywhere" | head -1 | sed 's/^\[[[:space:]]*\([0-9]*\)\].*/\1/')"
      [ -n "$N" ] || break
      ufw --force delete "$N" >/dev/null 2>&1 || break
    done
    log "ufw: 22/tcp только с [$SSH_ALLOW]"
  fi
fi

# --- 2. Постоянные правила гигиены ---------------------------------------- #
cat > @@AI_ROOT@@/10-hygiene.sh <<'HYGEOS'
#!/bin/bash
# Сгенерировано backend/app/services/ai_exit_node.py. Идемпотентно, безопасно повторять.
set -u
PATH="$PATH:/usr/sbin:/sbin"
QUEEN_IP="__QUEEN_IP__"
AGENT_PORT="__AGENT_PORT__"
IPV6_MODE="__IPV6_MODE__"
WAN="$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')"

ipt_app() { local t="$1" c="$2"; shift 2; iptables -t "$t" -C "$c" "$@" 2>/dev/null || iptables -t "$t" -A "$c" "$@"; }
ipt_ins() { local t="$1" c="$2"; shift 2; iptables -t "$t" -C "$c" "$@" 2>/dev/null || iptables -t "$t" -I "$c" 1 "$@"; }

# cell-agent: Улей — да, интернет — нет. Порты 56000/56001 не трогаем (старые клиенты).
ipt_ins filter INPUT -p tcp --dport "$AGENT_PORT" -s "$QUEEN_IP" -j ACCEPT
ipt_ins filter INPUT -p tcp --dport "$AGENT_PORT" -s 127.0.0.1 -j ACCEPT
ipt_ins filter INPUT -p tcp --dport "$AGENT_PORT" -s 10.66.0.0/16 -j ACCEPT
ipt_app filter INPUT -p tcp --dport "$AGENT_PORT" -j DROP

# TTL наружу = 64: убирает разброс Windows(128)/Android(64) и число хопов клиента.
if [ -n "$WAN" ]; then
  modprobe xt_HL 2>/dev/null || true
  iptables -t mangle -C POSTROUTING -o "$WAN" -j TTL --ttl-set 64 2>/dev/null \
    || iptables -t mangle -A POSTROUTING -o "$WAN" -j TTL --ttl-set 64 2>/dev/null \
    || echo "[ai-exit] TTL-таргет недоступен, пропускаем"
fi

# IPv6 наружу: либо выключаем совсем (детерминированное гео), либо не трогаем.
if [ "$IPV6_MODE" = "off" ] && command -v ip6tables >/dev/null 2>&1; then
  ip6tables -C FORWARD -j DROP 2>/dev/null || ip6tables -A FORWARD -j DROP
  ip6tables -C OUTPUT -d 2000::/3 -j REJECT 2>/dev/null || ip6tables -A OUTPUT -d 2000::/3 -j REJECT
fi
exit 0
HYGEOS
sed -i "s|__QUEEN_IP__|$QUEEN_IP|; s|__AGENT_PORT__|$AGENT_PORT|; s|__IPV6_MODE__|$IPV6_MODE|" @@AI_ROOT@@/10-hygiene.sh
chmod 755 @@AI_ROOT@@/10-hygiene.sh

# glibc: предпочитать IPv4, чтобы A и AAAA не давали разное гео.
if [ "$IPV6_MODE" = "off" ]; then
  grep -q '^precedence ::ffff:0:0/96  100' /etc/gai.conf 2>/dev/null \
    || echo 'precedence ::ffff:0:0/96  100' >> /etc/gai.conf
fi

# --- 3. Юнит, который переигрывает правила после ребута -------------------- #
cat > /etc/systemd/system/silent-ai-rules.service <<'SVCEOS'
[Unit]
Description=Silent VPN AI exit: firewall/DNS rules (idempotent)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c 'for f in /opt/silent-vpn/ai-exit/[0-9]*.sh; do [ -x "$f" ] && "$f"; done; exit 0'

[Install]
WantedBy=multi-user.target
SVCEOS
systemctl daemon-reload
systemctl enable silent-ai-rules >/dev/null 2>&1 || true
@@AI_ROOT@@/10-hygiene.sh

# --- 4. Проверки ----------------------------------------------------------- #
log "cell-agent локально: $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:$AGENT_PORT/health)"
log "INPUT для $AGENT_PORT:"; iptables -S INPUT | grep -- "--dport $AGENT_PORT" || true
log "НАПОМИНАНИЕ: PTR (rDNS) для $(pub_ip) правится в панели HOSTKEY вручную — нейтральное имя без vpn/proxy/tunnel/wg."
echo "=== done ==="
"""


def hygiene_script(
    *,
    queen_ip: str,
    agent_port: int = 9100,
    ipv6_mode: str = "off",
    ssh_allow: Iterable[str] = (),
) -> str:
    """Ф1: закрыть cell-agent от интернета, нормализовать TTL, убрать IPv6-разнобой."""
    if ipv6_mode not in ("off", "keep"):
        raise ValueError("ipv6_mode: off | keep")
    allow = " ".join(_validate_ip(a, "ssh_allow") for a in ssh_allow)
    return BASH_HELPERS + _render(
        HYGIENE_TEMPLATE,
        {
            "QUEEN_IP": _validate_ip(queen_ip, "queen_ip"),
            "AGENT_PORT": int(agent_port),
            "IPV6_MODE": ipv6_mode,
            "SSH_ALLOW": allow,
            "AI_ROOT": AI_ROOT,
            "CONF_ROOT": CONF_ROOT,
        },
    )


# --------------------------------------------------------------------------- #
# Ф2. Свой резолвер на соте
# --------------------------------------------------------------------------- #

DNS_TEMPLATE = r"""
PUB="$(pub_ip)"
[ -n "$PUB" ] || { echo "Не определил публичный IP ноды"; exit 1; }
mkdir -p @@AI_ROOT@@ @@CONF_ROOT@@

log "ставим unbound + dnsmasq"
apt-get update -qq >/dev/null 2>&1 || true
apt-get install -y -qq unbound dnsmasq dnsutils ca-certificates >/dev/null 2>&1 || {
  echo "apt-get install не прошёл"; exit 1; }
systemctl stop dnsmasq >/dev/null 2>&1 || true

# --- unbound: DoT-стаб на 127.0.0.1:53, только IPv4, без ECS --------------- #
cat > /etc/unbound/unbound.conf.d/silent-ai.conf <<'UBEOS'
server:
    verbosity: 0
    interface: 127.0.0.1@53
    port: 53
    do-ip4: yes
    do-ip6: no
    prefer-ip4: yes
    do-udp: yes
    do-tcp: yes
    access-control: 0.0.0.0/0 refuse
    access-control: 127.0.0.0/8 allow
    hide-identity: yes
    hide-version: yes
    qname-minimisation: yes
    harden-glue: yes
    harden-dnssec-stripped: yes
    aggressive-nsec: yes
    edns-buffer-size: 1232
    cache-min-ttl: 60
    cache-max-ttl: 86400
    msg-cache-size: 64m
    rrset-cache-size: 128m
    num-threads: 2
    so-reuseport: yes
    tls-cert-bundle: "/etc/ssl/certs/ca-certificates.crt"

forward-zone:
    name: "."
    forward-tls-upstream: yes
@@FORWARD_ADDRS@@
UBEOS

# --- dnsmasq: лицо для клиентов, режет AAAA (иначе IPv6-утечка мимо туннеля) - #
TIF_LINE=""
if [ "@@THREAT_FILTER@@" = "on" ]; then
  if curl -sfL --max-time 90 "@@TIF_URL@@" -o @@CONF_ROOT@@/tif.dnsmasq.new 2>/dev/null \
     && [ -s @@CONF_ROOT@@/tif.dnsmasq.new ]; then
    mv @@CONF_ROOT@@/tif.dnsmasq.new @@CONF_ROOT@@/tif.dnsmasq
    TIF_LINE="conf-file=@@CONF_ROOT@@/tif.dnsmasq"
    log "HaGeZi TIF: $(grep -c . @@CONF_ROOT@@/tif.dnsmasq) строк"
  else
    rm -f @@CONF_ROOT@@/tif.dnsmasq.new
    log "список угроз не скачался — работаем без фильтра (fail-open)"
  fi
fi

write_dnsmasq() {
  cat > /etc/dnsmasq.d/silent-ai.conf <<DMEOS
# Silent VPN AI exit — резолвер для клиентов соты.
port=@@DNSMASQ_PORT@@
no-resolv
no-poll
server=127.0.0.1
cache-size=10000
min-cache-ttl=60
domain-needed
bogus-priv
log-async
$1
$TIF_LINE
DMEOS
}

write_dnsmasq "filter-AAAA"
if ! dnsmasq --test -C /etc/dnsmasq.conf >/dev/null 2>&1; then
  log "filter-AAAA не поддержан этой версией dnsmasq — выключаем"
  write_dnsmasq ""
fi

systemctl restart unbound
sleep 1
systemctl enable dnsmasq >/dev/null 2>&1 || true
systemctl restart dnsmasq
sleep 1

# Сама нода тоже резолвит через unbound.
if [ ! -f @@CONF_ROOT@@/resolv.conf.bak ]; then cp -a /etc/resolv.conf @@CONF_ROOT@@/resolv.conf.bak 2>/dev/null || true; fi
rm -f /etc/resolv.conf
printf '# Silent VPN AI exit\nnameserver 127.0.0.1\noptions timeout:2 attempts:2\n' > /etc/resolv.conf

# --- правила: клиентский :53 заворачиваем на свой dnsmasq ------------------ #
cat > @@AI_ROOT@@/20-dns.sh <<'DNSEOS'
#!/bin/bash
# Сгенерировано ai_exit_node.py. Клиентский DNS -> локальный dnsmasq соты.
set -u
PATH="$PATH:/usr/sbin:/sbin"
NET="__NET__"
PORT="__PORT__"
PUB="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.*src \([0-9.]*\).*/\1/p' | head -1)"
[ -n "$PUB" ] || exit 0

ipt_app() { local t="$1" c="$2"; shift 2; iptables -t "$t" -C "$c" "$@" 2>/dev/null || iptables -t "$t" -A "$c" "$@"; }
ipt_ins() { local t="$1" c="$2"; shift 2; iptables -t "$t" -C "$c" "$@" 2>/dev/null || iptables -t "$t" -I "$c" 1 "$@"; }

# Локальные запросы (сама нода, наши проверки) не должны попадать под DROP ниже.
ipt_ins filter INPUT -i lo -j ACCEPT

for P in udp tcp; do
  # Любой :53 от клиента (Яндекс, 10.66.66.1, что угодно) -> наш резолвер.
  ipt_app nat PREROUTING -s "$NET" -p "$P" --dport 53 ! -d "$PUB" -j DNAT --to-destination "$PUB:$PORT"
  ipt_ins filter INPUT -s "$NET" -p "$P" --dport "$PORT" -j ACCEPT
  ipt_app filter INPUT -p "$P" --dport "$PORT" -j DROP
done
exit 0
DNSEOS
sed -i "s|__NET__|@@CLIENT_NET@@|; s|__PORT__|@@DNSMASQ_PORT@@|" @@AI_ROOT@@/20-dns.sh
chmod 755 @@AI_ROOT@@/20-dns.sh
@@AI_ROOT@@/20-dns.sh

# --- обновление списка угроз раз в 6 часов --------------------------------- #
if [ "@@THREAT_FILTER@@" = "on" ]; then
cat > /etc/systemd/system/silent-ai-dnslist.service <<'LSTEOS'
[Unit]
Description=Silent VPN AI exit: refresh threat DNS list
[Service]
Type=oneshot
ExecStart=/bin/bash -c 'curl -sfL --max-time 120 "__URL__" -o /etc/silent-ai/tif.dnsmasq.new && [ -s /etc/silent-ai/tif.dnsmasq.new ] && mv /etc/silent-ai/tif.dnsmasq.new /etc/silent-ai/tif.dnsmasq && systemctl restart dnsmasq; exit 0'
LSTEOS
sed -i "s|__URL__|@@TIF_URL@@|" /etc/systemd/system/silent-ai-dnslist.service
cat > /etc/systemd/system/silent-ai-dnslist.timer <<'TMREOS'
[Unit]
Description=Silent VPN AI exit: refresh threat DNS list every 6h
[Timer]
OnBootSec=15min
OnUnitActiveSec=6h
[Install]
WantedBy=timers.target
TMREOS
systemctl daemon-reload
systemctl enable --now silent-ai-dnslist.timer >/dev/null 2>&1 || true
else
systemctl disable --now silent-ai-dnslist.timer >/dev/null 2>&1 || true
rm -f @@CONF_ROOT@@/tif.dnsmasq
fi

# --- проверки -------------------------------------------------------------- #
log "unbound: $(systemctl is-active unbound), dnsmasq: $(systemctl is-active dnsmasq)"
log "нода -> chatgpt.com: $(getent ahostsv4 chatgpt.com | awk '{print $1}' | sort -u | tr '\n' ' ')"
log "через dnsmasq: $(dig +short +time=3 +tries=1 @127.0.0.1 -p @@DNSMASQ_PORT@@ chatgpt.com A | tr '\n' ' ')"
log "AAAA (ожидаем пусто при filter-AAAA): $(dig +short +time=3 +tries=1 @127.0.0.1 -p @@DNSMASQ_PORT@@ chatgpt.com AAAA | tr '\n' ' ')"
echo "=== done ==="
"""


def dns_script(*, threat_filter_enabled: bool, tif_url: str | None = None) -> str:
    """Ф2: unbound (DoT, US) + dnsmasq (filter-AAAA) и заворот клиентского :53."""
    forward = "\n".join(
        f"    forward-addr: {ip}@853#{host}" for ip, host in DOT_UPSTREAMS
    )
    url = (tif_url or "https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/dnsmasq/tif.txt").strip()
    if not url.startswith("https://"):
        raise ValueError("tif_url должен быть https")
    return BASH_HELPERS + _render(
        DNS_TEMPLATE,
        {
            "AI_ROOT": AI_ROOT,
            "CONF_ROOT": CONF_ROOT,
            "CLIENT_NET": CLIENT_NET,
            "DNSMASQ_PORT": DNSMASQ_PORT,
            "FORWARD_ADDRS": forward,
            "THREAT_FILTER": "on" if threat_filter_enabled else "off",
            "TIF_URL": url,
        },
    )


# --------------------------------------------------------------------------- #
# Ф3/Ф4. Транспарентный прокси + опциональная цепочка
# --------------------------------------------------------------------------- #


def _parse_socks_url(url: str) -> dict[str, Any]:
    """socks5://user:pass@host:port -> outbound sing-box."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("socks5", "socks5h", "socks"):
        raise ValueError("chain: ожидается socks5://[user:pass@]host:port")
    if not parsed.hostname or not parsed.port:
        raise ValueError("chain: не хватает host:port")
    out: dict[str, Any] = {
        "type": "socks",
        "tag": "ai-out",
        "server": parsed.hostname,
        "server_port": int(parsed.port),
        "version": "5",
        "domain_strategy": "ipv4_only",
    }
    if parsed.username:
        out["username"] = parsed.username
        out["password"] = parsed.password or ""
    return out


#: Заглушки WARP-профиля: реальные ключи появляются только на ноде (wgcf register).
WARP_PLACEHOLDER = {
    "type": "wireguard",
    "tag": "ai-out",
    "server": "162.159.192.1",
    "server_port": 2408,
    "local_address": ["172.16.0.2/32"],
    "private_key": "__WARP_PRIVATE_KEY__",
    "peer_public_key": "__WARP_PEER_PUBLIC_KEY__",
    "mtu": 1280,
    "domain_strategy": "ipv4_only",
}


def chain_mode(chain_url: str | None) -> str:
    value = (chain_url or "").strip().lower()
    if not value or value == "direct":
        return "direct"
    if value == "warp":
        return "warp"
    return "socks"


def singbox_config(*, chain_url: str | None = None, domains: Iterable[str] = AI_DOMAIN_SUFFIXES) -> dict[str, Any]:
    """Конфиг sing-box: TPROXY-вход, sniff SNI, ИИ-домены отдельным outbound-ом.

    Без цепочки `ai-out` — тот же direct. Смысл всё равно есть: TCP терминируется
    на ноде, наружу уходит нормальный Linux-SYN (MSS 1460, TTL 64), а не
    туннельная аномалия клиента.
    """
    mode = chain_mode(chain_url)
    if mode == "warp":
        ai_out: dict[str, Any] = dict(WARP_PLACEHOLDER)
    elif mode == "socks":
        ai_out = _parse_socks_url(chain_url or "")
    else:
        ai_out = {"type": "direct", "tag": "ai-out", "domain_strategy": "ipv4_only"}
    return {
        "log": {"level": "warn", "timestamp": True},
        "dns": {
            "servers": [{"tag": "local", "address": "127.0.0.1", "detour": "direct"}],
            "strategy": "ipv4_only",
            "independent_cache": True,
        },
        "inbounds": [
            {
                "type": "tproxy",
                "tag": "tp-in",
                "listen": "0.0.0.0",
                "listen_port": TPROXY_PORT,
                "sniff": True,
                "sniff_override_destination": False,
                "tcp_fast_open": False,
            }
        ],
        "outbounds": [
            {"type": "direct", "tag": "direct", "domain_strategy": "ipv4_only"},
            ai_out,
            {"type": "block", "tag": "block"},
        ],
        "route": {
            "rules": [
                {"ip_is_private": True, "outbound": "direct"},
                {"domain_suffix": list(domains), "outbound": "ai-out"},
            ],
            "final": "direct",
            "auto_detect_interface": True,
        },
    }


PROXY_TEMPLATE = r"""
VER="@@SINGBOX_VERSION@@"
mkdir -p @@AI_ROOT@@ @@CONF_ROOT@@
chmod 700 @@CONF_ROOT@@

# --- 1. Бинарь sing-box ---------------------------------------------------- #
NEED=1
if [ -x /usr/local/bin/sing-box ] && /usr/local/bin/sing-box version 2>/dev/null | grep -q "$VER"; then NEED=0; fi
if [ "$NEED" = "1" ]; then
  ARCH=amd64; case "$(uname -m)" in aarch64|arm64) ARCH=arm64 ;; esac
  URL="https://github.com/SagerNet/sing-box/releases/download/v$VER/sing-box-$VER-linux-$ARCH.tar.gz"
  log "качаем $URL"
  rm -rf /tmp/sb && mkdir -p /tmp/sb
  if ! curl -sfL --max-time 180 "$URL" -o /tmp/sb/sb.tgz; then
    echo "Не скачался sing-box $VER — проверьте версию/сеть, ничего не меняли"; exit 1
  fi
  tar -xzf /tmp/sb/sb.tgz -C /tmp/sb
  install -m 0755 "$(find /tmp/sb -type f -name sing-box | head -1)" /usr/local/bin/sing-box
  rm -rf /tmp/sb
fi
/usr/local/bin/sing-box version | head -1

# --- 2. Конфиг ------------------------------------------------------------- #
cat > @@CONF_ROOT@@/sing-box.json <<'SBEOS'
@@SINGBOX_CONFIG@@
SBEOS
chmod 600 @@CONF_ROOT@@/sing-box.json

# --- 2б. Ф4: WARP вторым хопом только для ИИ-доменов ----------------------- #
if [ "@@CHAIN_MODE@@" = "warp" ]; then
  if [ ! -s @@CONF_ROOT@@/wgcf-profile.conf ]; then
    if [ ! -x /usr/local/bin/wgcf ]; then
      WGCF_URL="$(curl -sfL --max-time 30 https://api.github.com/repos/ViRb3/wgcf/releases/latest \
        | grep -o 'https://[^"]*linux_amd64' | head -1)"
      [ -n "$WGCF_URL" ] || { echo "Не нашёл релиз wgcf"; exit 1; }
      curl -sfL --max-time 120 "$WGCF_URL" -o /usr/local/bin/wgcf || { echo "wgcf не скачался"; exit 1; }
      chmod 755 /usr/local/bin/wgcf
    fi
    ( cd @@CONF_ROOT@@ && /usr/local/bin/wgcf register --accept-tos >/dev/null 2>&1 && /usr/local/bin/wgcf generate >/dev/null 2>&1 )
  fi
  [ -s @@CONF_ROOT@@/wgcf-profile.conf ] || { echo "Не получился профиль WARP — конфиг не трогаем"; exit 1; }
  chmod 600 @@CONF_ROOT@@/wgcf-*.toml @@CONF_ROOT@@/wgcf-profile.conf 2>/dev/null || true
  python3 - <<'PYEOS' || { echo "Не удалось вшить WARP в конфиг"; exit 1; }
import json, pathlib, re

prof = pathlib.Path("/etc/silent-ai/wgcf-profile.conf").read_text()

def val(key: str) -> str:
    m = re.search(rf"^{key}\s*=\s*(.+)$", prof, re.M)
    return m.group(1).strip() if m else ""

path = pathlib.Path("/etc/silent-ai/sing-box.json")
cfg = json.loads(path.read_text())
host, _, port = val("Endpoint").rpartition(":")
for out in cfg.get("outbounds", []):
    if out.get("tag") != "ai-out":
        continue
    out["private_key"] = val("PrivateKey")
    out["peer_public_key"] = val("PublicKey")
    addrs = [a.strip() for a in val("Address").split(",") if a.strip()]
    if addrs:
        out["local_address"] = addrs
    if host:
        out["server"] = host.strip("[]")
        out["server_port"] = int(port or 2408)
path.write_text(json.dumps(cfg, indent=2))
print("[ai-exit] WARP вшит в outbound ai-out")
PYEOS
fi

if ! /usr/local/bin/sing-box check -c @@CONF_ROOT@@/sing-box.json; then
  echo "sing-box check не прошёл — правила не трогаем"; exit 1
fi

# --- 3. Юнит --------------------------------------------------------------- #
cat > /etc/systemd/system/sing-box.service <<'SVCEOS'
[Unit]
Description=Silent VPN AI exit: sing-box transparent proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/sing-box run -c /etc/silent-ai/sing-box.json
Restart=always
RestartSec=2
LimitNOFILE=65535
MemoryMax=512M
CPUQuota=150%
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
SVCEOS

# --- 4. Watchdog: единственный, кто вешает и снимает цепочку TPROXY -------- #
cat > @@AI_ROOT@@/watchdog.sh <<'WDEOS'
#!/bin/bash
# Fail-open: правила TPROXY существуют, только пока sing-box реально жив.
set -u
PATH="$PATH:/usr/sbin:/sbin"
NET="__NET__"; PORT="__PORT__"; MARK="__MARK__"; TABLE="__TABLE__"; CHAIN="__CHAIN__"
PUB="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.*src \([0-9.]*\).*/\1/p' | head -1)"

hook_present() { iptables -t mangle -C PREROUTING -s "$NET" -j "$CHAIN" 2>/dev/null; }
remove_hook() { while hook_present; do iptables -t mangle -D PREROUTING -s "$NET" -j "$CHAIN"; done; }

healthy() {
  [ -f /etc/silent-ai/proxy.enabled ] || return 1
  systemctl is-active --quiet sing-box || return 1
  ss -lnt 2>/dev/null | grep -q ":$PORT " || return 1
  return 0
}

install_rules() {
  ip rule show 2>/dev/null | grep -q "lookup $TABLE" || ip rule add fwmark "$MARK" lookup "$TABLE" pref 100
  ip route show table "$TABLE" 2>/dev/null | grep -q 'local default' || ip route add local default dev lo table "$TABLE"
  iptables -t mangle -nL "$CHAIN" >/dev/null 2>&1 || iptables -t mangle -N "$CHAIN"
  iptables -t mangle -F "$CHAIN"
  for N in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4; do
    iptables -t mangle -A "$CHAIN" -d "$N" -j RETURN
  done
  [ -n "$PUB" ] && iptables -t mangle -A "$CHAIN" -d "$PUB" -j RETURN
  iptables -t mangle -A "$CHAIN" -p tcp -m multiport --dports 80,443 -j TPROXY --on-port "$PORT" --tproxy-mark "$MARK"
  iptables -t mangle -A "$CHAIN" -j RETURN
  hook_present || iptables -t mangle -A PREROUTING -s "$NET" -j "$CHAIN"
}

if healthy; then install_rules; else remove_hook; fi
exit 0
WDEOS
sed -i "s|__NET__|@@CLIENT_NET@@|; s|__PORT__|@@TPROXY_PORT@@|; s|__MARK__|@@TPROXY_MARK@@|; s|__TABLE__|@@TPROXY_TABLE@@|; s|__CHAIN__|@@TPROXY_CHAIN@@|" @@AI_ROOT@@/watchdog.sh
chmod 755 @@AI_ROOT@@/watchdog.sh

cat > /etc/systemd/system/silent-ai-watchdog.service <<'WSEOS'
[Unit]
Description=Silent VPN AI exit: TPROXY fail-open watchdog
[Service]
Type=oneshot
ExecStart=/opt/silent-vpn/ai-exit/watchdog.sh
WSEOS
cat > /etc/systemd/system/silent-ai-watchdog.timer <<'WTEOS'
[Unit]
Description=Silent VPN AI exit: watchdog every 20s
[Timer]
OnBootSec=30s
OnUnitActiveSec=20s
AccuracySec=5s
[Install]
WantedBy=timers.target
WTEOS

systemctl daemon-reload
systemctl enable sing-box >/dev/null 2>&1 || true
systemctl restart sing-box
sleep 2
if ! systemctl is-active --quiet sing-box; then
  journalctl -u sing-box -n 20 --no-pager | tail -20
  echo "sing-box не поднялся — цепочку не вешаем"; exit 1
fi

if [ "@@ENABLE@@" = "on" ]; then touch @@CONF_ROOT@@/proxy.enabled; else rm -f @@CONF_ROOT@@/proxy.enabled; fi
systemctl enable --now silent-ai-watchdog.timer >/dev/null 2>&1 || true
@@AI_ROOT@@/watchdog.sh

# --- 5. Проверки ----------------------------------------------------------- #
log "sing-box: $(systemctl is-active sing-box), listener: $(ss -lnt | grep -c ':@@TPROXY_PORT@@ ')"
log "mangle PREROUTING:"; iptables -t mangle -S PREROUTING | grep @@TPROXY_CHAIN@@ || log "(цепочка не подключена)"
log "через ноду наружу: $(curl -s -o /dev/null -w '%{http_code}' --max-time 12 https://chatgpt.com/)"
log "wdtt (не трогали): $(systemctl is-active wdtt)"
echo "=== done ==="
"""


def proxy_script(
    *,
    enable: bool = True,
    chain_url: str | None = None,
    singbox_version: str = SINGBOX_DEFAULT_VERSION,
    domains: Iterable[str] = AI_DOMAIN_SUFFIXES,
) -> str:
    """Ф3 (+Ф4 при chain_url): sing-box TPROXY с fail-open watchdog."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", singbox_version.strip()):
        raise ValueError("singbox_version: ожидается X.Y.Z")
    cfg = json.dumps(singbox_config(chain_url=chain_url, domains=domains), indent=2, ensure_ascii=False)
    if "SBEOS" in cfg:
        raise ValueError("конфиг содержит маркер heredoc")
    return BASH_HELPERS + _render(
        PROXY_TEMPLATE,
        {
            "AI_ROOT": AI_ROOT,
            "CONF_ROOT": CONF_ROOT,
            "CLIENT_NET": CLIENT_NET,
            "TPROXY_PORT": TPROXY_PORT,
            "TPROXY_MARK": TPROXY_MARK,
            "TPROXY_TABLE": TPROXY_TABLE,
            "TPROXY_CHAIN": TPROXY_CHAIN,
            "SINGBOX_VERSION": singbox_version.strip(),
            "SINGBOX_CONFIG": cfg,
            "CHAIN_MODE": chain_mode(chain_url),
            "ENABLE": "on" if enable else "off",
        },
    )


# --------------------------------------------------------------------------- #
# Статус и откат
# --------------------------------------------------------------------------- #

STATUS_TEMPLATE = r"""
echo "=== units ==="
for s in wdtt silent-cell-agent unbound dnsmasq sing-box silent-ai-rules silent-ai-watchdog.timer silent-ai-dnslist.timer; do
  printf '%-26s %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null || echo n/a)"
done
echo "=== цепочка для ИИ-доменов ==="
if [ -f @@CONF_ROOT@@/sing-box.json ]; then
  python3 -c "import json;c=json.load(open('@@CONF_ROOT@@/sing-box.json'));print(next((o['type'] for o in c['outbounds'] if o.get('tag')=='ai-out'),'нет'))" 2>/dev/null || echo "(не прочитал)"
else
  echo "(конфига нет)"
fi
echo "=== proxy switch ==="
[ -f @@CONF_ROOT@@/proxy.enabled ] && echo "proxy.enabled: да" || echo "proxy.enabled: нет (fail-open, трафик мимо прокси)"
echo "=== tproxy hook ==="
iptables -t mangle -S PREROUTING | grep @@TPROXY_CHAIN@@ || echo "(нет)"
echo "=== dns dnat ==="
iptables -t nat -S PREROUTING | grep -- "--dport 53" || echo "(нет)"
echo "=== agent port ==="
iptables -S INPUT | grep -- "--dport @@AGENT_PORT@@" || echo "(нет)"
echo "=== agent port со стороны, которой нет в белом списке ==="
# Нода стучится на свой же публичный IP: адрес не 127.0.0.1, не Улей, не 10.66/16,
# значит попадает под тот же DROP, что и любой сканер. Ожидаем 000.
printf 'http://%s:%s/health -> %s (ожидаем 000)\n' "$(pub_ip)" "@@AGENT_PORT@@" \
  "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://$(pub_ip):@@AGENT_PORT@@/health")"
echo "=== firewall backend ==="
iptables --version
iptables -L INPUT -n -v --line-numbers | head -20
if command -v iptables-legacy >/dev/null 2>&1; then echo "-- legacy --"; iptables-legacy -S INPUT 2>/dev/null | head -10; fi
if command -v nft >/dev/null 2>&1; then echo "-- nft --"; nft list ruleset 2>/dev/null | head -40; fi
echo "=== resolv.conf ==="
cat /etc/resolv.conf
echo "=== egress ==="
PUB="$(pub_ip)"; echo "ip: $PUB"
curl -s --max-time 10 "http://ip-api.com/json/$PUB?fields=country,city,as,reverse,proxy,hosting" || true; echo
for u in https://chatgpt.com/ https://gemini.google.com/ https://claude.ai/; do
  printf '%-32s %s\n' "$u" "$(curl -s -o /dev/null -w 'code=%{http_code}' --max-time 15 "$u" 2>/dev/null)"
done
echo "=== done ==="
"""


def status_script(*, agent_port: int = 9100) -> str:
    return BASH_HELPERS + _render(
        STATUS_TEMPLATE,
        {"CONF_ROOT": CONF_ROOT, "TPROXY_CHAIN": TPROXY_CHAIN, "AGENT_PORT": int(agent_port)},
    )


VERIFY_TEMPLATE = r"""
# Псевдо-клиент: veth в отдельном netns с адресом из клиентской сети.
# Его пакеты проходят тот же путь (PREROUTING/FORWARD), что и трафик из туннеля,
# поэтому это честная проверка DNS-заворота и TPROXY. Ничего постоянного не создаём.
NS=silentai_verify
VETH=veth-aiver

cleanup() {
  ip netns del "$NS" 2>/dev/null || true
  ip link del "$VETH" 2>/dev/null || true
  rm -rf "/etc/netns/$NS"
}
trap cleanup EXIT
cleanup

mkdir -p "/etc/netns/$NS"
# Намеренно «чужой» резолвер: если заворот работает, ответит наш dnsmasq.
printf 'nameserver 77.88.8.8\noptions timeout:3 attempts:1\n' > "/etc/netns/$NS/resolv.conf"

ip netns add "$NS"
ip link add "$VETH" type veth peer name "${VETH}-ns"
ip addr add @@VERIFY_GW@@/30 dev "$VETH"
ip link set "$VETH" up
ip link set "${VETH}-ns" netns "$NS"
ip netns exec "$NS" ip link set lo up
ip netns exec "$NS" ip addr add @@VERIFY_CLIENT@@/30 dev "${VETH}-ns"
ip netns exec "$NS" ip link set "${VETH}-ns" up
ip netns exec "$NS" ip route add default via @@VERIFY_GW@@
sleep 1

echo "=== DNS клиента (спрашивает 77.88.8.8) ==="
printf 'A    chatgpt.com -> %s\n' "$(ip netns exec "$NS" dig +short +time=3 +tries=1 @77.88.8.8 chatgpt.com A 2>/dev/null | tr '\n' ' ')"
printf 'AAAA chatgpt.com -> %s (ожидаем пусто)\n' "$(ip netns exec "$NS" dig +short +time=3 +tries=1 @77.88.8.8 chatgpt.com AAAA 2>/dev/null | tr '\n' ' ')"

echo "=== HTTP клиента ==="
# Голый curl Cloudflare режет почти везде — сравниваем с браузерным UA,
# иначе 403 легко принять за проблему репутации IP.
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
for u in https://chatgpt.com/ https://gemini.google.com/ https://claude.ai/ https://api.openai.com/v1/models; do
  printf '%-38s curl=%s браузерный-UA=%s\n' "$u" \
    "$(ip netns exec "$NS" curl -s -o /dev/null -w '%{http_code}' --max-time 25 "$u" 2>/dev/null)" \
    "$(ip netns exec "$NS" curl -s -o /dev/null -w '%{http_code}' --max-time 25 -H "User-Agent: $UA" -H 'Accept-Language: en-US,en;q=0.9' "$u" 2>/dev/null)"
done

echo "=== выходной IP клиента ==="
ip netns exec "$NS" curl -s --max-time 20 https://api.ipify.org 2>/dev/null; echo
echo "=== cloudflare trace клиента ==="
ip netns exec "$NS" curl -s --max-time 20 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null | tr '\n' ' '; echo

echo "=== счётчики TPROXY (пакеты должны быть > 0) ==="
iptables -t mangle -L @@TPROXY_CHAIN@@ -n -v 2>/dev/null | tail -4
echo "=== счётчики DNS-DNAT ==="
iptables -t nat -L PREROUTING -n -v 2>/dev/null | grep -- "dpt:53" || echo "(нет)"
echo "=== done ==="
"""


def verify_script() -> str:
    """Проверка глазами клиента: временный netns в клиентской сети, потом убирается."""
    return BASH_HELPERS + _render(
        VERIFY_TEMPLATE,
        {
            "VERIFY_GW": "10.66.250.1",
            "VERIFY_CLIENT": "10.66.250.2",
            "TPROXY_CHAIN": TPROXY_CHAIN,
        },
    )


ROLLBACK_TEMPLATE = r"""
SCOPE="@@SCOPE@@"

# Прокси снимаем всегда первым: сначала трафик мимо, потом всё остальное.
rm -f @@CONF_ROOT@@/proxy.enabled
[ -x @@AI_ROOT@@/watchdog.sh ] && @@AI_ROOT@@/watchdog.sh || true
while iptables -t mangle -C PREROUTING -s @@CLIENT_NET@@ -j @@TPROXY_CHAIN@@ 2>/dev/null; do
  iptables -t mangle -D PREROUTING -s @@CLIENT_NET@@ -j @@TPROXY_CHAIN@@
done
log "TPROXY снят"

if [ "$SCOPE" = "proxy" ]; then
  systemctl disable --now silent-ai-watchdog.timer >/dev/null 2>&1 || true
  systemctl disable --now sing-box >/dev/null 2>&1 || true
  echo "=== done ==="; exit 0
fi

# DNS: возвращаем клиентов на их собственный резолвер.
for P in udp tcp; do
  PUB="$(pub_ip)"
  while iptables -t nat -C PREROUTING -s @@CLIENT_NET@@ -p "$P" --dport 53 ! -d "$PUB" -j DNAT --to-destination "$PUB:@@DNSMASQ_PORT@@" 2>/dev/null; do
    iptables -t nat -D PREROUTING -s @@CLIENT_NET@@ -p "$P" --dport 53 ! -d "$PUB" -j DNAT --to-destination "$PUB:@@DNSMASQ_PORT@@"
  done
done
rm -f @@AI_ROOT@@/20-dns.sh
systemctl disable --now silent-ai-dnslist.timer >/dev/null 2>&1 || true
[ -f @@CONF_ROOT@@/resolv.conf.bak ] && cp -a @@CONF_ROOT@@/resolv.conf.bak /etc/resolv.conf || true
log "DNS-заворот снят"

if [ "$SCOPE" = "dns" ]; then echo "=== done ==="; exit 0; fi

# Гигиена: возвращаем cell-agent наружу (нужно, если сота теряет связь с Ульем).
while iptables -C INPUT -p tcp --dport @@AGENT_PORT@@ -j DROP 2>/dev/null; do
  iptables -D INPUT -p tcp --dport @@AGENT_PORT@@ -j DROP
done
command -v ufw >/dev/null 2>&1 && ufw --force allow @@AGENT_PORT@@/tcp >/dev/null 2>&1 || true
rm -f @@AI_ROOT@@/10-hygiene.sh
systemctl disable --now silent-ai-rules >/dev/null 2>&1 || true
log "гигиена откачена, cell-agent снова доступен"
log "wdtt: $(systemctl is-active wdtt) (не трогали)"
echo "=== done ==="
"""


def rollback_script(*, scope: str = "all", agent_port: int = 9100) -> str:
    """Откат. scope: proxy | dns | all — всегда снимает прокси первым."""
    if scope not in ("proxy", "dns", "all"):
        raise ValueError("scope: proxy | dns | all")
    return BASH_HELPERS + _render(
        ROLLBACK_TEMPLATE,
        {
            "SCOPE": scope,
            "AI_ROOT": AI_ROOT,
            "CONF_ROOT": CONF_ROOT,
            "CLIENT_NET": CLIENT_NET,
            "TPROXY_CHAIN": TPROXY_CHAIN,
            "DNSMASQ_PORT": DNSMASQ_PORT,
            "AGENT_PORT": int(agent_port),
        },
    )


# --------------------------------------------------------------------------- #
# Выполнение на соте
# --------------------------------------------------------------------------- #


def run_on_cell(host: str, ssh_password: str, script: str, *, timeout: int = 900) -> tuple[int, str]:
    """Выполнить сгенерированный скрипт на соте по SSH. Возвращает (код, вывод)."""
    from app.services.hive_provision_service import _run, _ssh_connect  # локальный импорт: paramiko

    client = _ssh_connect(host, ssh_password)
    try:
        sftp = client.open_sftp()
        import io

        sftp.putfo(io.BytesIO(script.encode("utf-8")), "/tmp/silent_ai_phase.sh")
        sftp.close()
        code, out, err = _run(client, "bash /tmp/silent_ai_phase.sh 2>&1", timeout=timeout)
        return code, out + (err or "")
    finally:
        client.close()


async def fetch_cell_egress(cell: Any, *, timeout: float = 40.0, with_http: bool = True) -> dict[str, Any]:
    """Спросить у cell-agent, как выглядит выход соты снаружи. Только чтение."""
    import httpx

    from app.core.security import decrypt_value
    from app.services.hive_service import _validate_outbound_url

    if not getattr(cell, "api_url", ""):
        raise ValueError("У соты нет cell-agent")
    enc = getattr(cell, "api_secret_enc", None)
    if not enc:
        raise ValueError("У соты не сохранён секрет cell-agent")
    try:
        secret = decrypt_value(enc)
    except Exception as e:  # noqa: BLE001
        raise ValueError("Не удалось расшифровать секрет соты") from e

    base = _validate_outbound_url(cell.api_url)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        resp = await client.post(
            f"{base}/v1/egress-check",
            headers={"X-Cell-Agent-Secret": secret},
            json={"timeout_sec": min(timeout - 5, 20), "with_http": bool(with_http)},
        )
    if resp.status_code == 404:
        raise ValueError("Старый cell-agent: обновите агента на соте (кнопка «Обновить агента»)")
    if resp.status_code >= 400:
        raise ValueError(f"cell-agent: HTTP {resp.status_code}")
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("cell-agent: неверный ответ")
    return data


def build_phase_script(phase: str, **kwargs: Any) -> str:
    if phase == "audit":
        return audit_script()
    if phase == "hygiene":
        return hygiene_script(**kwargs)
    if phase == "dns":
        return dns_script(**kwargs)
    if phase == "proxy":
        return proxy_script(**kwargs)
    if phase == "verify":
        return verify_script()
    if phase == "status":
        return status_script(**kwargs)
    if phase == "rollback":
        return rollback_script(**kwargs)
    raise ValueError(f"Неизвестная фаза {phase!r}, доступны: {', '.join(PHASES)}")
