"""Pure helpers: pick live GETCONF WireGuard peers to kick (no SSH/DB)."""
from __future__ import annotations

import time
from datetime import timezone

_CELL_LIVE_HS_SEC = 120.0
_QUEEN_SOLO_EXTRAS = 2
DEVICE_RECENT_SEC = 20 * 60
_LAST_CONNECTED_MATCH_SEC = 180.0


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
    """Choose GETCONF peers to cut for this device.

    On a cell leftover GETCONF keys are normal (n=5 in prod logs). The live
    session is the newest handshake — not a stale last_connected leftover.
    Queen has thousands of extras: never pick “newest of 90”.
    """
    # Incident 2026-08-16: picking newest extra on a cell removed other clients.
    return []
