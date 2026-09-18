"""Запасной HTTPS-порт Улья. 443/22/wdtt никогда не закрываем.

Старые клиенты остаются на :443. Новые получают запасной порт в теме, если
с РФ хоть одна нода режет API (1/2 тоже — иначе флап никогда не даст 0/2).
Автосмена — живой кандидат с РФ только `open` (HTTPS слушает). `refused` — нет listener, не публикуем. 8443 запрещён (mtg).
"""
from __future__ import annotations

from dataclasses import dataclass, field

ACTION_HOLD = "hold"
ACTION_OPEN_CANDIDATE = "open_candidate"
ACTION_CLOSE_STALE_ALT = "close_stale_alt"

# Не открываем как «новый API» и не закрываем автоматом.
FORBIDDEN_PORTS = frozenset({22, 80, 8000, 9100, 56000, 56001, 1194, 51820, 500, 4500, 8443})
KEEP_FOREVER = frozenset({443, 22, 80, 8000, 56000, 56001})
CANDIDATE_ORDER = (2083, 2053, 2087, 2096)
REACHABLE = frozenset({"open"})


@dataclass
class PortPolicyInput:
    tcp_ok: int = 0
    tcp_fail: int = 0
    tls_ok: int = 0
    tls_fail: int = 0
    ping_ok: int = 0
    ping_fail: int = 0
    local_443_ok: bool = True
    consecutive_all_failed: int = 0
    confirm_cycles: int = 3
    autoswitch: bool = False
    open_ports: tuple[int, ...] = (443,)
    published_alt_ports: tuple[int, ...] = ()
    alt_grace_cycles: int = 0
    stale_alt_blocked: tuple[int, ...] = ()
    candidate_reach: dict[str, str] = field(default_factory=dict)


@dataclass
class PortPolicyDecision:
    action: str
    port: int | None = None
    suggested_port: int | None = None
    close_port: int | None = None
    keep_open: tuple[int, ...] = ()
    reason: str = ""


def _reach(inp: PortPolicyInput) -> dict[int, str]:
    out: dict[int, str] = {}
    for k, v in (inp.candidate_reach or {}).items():
        try:
            out[int(k)] = str(v or "").strip().lower()
        except (TypeError, ValueError):
            continue
    return out


def pick_candidate(reach: dict[int | str, str], *, skip: set[int] | None = None) -> int | None:
    skip = skip or set()
    norm: dict[int, str] = {}
    for k, v in (reach or {}).items():
        try:
            norm[int(k)] = str(v or "").strip().lower()
        except (TypeError, ValueError):
            continue
    for port in CANDIDATE_ORDER:
        if port in FORBIDDEN_PORTS or port in KEEP_FOREVER or port in skip:
            continue
        if norm.get(port) in REACHABLE:
            return port
    return None


def stale_published_ports(
    published: tuple[int, ...] | list[int],
    reach: dict[int | str, str] | None,
) -> tuple[int, ...]:
    """Опубликованный порт мёртв с РФ (timeout/refused). Без пробы не гадаем."""
    if not reach:
        return ()
    norm: dict[int, str] = {}
    for key, value in reach.items():
        try:
            norm[int(key)] = str(value or "").strip().lower()
        except (TypeError, ValueError):
            continue
    out: list[int] = []
    for port in published:
        status = norm.get(int(port), "")
        if status in ("timeout", "refused"):
            out.append(int(port))
    return tuple(out)


def alt_https_urls(domain: str, ip: str, ports: list[int] | tuple[int, ...]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for port in ports:
        p = int(port)
        if p == 443 or p in FORBIDDEN_PORTS:
            continue
        for host in (domain.strip(), ip.strip()):
            if not host:
                continue
            u = f"https://{host}:{p}"
            if u not in seen:
                seen.add(u)
                urls.append(u)
    return urls


def _keep(inp: PortPolicyInput) -> tuple[int, ...]:
    ports = set(inp.open_ports or ()) | set(KEEP_FOREVER)
    return tuple(sorted(p for p in ports if p > 0))


def _rf_api_block(inp: PortPolicyInput) -> bool:
    """Хоть одна российская нода не дошла до API — для части клиентов 443 мёртв."""
    return inp.tcp_fail > 0 or inp.tls_fail > 0


def decide_api_port_action(inp: PortPolicyInput) -> PortPolicyDecision:
    keep = _keep(inp)
    cand = pick_candidate(_reach(inp), skip=set(inp.open_ports or ()))
    if not inp.local_443_ok:
        return PortPolicyDecision(ACTION_HOLD, keep_open=keep, reason="local_443_down")
    if inp.tcp_ok == 0 and inp.tcp_fail > 0 and inp.ping_ok == 0 and inp.ping_fail > 0:
        return PortPolicyDecision(ACTION_HOLD, keep_open=keep, reason="ip_blackhole")

    stale = [p for p in (inp.stale_alt_blocked or ()) if p not in KEEP_FOREVER and p not in FORBIDDEN_PORTS]
    replacement = [p for p in (inp.published_alt_ports or ()) if p not in stale]
    if (
        inp.autoswitch
        and stale
        and replacement
        and inp.alt_grace_cycles >= max(3, inp.confirm_cycles)
    ):
        return PortPolicyDecision(
            ACTION_CLOSE_STALE_ALT,
            close_port=stale[0],
            keep_open=keep,
            reason="stale_alt",
        )

    live_pub = [
        p
        for p in (inp.published_alt_ports or ())
        if p not in stale and p not in KEEP_FOREVER and p not in FORBIDDEN_PORTS
    ]
    if live_pub:
        return PortPolicyDecision(
            ACTION_HOLD,
            suggested_port=live_pub[0],
            keep_open=keep,
            reason="already_open",
        )

    if not _rf_api_block(inp):
        return PortPolicyDecision(ACTION_HOLD, keep_open=keep, reason="partial_or_ok")

    if inp.autoswitch and cand:
        return PortPolicyDecision(
            ACTION_OPEN_CANDIDATE,
            port=cand,
            suggested_port=cand,
            keep_open=keep,
            reason="rf_block",
        )
    return PortPolicyDecision(
        ACTION_HOLD,
        suggested_port=cand,
        keep_open=keep,
        reason="dry_run" if cand else "no_candidate",
    )
