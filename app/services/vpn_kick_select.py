"""Pure helpers: pick live GETCONF WireGuard peers to kick (no SSH/DB)."""
from __future__ import annotations

import time
from datetime import timezone

_CELL_LIVE_HS_SEC = 120.0
_QUEEN_SOLO_EXTRAS = 2
DEVICE_RECENT_SEC = 20 * 60
_LAST_CONNECTED_MATCH_SEC = 180.0
# GETCONF extras with no handshake, or handshake older than this, and not a Device key.
STALE_EXTRA_HS_SEC = 6 * 3600.0
NEVER_HS_GC_GRACE_SEC = 90.0


def should_keep_vpn_dataplane(
    *,
    is_admin: bool,
    in_test_mode: bool,
    has_live_test_plan: bool,
    has_active_subscription: bool,
) -> bool:
    """Fail-open: админ / глобальный тест / живой test-план / оплата. Режем только явный «нет»."""
    return bool(is_admin or in_test_mode or has_live_test_plan or has_active_subscription)


def valid_wg_pub(pub: str) -> bool:
    p = (pub or "").strip()
    return len(p) >= 40 and all(c.isalnum() or c in "+/=" for c in p)


def addr_ip(wg_address: str | None) -> str:
    raw = (wg_address or "").strip()
    if not raw:
        return ""
    return raw.split("/", 1)[0].strip()


class LivePeer:
    __slots__ = ("pub", "ip", "handshake_age")

    def __init__(self, pub: str, ip: str, handshake_age: float | None):
        self.pub = pub
        self.ip = ip
        self.handshake_age = handshake_age


def ts_epoch(ts) -> float | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc).timestamp()
    return ts.timestamp()


def device_looks_live(device, *, now: float | None = None, watch: bool = False) -> bool:
    if watch:
        return True
    if bool(getattr(device, "is_connected", False)):
        return True
    epoch = ts_epoch(getattr(device, "last_connected", None))
    if epoch is None:
        return False
    now_ts = time.time() if now is None else now
    return (now_ts - epoch) < DEVICE_RECENT_SEC


def parse_wg_show_dump(allowed_text: str, handshake_text: str, *, now: float | None = None) -> list[LivePeer]:
    """Parse `wg show wdtt0 allowed-ips` + `latest-handshakes`."""
    now_ts = time.time() if now is None else now
    ips: dict[str, str] = {}
    for line in (allowed_text or "").splitlines():
        parts = line.split()
        if len(parts) < 2 or not valid_wg_pub(parts[0]):
            continue
        ip = parts[1].split(",")[0].strip()
        ips[parts[0].strip()] = addr_ip(ip)
    ages: dict[str, float | None] = {}
    for line in (handshake_text or "").splitlines():
        parts = line.split()
        if len(parts) < 2 or not valid_wg_pub(parts[0]):
            continue
        try:
            ts = float(parts[1])
        except ValueError:
            continue
        if ts <= 0:
            ages[parts[0].strip()] = None
        else:
            ages[parts[0].strip()] = max(0.0, now_ts - ts)
    pubs = set(ips) | set(ages)
    return [LivePeer(pub=p, ip=ips.get(p, ""), handshake_age=ages.get(p)) for p in pubs]


def getconf_extras(live: list[LivePeer], known_pubs: set[str]) -> list[LivePeer]:
    """Peers GETCONF created on the node — not the API Device.wg_public_key."""
    extras = []
    for p in live:
        if not valid_wg_pub(p.pub) or p.pub in known_pubs:
            continue
        if p.handshake_age is None or p.handshake_age > 600:
            continue
        extras.append(p)
    extras.sort(key=lambda x: x.handshake_age if x.handshake_age is not None else 9e9)
    return extras


def _match_extra_by_last_connected_ts(
    last_connected,
    extras: list[LivePeer],
    now_ts: float,
) -> LivePeer | None:
    epoch = ts_epoch(last_connected)
    if epoch is None or not extras:
        return None
    best: LivePeer | None = None
    best_delta = 1e9
    for p in extras:
        if p.handshake_age is None:
            continue
        hs_unix = now_ts - p.handshake_age
        delta = abs(hs_unix - epoch)
        if delta < best_delta:
            best_delta = delta
            best = p
    if best is None or best_delta > _LAST_CONNECTED_MATCH_SEC:
        return None
    return best


def pick_getconf_extras(
    extras: list[LivePeer],
    *,
    on_queen: bool,
    device_is_live: bool,
    last_connected=None,
    now: float | None = None,
) -> list[LivePeer]:
    """Legacy helper — must stay empty.

    Incident 2026-08-16: picking the newest extra on a cell removed other clients.
    Use select_owned_getconf_extras (same IP / uniquely appeared extra).
    """
    return []


def snapshot_appeared(previous: set[str] | None, current_pubs: set[str]) -> tuple[set[str], set[str]]:
    """New pubs since last dump. First snapshot does not treat existing peers as new."""
    cur = {p.strip() for p in current_pubs if valid_wg_pub(p)}
    if previous is None:
        return set(), cur
    prev = {p.strip() for p in previous if valid_wg_pub(p)}
    return cur - prev, cur


def select_owned_getconf_extras(
    live: list[LivePeer],
    *,
    known_pubs: set[str],
    device_ip: str,
    appeared_pubs: set[str] | None = None,
    bound_pubs: set[str] | None = None,
    unique_watch_on_node: bool = False,
) -> list[LivePeer]:
    """GETCONF extras that belong to THIS device.

    Safe signals only:
    - allowed-ips IP equals this device's assigned address (exact, not substring)
    - extra pub we already bound to this device after a unique appear
    - exactly one new extra on the node while this is the only watched device
      (toggle after revoke). Never “newest of many” — that kicked strangers.
    """
    known = {p.strip() for p in known_pubs if valid_wg_pub(p)}
    bound = {p.strip() for p in (bound_pubs or set()) if valid_wg_pub(p)}
    appeared = {p.strip() for p in (appeared_pubs or set()) if valid_wg_pub(p)}
    ip = addr_ip(device_ip)
    by_pub = {p.pub: p for p in live if valid_wg_pub(p.pub)}
    out: dict[str, LivePeer] = {}

    if ip:
        for p in live:
            if not valid_wg_pub(p.pub) or p.pub in known:
                continue
            if p.ip == ip:
                out[p.pub] = p

    for pub in bound:
        if pub in known:
            continue
        peer = by_pub.get(pub)
        if peer is not None:
            out[pub] = peer

    if unique_watch_on_node:
        fresh = [
            p for p in live
            if p.pub in appeared and p.pub not in known
        ]
        # Только уникальный НОВЫЙ extra. «Единственный unknown на тихой ноде»
        # снимал платящих на Соте 2 (инцидент 2026-08-23).
        if len(fresh) == 1:
            out[fresh[0].pub] = fresh[0]

    return list(out.values())


LAST_CONNECTED_UNIQUE_SEC = 12.0
RESURRECT_STALE_SEC = 20.0
RESURRECT_FRESH_SEC = 8.0


def snapshot_ages(live: list[LivePeer]) -> dict[str, float | None]:
    return {p.pub: p.handshake_age for p in live if valid_wg_pub(p.pub)}


def select_extra_by_last_connected(
    live: list[LivePeer],
    last_connected,
    known_pubs: set[str],
    *,
    now: float | None = None,
    window_sec: float = LAST_CONNECTED_UNIQUE_SEC,
) -> list[LivePeer]:
    """Leftover GETCONF extra after toggle-off: handshake time ≈ last_connected.

    Only if exactly one extra matches. Two matches → guess, return empty
    (incident 2026-08-16 was “newest of many”).
    """
    epoch = ts_epoch(last_connected)
    if epoch is None:
        return []
    known = {p.strip() for p in known_pubs if valid_wg_pub(p)}
    now_ts = time.time() if now is None else now
    hits: list[LivePeer] = []
    for p in live:
        if not valid_wg_pub(p.pub) or p.pub in known or p.handshake_age is None:
            continue
        hs_unix = now_ts - p.handshake_age
        if abs(hs_unix - epoch) <= window_sec:
            hits.append(p)
    if len(hits) == 1:
        return hits
    return []


def select_resurrected_extras(
    live: list[LivePeer],
    prev_ages: dict[str, float | None] | None,
    known_pubs: set[str],
    *,
    stale_prev_sec: float = RESURRECT_STALE_SEC,
    fresh_now_sec: float = RESURRECT_FRESH_SEC,
) -> list[LivePeer]:
    """Cache extra came back: was stale/never-hs on this node, now handshake <8s.

    Unique resurrection only — two people reconnecting in the same window → skip.
    """
    if not prev_ages:
        return []
    known = {p.strip() for p in known_pubs if valid_wg_pub(p)}
    hits: list[LivePeer] = []
    for p in live:
        if not valid_wg_pub(p.pub) or p.pub in known:
            continue
        if p.handshake_age is None or p.handshake_age > fresh_now_sec:
            continue
        if p.pub not in prev_ages:
            continue
        prev = prev_ages.get(p.pub)
        if prev is None or prev >= stale_prev_sec:
            hits.append(p)
    if len(hits) == 1:
        return hits
    return []


def select_gc_extra_pubs(
    live: list[LivePeer],
    known_device_pubs: set[str],
    *,
    stale_hs_sec: float = STALE_EXTRA_HS_SEC,
) -> list[str]:
    """GETCONF leftovers: never-handshake or hs older than stale_hs_sec.

    Never removes Device.wg_public_key (connecting phone may still have hs=0).
    Never removes extras with a recent handshake (another live session).
    """
    known = {p.strip() for p in known_device_pubs if valid_wg_pub(p)}
    out: list[str] = []
    for p in live:
        if not valid_wg_pub(p.pub) or p.pub in known:
            continue
        if p.handshake_age is None:
            out.append(p.pub)
        elif p.handshake_age >= stale_hs_sec:
            out.append(p.pub)
    return out
