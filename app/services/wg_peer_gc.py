"""Снять мёртвые GETCONF WireGuard-peer’ы на Улье. wdtt не рестартим, ключи из БД не трогаем."""
from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Device
from app.services.vpn_kick import _queen_wg_dump, remove_wg_peers_batch_on_queen
from app.services.vpn_kick_select import NEVER_HS_GC_GRACE_SEC, select_gc_extra_pubs, valid_wg_pub

logger = logging.getLogger(__name__)

_pending_never_hs: dict[str, float] = {}
_last_gc_at = 0.0
_last_gc_log_at = 0.0
GC_EVERY_SEC = 90.0


async def known_device_pubs(db: AsyncSession) -> set[str]:
    rows = (
        await db.execute(
            select(Device.wg_public_key).where(
                Device.is_active == True,  # noqa: E712
                Device.wg_public_key.is_not(None),
            )
        )
    ).scalars().all()
    return {p.strip() for p in rows if p and valid_wg_pub(p)}


def _with_never_hs_grace(cands: list[str], *, grace_sec: float, now: float) -> list[str]:
    live = set(cands)
    for pub in list(_pending_never_hs):
        if pub not in live:
            _pending_never_hs.pop(pub, None)
    ready: list[str] = []
    for pub in cands:
        _pending_never_hs.setdefault(pub, now)
        if now - _pending_never_hs[pub] >= grace_sec:
            ready.append(pub)
    return ready


async def gc_stale_queen_peers(
    db: AsyncSession,
    *,
    grace_sec: float = NEVER_HS_GC_GRACE_SEC,
    batch: int = 40,
    limit: int = 120,
) -> dict:
    """Убрать extras: never-hs (после grace) и handshake >6ч. Ключи devices не трогаем."""
    global _last_gc_at, _last_gc_log_at
    now = time.time()
    if now - _last_gc_at < GC_EVERY_SEC and grace_sec > 0:
        return {"ok": True, "skipped": True}
    _last_gc_at = now
    known = await known_device_pubs(db)
    peers = _queen_wg_dump()
    cands = select_gc_extra_pubs(peers, known)
    now = time.time()
    # hs>6ч — сразу; never-hs — только если висели дольше grace (идёт connect).
    never = [p.pub for p in peers if p.pub in cands and p.handshake_age is None]
    stale = [p.pub for p in peers if p.pub in cands and p.handshake_age is not None]
    ready_never = _with_never_hs_grace(never, grace_sec=grace_sec, now=now)
    to_drop = (stale + ready_never)[:limit]
    if not to_drop:
        return {"ok": True, "removed": 0, "candidates": len(cands), "known": len(known)}
    removed = remove_wg_peers_batch_on_queen(to_drop, batch=batch)
    for pub in to_drop:
        _pending_never_hs.pop(pub, None)
    if removed and now - _last_gc_log_at > 30:
        _last_gc_log_at = now
        logger.info(
            "queen wg peer gc removed=%s never_ready=%s stale=%s known_keys=%s dump=%s",
            removed,
            len(ready_never),
            len(stale),
            len(known),
            len(peers),
        )
    return {
        "ok": True,
        "removed": removed,
        "candidates": len(cands),
        "known": len(known),
        "dump": len(peers),
    }


_QUEEN_WG_COUNTS_AT = 0.0
_QUEEN_WG_COUNTS: dict[str, int] | None = None
_QUEEN_WG_COUNTS_TTL_SEC = 8.0


def count_queen_wg_live_3m(*, window_sec: float = 180.0, known: set[str] | None = None) -> int:
    """Живые handshake на wdtt0 Улья. known — только ключи устройств этой ноды."""
    counts = queen_wg_peer_counts(known_connected=known, window_sec=window_sec)
    if known is not None:
        return int(counts.get("wg_peers_live_known") or 0)
    return int(counts.get("wg_peers_live_3m") or 0)


def queen_wg_peer_counts(
    *,
    known_connected: set[str] | None = None,
    window_sec: float = 180.0,
) -> dict[str, int]:
    global _QUEEN_WG_COUNTS_AT, _QUEEN_WG_COUNTS
    now = time.monotonic()
    if (
        known_connected is None
        and window_sec == 180.0
        and _QUEEN_WG_COUNTS is not None
        and (now - _QUEEN_WG_COUNTS_AT) < _QUEEN_WG_COUNTS_TTL_SEC
    ):
        return dict(_QUEEN_WG_COUNTS)
    try:
        peers = _queen_wg_dump()
    except Exception:
        return {
            "wg_peers_total": 0,
            "wg_peers_never_hs": 0,
            "wg_peers_live_3m": 0,
            "wg_peers_live_known": 0,
            "wg_gc_last_removed": 0,
        }
    never = live = live_known = 0
    known = known_connected or set()
    for p in peers:
        if p.handshake_age is None:
            never += 1
            continue
        if p.handshake_age < window_sec:
            live += 1
            if p.pub in known:
                live_known += 1
    out = {
        "wg_peers_total": len(peers),
        "wg_peers_never_hs": never,
        "wg_peers_live_3m": live,
        "wg_peers_live_known": live_known,
        "wg_gc_last_removed": 0,
    }
    if known_connected is None and window_sec == 180.0:
        _QUEEN_WG_COUNTS = dict(out)
        _QUEEN_WG_COUNTS_AT = now
    return out
