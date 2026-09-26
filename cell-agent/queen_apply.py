"""Принять новый IP Улья на соте без правки кода и без рестарта wdtt."""
from __future__ import annotations

import ipaddress
import json
import os
import re
from pathlib import Path

QUEEN_STATE_PATH = Path("/etc/wdtt/hive_queen.json")
SOCAT_UNIT_PATH = Path("/etc/systemd/system/silent-tunnel-api-proxy.service")
AGENT_DROPIN_PATH = Path("/etc/systemd/system/silent-cell-agent.service.d/queen.conf")
_SOCAT_TCP_RE = re.compile(r"TCP:[0-9.]+(?::80|:8000)")


def parse_ipv4(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    return str(ipaddress.IPv4Address(text))


def should_apply_queen_ip(*, current: str, incoming: str) -> bool:
    try:
        new = parse_ipv4(incoming)
    except ValueError:
        return False
    if not new:
        return False
    try:
        old = parse_ipv4(current) if current else ""
    except ValueError:
        old = ""
    return new != old


def queen_state_dict(*, queen_ip: str, previous_ip: str = "", sibling_api_urls: list[str] | None = None) -> dict:
    return {
        "queen_ip": parse_ipv4(queen_ip),
        "previous_ip": (parse_ipv4(previous_ip) if previous_ip else ""),
        "sibling_api_urls": [u for u in (sibling_api_urls or []) if isinstance(u, str) and u.strip()],
    }


def read_queen_ip_from_state(raw: str) -> str:
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        return ""
    try:
        return parse_ipv4(str(data.get("queen_ip") or ""))
    except ValueError:
        return ""


def current_queen_ip(env_ip: str = "", state_path: Path = QUEEN_STATE_PATH) -> str:
    try:
        if state_path.is_file():
            ip = read_queen_ip_from_state(state_path.read_text(encoding="utf-8"))
            if ip:
                return ip
    except Exception:
        pass
    try:
        return parse_ipv4(env_ip) if env_ip else ""
    except ValueError:
        return (env_ip or "").strip()


def rewrite_socat_unit(text: str, new_ip: str) -> str:
    ip = parse_ipv4(new_ip)
    return _SOCAT_TCP_RE.sub(f"TCP:{ip}:80", text)


def agent_dropin_text(new_ip: str) -> str:
    ip = parse_ipv4(new_ip)
    return (
        "[Service]\n"
        f"Environment=HIVE_QUEEN_IP={ip}\n"
        f"Environment=HIVE_API_URL=https://{ip.replace('.', '-')}.nip.io\n"
    )


def sibling_queen_hint_urls(sibling_bases: list[str]) -> list[str]:
    out: list[str] = []
    for raw in sibling_bases or []:
        base = str(raw or "").strip().rstrip("/")
        if not base:
            continue
        url = f"{base}/health"
        if url not in out:
            out.append(url)
    return out


def parse_queen_hint(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    try:
        return parse_ipv4(str(payload.get("queen_ip") or ""))
    except ValueError:
        return ""


def env_queen_ip() -> str:
    return (os.environ.get("HIVE_QUEEN_IP") or "").strip()


def apply_queen_ip_on_host(
    incoming: str,
    *,
    sibling_api_urls: list[str] | None = None,
    agent_port: int = 9100,
) -> dict:
    """Пишет IP Улья, DNAT/socat и allow :9100. wdtt не трогает."""
    import subprocess

    new_ip = parse_ipv4(incoming)
    current = current_queen_ip(env_queen_ip())
    if not should_apply_queen_ip(current=current, incoming=new_ip):
        return {"ok": True, "applied": False, "queen_ip": current or new_ip}

    QUEEN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEEN_STATE_PATH.write_text(
        json.dumps(queen_state_dict(queen_ip=new_ip, previous_ip=current, sibling_api_urls=sibling_api_urls), ensure_ascii=False),
        encoding="utf-8",
    )
    AGENT_DROPIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    AGENT_DROPIN_PATH.write_text(agent_dropin_text(new_ip), encoding="utf-8")

    if SOCAT_UNIT_PATH.is_file():
        rewritten = rewrite_socat_unit(SOCAT_UNIT_PATH.read_text(encoding="utf-8"), new_ip)
        SOCAT_UNIT_PATH.write_text(rewritten, encoding="utf-8")
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=15)
        subprocess.run(
            ["systemctl", "restart", "silent-tunnel-api-proxy"],
            capture_output=True,
            timeout=20,
        )

    for dst in (f"{current}:80", f"{current}:8000", f"{new_ip}:80") if current else (f"{new_ip}:80",):
        subprocess.run(
            [
                "iptables", "-t", "nat", "-D", "PREROUTING",
                "-d", "10.66.66.1", "-p", "tcp", "--dport", "8000",
                "-j", "DNAT", "--to-destination", dst,
            ],
            capture_output=True,
            timeout=10,
        )
    subprocess.run(
        [
            "iptables", "-t", "nat", "-A", "PREROUTING",
            "-d", "10.66.66.1", "-p", "tcp", "--dport", "8000",
            "-j", "DNAT", "--to-destination", f"{new_ip}:80",
        ],
        capture_output=True,
        timeout=10,
    )
    if current:
        subprocess.run(
            [
                "iptables", "-t", "nat", "-D", "POSTROUTING",
                "-d", current, "-p", "tcp", "--dport", "80", "-j", "MASQUERADE",
            ],
            capture_output=True,
            timeout=10,
        )
    masquerade = [
        "iptables", "-t", "nat", "-C", "POSTROUTING",
        "-d", new_ip, "-p", "tcp", "--dport", "80", "-j", "MASQUERADE",
    ]
    if subprocess.run(masquerade, capture_output=True, timeout=10).returncode != 0:
        subprocess.run(
            [
                "iptables", "-t", "nat", "-A", "POSTROUTING",
                "-d", new_ip, "-p", "tcp", "--dport", "80", "-j", "MASQUERADE",
            ],
            capture_output=True,
            timeout=10,
        )

    subprocess.run(
        ["iptables", "-I", "INPUT", "-p", "tcp", "--dport", str(agent_port), "-s", new_ip, "-j", "ACCEPT"],
        capture_output=True,
        timeout=10,
    )
    subprocess.run(
        ["ufw", "--force", "allow", "from", new_ip, "to", "any", "port", str(agent_port), "proto", "tcp"],
        capture_output=True,
        timeout=15,
    )
    return {"ok": True, "applied": True, "queen_ip": new_ip, "previous_ip": current}
