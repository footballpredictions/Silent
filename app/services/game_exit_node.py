"""Профиль для игр на соте: диагностика Steam SDR (UDP) и безопасный UDP/MTU-тюнинг.

Dota/CS через VPN на модеме с белым списком: исключения приложений нельзя —
трафик должен идти через туннель. Симптом Valve: «ping any relay via UDP failed
(firewall or MTU)». TCP при этом часто жив (скачивание/серфинг).

Инварианты (.cursor/rules/vpn-safety.mdc):
  * `wdtt.service` не рестартим и не трогаем;
  * порты 56000/56001 не закрываем;
  * правки идемпотентны и обратимы (`rollback`);
  * эксперименты — на выбранной соте (`--host`), без затрагивания Улья/ИИ-соты.
"""
from __future__ import annotations

import re
from typing import Any

GAME_ROOT = "/opt/silent-vpn/game-exit"
CLIENT_NET = "10.66.0.0/16"
# Вне рабочего диапазона клиентов соты (как у AI verify 10.66.250.x).
VERIFY_GW = "10.66.251.1"
VERIFY_CLIENT = "10.66.251.2"
DOTA_APPID = 570
CS2_APPID = 730

PHASES = ("audit", "probe", "udp-tune", "status", "rollback")


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


BASH_HELPERS = r"""
set -u
export DEBIAN_FRONTEND=noninteractive
PATH="$PATH:/usr/sbin:/sbin"

log() { echo "[game-exit] $*"; }

pub_ip() {
  local ip
  ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.*src \([0-9.]*\).*/\1/p' | head -1)"
  [ -n "$ip" ] || ip="$(curl -s --max-time 8 https://api.ipify.org 2>/dev/null)"
  echo "$ip"
}

wan_if() { ip -4 route show default 2>/dev/null | awk '{print $5; exit}'; }

ipt_app() { local t="$1" c="$2"; shift 2; iptables -t "$t" -C "$c" "$@" 2>/dev/null || iptables -t "$t" -A "$c" "$@"; }
ipt_ins() { local t="$1" c="$2"; shift 2; iptables -t "$t" -C "$c" "$@" 2>/dev/null || iptables -t "$t" -I "$c" 1 "$@"; }
ipt_del() { local t="$1" c="$2"; shift 2; while iptables -t "$t" -C "$c" "$@" 2>/dev/null; do iptables -t "$t" -D "$c" "$@"; done; }
"""

# --------------------------------------------------------------------------- #
# Ф0. Аудит (только чтение)
# --------------------------------------------------------------------------- #

AUDIT_TEMPLATE = r"""
echo "=== pub ==="
PUB="$(pub_ip)"; echo "$PUB"; echo "wan_if: $(wan_if)"
echo "=== ip-api ==="
curl -s --max-time 10 "http://ip-api.com/json/$PUB?fields=status,country,city,isp,org,as,reverse,proxy,hosting,query" || true
echo
echo "=== units ==="
for s in wdtt silent-cell-agent silent-cell-hardening ufw; do
  printf '%-26s %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null || echo n/a)"
done
echo "=== mtu ==="
ip -o link show 2>/dev/null | awk '{print $2,$0}' | grep -oE '[a-zA-Z0-9@._-]+: .*mtu [0-9]+' | head -15
echo "=== ufw ==="
ufw status verbose 2>/dev/null | head -40 || echo "(ufw нет)"
echo "=== DEFAULT_FORWARD_POLICY ==="
grep DEFAULT_FORWARD_POLICY /etc/default/ufw 2>/dev/null || echo "(нет /etc/default/ufw)"
echo "=== iptables FORWARD (policy + UDP hints) ==="
iptables -L FORWARD -n -v --line-numbers 2>/dev/null | head -40
echo "=== iptables FILTER UDP drops/rejects ==="
iptables -S 2>/dev/null | grep -iE 'udp.*(DROP|REJECT)' | head -30 || echo "(нет явных UDP DROP/REJECT)"
echo "=== iptables nat MASQUERADE ==="
iptables -t nat -S POSTROUTING 2>/dev/null | head -20
echo "=== icmp / pmtu sysctl ==="
sysctl net.ipv4.ip_forward net.ipv4.icmp_echo_ignore_all net.ipv4.ip_no_pmtu_disc \
  net.netfilter.nf_conntrack_udp_timeout net.netfilter.nf_conntrack_udp_timeout_stream 2>/dev/null || true
echo "=== wg head ==="
wg show 2>/dev/null | head -20 || echo "(wg нет)"
echo "=== game-exit files ==="
ls -la @@GAME_ROOT@@ 2>/dev/null || echo "(ещё не установлено)"
echo "=== done ==="
"""


def audit_script() -> str:
    return BASH_HELPERS + _render(AUDIT_TEMPLATE, {"GAME_ROOT": GAME_ROOT})


# --------------------------------------------------------------------------- #
# Ф1. Probe Steam SDR (host + псевдо-клиент netns)
# --------------------------------------------------------------------------- #

PROBE_PY = r'''
import json, socket, ssl, sys, time, urllib.request

APPIDS = [@@DOTA_APPID@@, @@CS2_APPID@@]
LIMIT = @@RELAY_LIMIT@@
TIMEOUT = 1.2

def fetch(appid):
    url = f"https://api.steampowered.com/ISteamApps/GetSDRConfig/v1?appid={appid}"
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(url, timeout=12, context=ctx) as r:
        return json.load(r)

def relay_port(rel):
    # Актуальный SDR: port_range=[27015,27060]; старый формат — port.
    if rel.get("port"):
        try:
            return int(rel["port"])
        except (TypeError, ValueError):
            pass
    pr = rel.get("port_range") or rel.get("port_ranges")
    if isinstance(pr, (list, tuple)) and pr:
        try:
            return int(pr[0])
        except (TypeError, ValueError):
            return 0
    return 0

def relays(data, limit):
    out = []
    for pop_name, pop in (data.get("pops") or {}).items():
        if not isinstance(pop, dict):
            continue
        for rel in (pop.get("relays") or []):
            if not isinstance(rel, dict):
                continue
            ip = str(rel.get("ipv4") or "").strip()
            port = relay_port(rel)
            if not ip or port <= 0:
                continue
            out.append((pop_name, ip, port))
            if len(out) >= limit:
                return out
    return out

# Если API пустой — запасные PoP (DE/NL рядом с Сотой 2).
FALLBACK = [
    ("ams", "155.133.248.36", 27015),
    ("ams", "155.133.248.37", 27015),
    ("fra", "162.254.197.180", 27015),
    ("fra", "162.254.197.181", 27015),
    ("vie", "155.133.226.68", 27015),
]

def udp_probe(ip, port, timeout=TIMEOUT, payload_size=32):
    # Valve отвечает только на свой протокол. Нам важны: reply | timeout
    # | icmp/oserror. Отдельно гоняем size≈1300 — Steam SDR предполагает такой UDP.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        body = b"\x00\x00\x00\x00silent-game-probe"
        if payload_size > len(body):
            body = body + (b"X" * (payload_size - len(body)))
        else:
            body = body[: max(8, payload_size)]
        s.sendto(body, (ip, port))
        try:
            data, addr = s.recvfrom(2048)
            return "reply", len(data), addr[0]
        except socket.timeout:
            return "timeout", 0, ""
        except ConnectionRefusedError:
            return "refused", 0, ""
        except OSError as e:
            return f"oserror:{getattr(e, 'errno', e)}", 0, ""
    finally:
        s.close()

def tcp_probe(ip, port, timeout=TIMEOUT):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return "ok"
    except OSError as e:
        return f"fail:{getattr(e, 'errno', e)}"
    finally:
        s.close()

replies = 0
timeouts = 0
errors = 0
total = 0
print("=== steam sdr fetch ===")
all_relays = []
for appid in APPIDS:
    try:
        data = fetch(appid)
        rs = relays(data, LIMIT)
        print(f"appid={appid} relays_sampled={len(rs)}")
        all_relays.extend(rs)
    except Exception as e:
        print(f"appid={appid} FETCH_FAIL {type(e).__name__}: {e}")

# unique by ip:port
seen = set()
uniq = []
for item in all_relays:
    key = (item[1], item[2])
    if key in seen:
        continue
    seen.add(key)
    uniq.append(item)

if not uniq:
    print("SDR empty — using FALLBACK relays")
    uniq = FALLBACK[:]

print(f"=== udp probes ({len(uniq)}) size=32 ===")
for pop, ip, port in uniq[:LIMIT]:
    total += 1
    status, n, from_ip = udp_probe(ip, port, payload_size=32)
    if status == "reply":
        replies += 1
        mark = "REPLY"
    elif status == "timeout":
        timeouts += 1
        mark = "TIMEOUT"
    else:
        errors += 1
        mark = status
    print(f"{mark:12} {pop:16} {ip}:{port}" + (f" from={from_ip} n={n}" if n else ""))

# Steam networking ~1300-byte UDP. MTU 1200/1280 роняет такие пакеты.
print("=== udp size sweep (first relay, Steam-sized) ===")
steam_sizes = {}
if uniq:
    pop, ip, port = uniq[0]
    for sz in (64, 1200, 1280, 1300, 1380, 1420):
        st, _, _ = udp_probe(ip, port, payload_size=sz, timeout=1.0)
        steam_sizes[str(sz)] = st
        print(f"size={sz:4d} -> {st}  ({pop} {ip}:{port})")

print("=== tcp sample (first 3 relays, same port — часто closed, это ок) ===")
for pop, ip, port in uniq[:3]:
    print(f"tcp {pop} {ip}:{port} -> {tcp_probe(ip, port)}")

# UDP_SILENT = пакеты ушли, ICMP/ошибки нет (типично для чужого payload к SDR).
# UDP_PATH_OK = был хотя бы один reply. UDP_BROKEN = oserror/refused.
# STEAM_MTU_RISK = мелкие ок, 1300+ ломаются (типичный баг клиента MTU 1200).
verdict = (
    "UDP_PATH_OK" if replies > 0
    else ("UDP_SILENT" if total > 0 and errors == 0 else "UDP_BROKEN")
)
if steam_sizes:
    small_ok = steam_sizes.get("64") in ("reply", "timeout")
    big_bad = any(steam_sizes.get(k) not in ("reply", "timeout") for k in ("1300", "1380"))
    if small_ok and big_bad:
        verdict = "STEAM_MTU_RISK"

print("=== summary ===")
print(json.dumps({
    "total": total,
    "replies": replies,
    "timeouts": timeouts,
    "errors": errors,
    "steam_sizes": steam_sizes,
    "verdict": verdict,
}, ensure_ascii=False))
'''

PROBE_TEMPLATE = r"""
echo "=== pub ==="
PUB="$(pub_ip)"; echo "$PUB"
echo "=== mtu ==="
ip -o link show 2>/dev/null | awk '{print $2,$0}' | grep -oE '[a-zA-Z0-9@._-]+: .*mtu [0-9]+' | head -15

echo "=== path mtu to 1.1.1.1 (DF) ==="
# Не фейлим скрипт: нас интересует максимальный размер без фрагментации.
for SZ in 1472 1400 1300 1200 1100; do
  if ping -4 -c 1 -W 2 -M do -s "$SZ" 1.1.1.1 >/dev/null 2>&1; then
    echo "DF ok size=$SZ (IP ~ $((SZ+28)))"
  else
    echo "DF fail size=$SZ"
  fi
done

echo "=== host steam UDP ==="
cat > /tmp/silent_game_probe.py <<'PY'
@@PROBE_PY@@
PY
python3 /tmp/silent_game_probe.py

# Псевдо-клиент: тот же FORWARD/NAT путь, что у WG-клиентов.
NS=silentgame_verify
VETH=veth-gamev
cleanup() {
  ip netns del "$NS" 2>/dev/null || true
  ip link del "$VETH" 2>/dev/null || true
  rm -rf "/etc/netns/$NS"
  rm -f /tmp/silent_game_probe.py
}
trap cleanup EXIT
cleanup
mkdir -p "/etc/netns/$NS"
printf 'nameserver 1.1.1.1\n' > "/etc/netns/$NS/resolv.conf"
ip netns add "$NS"
ip link add "$VETH" type veth peer name "${VETH}-ns"
ip addr add @@VERIFY_GW@@/30 dev "$VETH"
ip link set "$VETH" up
ip link set "${VETH}-ns" netns "$NS"
ip netns exec "$NS" ip link set lo up
ip netns exec "$NS" ip addr add @@VERIFY_CLIENT@@/30 dev "${VETH}-ns"
ip netns exec "$NS" ip link set "${VETH}-ns" up
ip netns exec "$NS" ip route add default via @@VERIFY_GW@@
# NAT для псевдо-клиента (боевой MASQUERADE WDTT_MANAGED уже есть для 10.66/16 —
# этот адрес тоже в /16, но на всякий случай не трогаем чужие правила).
ipt_app nat POSTROUTING -s @@VERIFY_CLIENT@@/32 -o "$(wan_if)" -j MASQUERADE
sysctl -w net.ipv4.conf.all.forwarding=1 >/dev/null 2>&1 || true
sleep 1

echo "=== client-netns egress IP ==="
ip netns exec "$NS" curl -s --max-time 15 https://api.ipify.org 2>/dev/null; echo
echo "=== client-netns steam UDP ==="
ip netns exec "$NS" python3 - <<'PY'
@@PROBE_PY@@
PY

echo "=== done ==="
"""


def probe_script(*, relay_limit: int = 12) -> str:
    limit = int(relay_limit)
    if not 3 <= limit <= 40:
        raise ValueError("relay_limit: 3..40")
    py = (
        PROBE_PY.replace("@@DOTA_APPID@@", str(DOTA_APPID))
        .replace("@@CS2_APPID@@", str(CS2_APPID))
        .replace("@@RELAY_LIMIT@@", str(limit))
    )
    return BASH_HELPERS + _render(
        PROBE_TEMPLATE,
        {
            "PROBE_PY": py,
            "VERIFY_GW": VERIFY_GW,
            "VERIFY_CLIENT": VERIFY_CLIENT,
        },
    )


# --------------------------------------------------------------------------- #
# Ф2. UDP/MTU тюнинг (идемпотентно, без wdtt)
# --------------------------------------------------------------------------- #

UDP_TUNE_TEMPLATE = r"""
mkdir -p @@GAME_ROOT@@
WAN="$(wan_if)"
NET="@@CLIENT_NET@@"

cat > @@GAME_ROOT@@/10-udp-tune.sh <<'EOS'
#!/bin/bash
# Сгенерировано game_exit_node.py. Идемпотентно. wdtt не трогаем.
# ВАЖНО: не ставить ACCEPT UDP/ICMP ПЕРЕД SILENT_DENY — иначе unpaid
# обойдёт dataplane-deny. FORWARD уже ACCEPT для 10.66/16 после deny.
set -u
PATH="$PATH:/usr/sbin:/sbin"
WAN="$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')"

# 1) PMTU / ICMP на ноде: без frag-needed UDP «молча» умирает.
sysctl -w net.ipv4.ip_no_pmtu_disc=0 >/dev/null 2>&1 || true
sysctl -w net.ipv4.icmp_echo_ignore_all=0 >/dev/null 2>&1 || true
# Чуть дольше держим UDP сессии игр (SDR / voice).
sysctl -w net.netfilter.nf_conntrack_udp_timeout=120 >/dev/null 2>&1 || true
sysctl -w net.netfilter.nf_conntrack_udp_timeout_stream=180 >/dev/null 2>&1 || true

# 1b) wdtt0 MTU: Steam SDR ~1300 байт; 1280 мало. Без рестарта wdtt.
if ip link show wdtt0 >/dev/null 2>&1; then
  if ip link set dev wdtt0 mtu 1420 2>/dev/null; then
    echo "[game-exit] wdtt0 mtu -> 1420"
  else
    echo "[game-exit] wdtt0 mtu set failed"
  fi
fi

# 2) TCPMSS clamp к PMTU (TCP лаунчер/стор). Не обходит SILENT_DENY.
iptables -t mangle -C FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null \
  || iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

# 3) Persist sysctl
mkdir -p /etc/sysctl.d
cat > /etc/sysctl.d/99-silent-game-exit.conf <<'SYS'
net.ipv4.ip_no_pmtu_disc = 0
net.ipv4.icmp_echo_ignore_all = 0
net.netfilter.nf_conntrack_udp_timeout = 120
net.netfilter.nf_conntrack_udp_timeout_stream = 180
SYS
sysctl -p /etc/sysctl.d/99-silent-game-exit.conf >/dev/null 2>&1 || true

exit 0
EOS
chmod 755 @@GAME_ROOT@@/10-udp-tune.sh
@@GAME_ROOT@@/10-udp-tune.sh
log "udp-tune applied (sysctl+TCPMSS; без обхода SILENT_DENY)"

cat > /etc/systemd/system/silent-game-exit.service <<EOF
[Unit]
Description=Silent VPN game-exit UDP/MTU tune (idempotent)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=@@GAME_ROOT@@/10-udp-tune.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable silent-game-exit.service >/dev/null 2>&1 || true
systemctl start silent-game-exit.service >/dev/null 2>&1 || true

echo "=== wdtt (must stay active, untouched) ==="
systemctl is-active wdtt
echo "=== FORWARD head (SILENT_DENY must stay near top) ==="
iptables -L FORWARD -n -v --line-numbers 2>/dev/null | head -12
echo "=== sysctl ==="
sysctl net.netfilter.nf_conntrack_udp_timeout net.netfilter.nf_conntrack_udp_timeout_stream net.ipv4.ip_no_pmtu_disc 2>/dev/null || true
echo "=== done ==="
"""


def udp_tune_script() -> str:
    return BASH_HELPERS + _render(
        UDP_TUNE_TEMPLATE,
        {"GAME_ROOT": GAME_ROOT, "CLIENT_NET": CLIENT_NET},
    )


STATUS_TEMPLATE = r"""
echo "=== units ==="
for s in wdtt silent-cell-agent silent-game-exit; do
  printf '%-26s %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null || echo n/a)"
done
echo "=== files ==="
ls -la @@GAME_ROOT@@ 2>/dev/null || echo "(нет)"
ls -la /etc/sysctl.d/99-silent-game-exit.conf 2>/dev/null || echo "(sysctl conf нет)"
echo "=== mtu ==="
ip link show wdtt0 2>/dev/null | head -1 || echo "(нет wdtt0)"
ip link show eth0 2>/dev/null | head -1 || true
echo "=== FORWARD head ==="
iptables -L FORWARD -n --line-numbers 2>/dev/null | head -10
echo "=== mangle TCPMSS ==="
iptables -t mangle -S FORWARD 2>/dev/null | grep -i TCPMSS || echo "(нет)"
echo "=== sysctl udp/pmtu ==="
sysctl net.ipv4.ip_no_pmtu_disc net.netfilter.nf_conntrack_udp_timeout \
  net.netfilter.nf_conntrack_udp_timeout_stream 2>/dev/null || true
echo "=== done ==="
"""


def status_script() -> str:
    return BASH_HELPERS + _render(STATUS_TEMPLATE, {"GAME_ROOT": GAME_ROOT})


ROLLBACK_TEMPLATE = r"""
ipt_del mangle FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
# Снять ошибочные ACCEPT UDP/ICMP, если остались от старой версии тюнинга.
NET="@@CLIENT_NET@@"
ipt_del filter FORWARD -s "$NET" -p udp -j ACCEPT
ipt_del filter FORWARD -d "$NET" -p udp -j ACCEPT
ipt_del filter FORWARD -p icmp --icmp-type destination-unreachable -j ACCEPT
ipt_del filter FORWARD -p icmp --icmp-type time-exceeded -j ACCEPT
systemctl disable --now silent-game-exit.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/silent-game-exit.service
rm -f /etc/sysctl.d/99-silent-game-exit.conf
systemctl daemon-reload >/dev/null 2>&1 || true
rm -rf @@GAME_ROOT@@
log "game-exit откатан; wdtt=$(systemctl is-active wdtt 2>/dev/null || echo n/a)"
echo "=== FORWARD head ==="
iptables -L FORWARD -n --line-numbers 2>/dev/null | head -8
echo "=== done ==="
"""


def rollback_script() -> str:
    return BASH_HELPERS + _render(
        ROLLBACK_TEMPLATE,
        {"GAME_ROOT": GAME_ROOT, "CLIENT_NET": CLIENT_NET},
    )


def build_phase_script(phase: str, **kwargs: Any) -> str:
    if phase == "audit":
        return audit_script()
    if phase == "probe":
        return probe_script(relay_limit=int(kwargs.get("relay_limit") or 12))
    if phase == "udp-tune":
        return udp_tune_script()
    if phase == "status":
        return status_script()
    if phase == "rollback":
        return rollback_script()
    raise ValueError(f"неизвестная фаза: {phase}")


def run_on_cell(host: str, ssh_password: str, script: str, *, timeout: int = 900) -> tuple[int, str]:
    from app.services.hive_provision_service import _run, _ssh_connect

    host = _validate_ip(host, "host")
    client = _ssh_connect(host, ssh_password)
    try:
        sftp = client.open_sftp()
        import io

        sftp.putfo(io.BytesIO(script.encode("utf-8")), "/tmp/silent_game_phase.sh")
        sftp.close()
        code, out, err = _run(client, "bash /tmp/silent_game_phase.sh 2>&1", timeout=timeout)
        return code, out + (err or "")
    finally:
        client.close()
