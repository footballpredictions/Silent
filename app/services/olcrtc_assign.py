"""Назначение комнаты olcrtc: sticky + max_clients + draining (плоскость отдельно от WDTT Hive)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.olcrtc_room import OlcrtcRoom, OlcrtcRoomSticky
from app.services.olcrtc_rooms_db import ensure_rooms_synced, room_to_dict
from app.services.olcrtc_settings import (
    DEFAULT_TRANSPORTS,
    load_olcrtc_settings,
    normalize_device_type,
    normalize_room_id,
)

logger = logging.getLogger(__name__)

HEARTBEAT_STALE_SEC = 120
NO_ROOM_DETAIL = (
    "Нет свободных комнат обхода (вариант 2). Попробуйте позже или другой провайдер."
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _matches_device(room: OlcrtcRoom, device_type: str) -> bool:
    dt = normalize_device_type(device_type) or device_type.strip().lower()
    dts = [str(x).lower() for x in (room.device_types or [])]
    if not dts:
        return True
    if dt and dt in dts:
        return True
    if dt and room.slot_label == dt:
        return True
    return False


def _device_type_for_sticky(device_type: str, room: OlcrtcRoom | None = None) -> str:
    """Канон sticky: pc|android из клиента, иначе slot_label комнаты."""
    dt = normalize_device_type(device_type)
    if dt:
        return dt
    if room is not None:
        slot = normalize_device_type(room.slot_label or "")
        if slot:
            return slot
        for x in room.device_types or []:
            cand = normalize_device_type(str(x))
            if cand:
                return cand
    return "pc"


async def _sticky_row(
    db: AsyncSession, fingerprint: str, provider: str, device_type: str
) -> OlcrtcRoomSticky | None:
    if not fingerprint.strip():
        return None
    result = await db.execute(
        select(OlcrtcRoomSticky).where(
            OlcrtcRoomSticky.fingerprint == fingerprint.strip()[:128],
            OlcrtcRoomSticky.provider == provider,
            OlcrtcRoomSticky.device_type == (normalize_device_type(device_type) or "pc"),
        )
    )
    return result.scalar_one_or_none()


async def _recount_room_online(db: AsyncSession, room: OlcrtcRoom) -> int:
    """online_count = число sticky на комнату (один fingerprint = один слот)."""
    result = await db.execute(
        select(func.count())
        .select_from(OlcrtcRoomSticky)
        .where(OlcrtcRoomSticky.room_id == room.id)
    )
    n = int(result.scalar() or 0)
    room.online_count = min(int(room.max_clients or 1), max(0, n))
    return int(room.online_count)


async def _save_sticky(
    db: AsyncSession,
    fingerprint: str,
    provider: str,
    device_type: str,
    room_id: uuid.UUID,
    *,
    commit: bool = True,
) -> None:
    fp = fingerprint.strip()[:128]
    if not fp:
        return
    dt = normalize_device_type(device_type) or "pc"
    # Убрать дубликаты того же fp+provider с другим device_type (баг slot_label vs android).
    await db.execute(
        delete(OlcrtcRoomSticky).where(
            OlcrtcRoomSticky.fingerprint == fp,
            OlcrtcRoomSticky.provider == provider,
            OlcrtcRoomSticky.device_type != dt,
        )
    )
    row = await _sticky_row(db, fp, provider, dt)
    if row:
        row.room_id = room_id
        row.updated_at = _now()
    else:
        db.add(
            OlcrtcRoomSticky(
                fingerprint=fp,
                provider=provider,
                device_type=dt,
                room_id=room_id,
            )
        )
    if commit:
        await db.commit()


async def _clear_sticky_fp_provider(
    db: AsyncSession,
    fingerprint: str,
    provider: str,
) -> int:
    fp = fingerprint.strip()[:128]
    if not fp or not provider:
        return 0
    res = await db.execute(
        delete(OlcrtcRoomSticky).where(
            OlcrtcRoomSticky.fingerprint == fp,
            OlcrtcRoomSticky.provider == provider,
        )
    )
    return int(res.rowcount or 0)


def _room_accepts_new(room: OlcrtcRoom, *, allow_overflow_sticky: bool = False) -> bool:
    if room.status == "draining":
        return allow_overflow_sticky
    if room.status != "active":
        return False
    if allow_overflow_sticky:
        return True
    return int(room.online_count or 0) < int(room.max_clients or 1)


async def pick_room(
    db: AsyncSession,
    *,
    provider: str,
    device_type: str = "",
    fingerprint: str = "",
    reserve: bool = True,
) -> OlcrtcRoom | None:
    """Выдать комнату.
    reserve=True — sticky + online (только выбранный провайдер).
    reserve=False — peek URL без sticky (остальные провайдеры в ответе конфига).
    """
    await ensure_rooms_synced(db)
    dt = normalize_device_type(device_type) or "pc"
    fp = fingerprint.strip()

    sticky = await _sticky_row(db, fp, provider, dt)
    if sticky:
        room = await db.get(OlcrtcRoom, sticky.room_id)
        if room and _matches_device(room, dt) and _room_accepts_new(
            room, allow_overflow_sticky=(room.status == "draining" or room.status == "active")
        ):
            if room.status == "active" and int(room.online_count or 0) >= int(room.max_clients or 1):
                pass
            elif room.status in ("active", "draining"):
                sticky.updated_at = _now()
                if reserve:
                    await _recount_room_online(db, room)
                await db.commit()
                return room

    result = await db.execute(
        select(OlcrtcRoom)
        .where(OlcrtcRoom.provider == provider, OlcrtcRoom.status == "active")
        .order_by(OlcrtcRoom.online_count.asc(), OlcrtcRoom.created_at.asc())
        .with_for_update(skip_locked=True)
    )
    chosen: OlcrtcRoom | None = None
    for r in result.scalars().all():
        if _matches_device(r, dt) and _room_accepts_new(r):
            chosen = r
            break
    if not chosen:
        return None
    if reserve and fp:
        await _save_sticky(db, fp, provider, dt, chosen.id, commit=False)
        await _recount_room_online(db, chosen)
        chosen.last_healthy_at = _now()
        await db.commit()
    else:
        # peek: без commit sticky — только URL для UI / переключения
        await db.commit()
    return chosen


async def assign_public_config(
    db: AsyncSession,
    *,
    device_type: str = "",
    fingerprint: str = "",
    preferred_provider: str = "",
) -> dict[str, Any]:
    """room из БД-пула. Sticky/online только у preferred_provider (иначе оба Telemost+WB online)."""
    settings = await load_olcrtc_settings(db)
    wb = settings.providers.get("wbstream")
    if wb and wb.enabled and not (wb.auth_token or "").strip():
        try:
            from app.services.olcrtc_room_accounts import resolve_wbstream_access_token

            tok = await resolve_wbstream_access_token(db)
            if tok:
                wb.auth_token = tok
        except Exception:
            pass
    key_ok = len(settings.crypto_key) == 64
    providers_out: dict[str, Any] = {}
    assigned_slot = ""
    any_provider_ok = False
    wanted_enabled = 0
    dt = normalize_device_type(device_type)
    fp = fingerprint.strip()
    pref = (preferred_provider or "").strip().lower()
    if pref not in settings.providers:
        # дефолт — первый включённый (клиент всегда шлёт свой выбор)
        for name, p in settings.providers.items():
            if p.enabled:
                pref = name
                break

    # Снять sticky других провайдеров — в online только выбранный канал.
    if fp and pref:
        others = (
            await db.execute(
                select(OlcrtcRoomSticky).where(
                    OlcrtcRoomSticky.fingerprint == fp[:128],
                    OlcrtcRoomSticky.provider != pref,
                )
            )
        ).scalars().all()
        affected = {st.room_id for st in others}
        if others:
            await db.execute(
                delete(OlcrtcRoomSticky).where(
                    OlcrtcRoomSticky.fingerprint == fp[:128],
                    OlcrtcRoomSticky.provider != pref,
                )
            )
            for room_id in affected:
                room = await db.get(OlcrtcRoom, room_id)
                if room:
                    await _recount_room_online(db, room)
            await db.commit()

    for name, p in settings.providers.items():
        room_url = ""
        room_slot = ""
        room_uuid = ""
        enabled = bool(settings.enabled and p.enabled and key_ok)
        denied = False
        if enabled:
            wanted_enabled += 1
            reserve = bool(fp and pref and name == pref)
            room = await pick_room(
                db,
                provider=name,
                device_type=device_type,
                fingerprint=fingerprint,
                reserve=reserve,
            )
            if room:
                room_url = normalize_room_id(name, room.room_url)
                room_slot = room.slot_label
                room_uuid = str(room.id)
                any_provider_ok = True
                if reserve and not assigned_slot:
                    assigned_slot = room.unit_name or room.slot_label
                elif not assigned_slot and name == pref:
                    assigned_slot = room.unit_name or room.slot_label
            else:
                enabled = False
                denied = True
        providers_out[name] = {
            "enabled": enabled,
            "room": room_url if enabled else "",
            "transport": p.transport or DEFAULT_TRANSPORTS[name],
            "room_slot_id": room_slot if enabled else "",
            "room_db_id": room_uuid if enabled else "",
            "rooms_count": 0,
            "denied": denied,
        }

    for name in providers_out:
        result = await db.execute(
            select(OlcrtcRoom).where(
                OlcrtcRoom.provider == name, OlcrtcRoom.status == "active"
            )
        )
        providers_out[name]["rooms_count"] = len(list(result.scalars().all()))

    pool_denied = bool(settings.enabled and key_ok and wanted_enabled > 0 and not any_provider_ok)

    return {
        "enabled": bool(settings.enabled and key_ok),
        "crypto_key": settings.crypto_key if (settings.enabled and key_ok) else "",
        "providers": providers_out,
        "socks_host": "127.0.0.1",
        "socks_port": 8808,
        "assigned_slot": assigned_slot,
        "device_type": dt,
        "jitsi_https_proxy": "",
        "pool_denied": pool_denied,
        "pool_denied_detail": NO_ROOM_DETAIL if pool_denied else "",
        "preferred_provider": pref,
    }


async def report_room_failure(
    db: AsyncSession,
    *,
    room_db_id: str = "",
    fingerprint: str = "",
    provider: str = "",
    device_type: str = "",
    detail: str = "",
) -> dict[str, Any]:
    """Клиент: peer/room dead → снять sticky; при фатале комнаты — status=error (агент пересоздаст)."""
    await ensure_rooms_synced(db)
    cleared_sticky = 0
    marked_error = 0
    affected_rooms: set[uuid.UUID] = set()
    fp = fingerprint.strip()
    prov = (provider or "").strip().lower()
    detail_l = (detail or "").lower()
    # Фатал комнаты (не «личный» дисконнект): guest 403 / 404 / host не в комнате.
    room_fatal = any(
        x in detail_l
        for x in (
            "guests cannot create",
            "гост",
            "мертв",
            "not found",
            "status 404",
            "status 403",
            "wait for peer",
            "peer srv",
            "auth.token",
            "invalid_token",
            "liveness",
        )
    )
    if (room_db_id or "").strip():
        try:
            affected_rooms.add(uuid.UUID(room_db_id.strip()))
        except ValueError:
            pass
    if fp and prov:
        rows = (
            await db.execute(
                select(OlcrtcRoomSticky).where(
                    OlcrtcRoomSticky.fingerprint == fp[:128],
                    OlcrtcRoomSticky.provider == prov,
                )
            )
        ).scalars().all()
        for st in rows:
            affected_rooms.add(st.room_id)
        cleared_sticky += await _clear_sticky_fp_provider(db, fp, prov)
    for room_id in affected_rooms:
        room = await db.get(OlcrtcRoom, room_id)
        if room:
            await _recount_room_online(db, room)
            if detail:
                room.last_error = detail[:500]
            if room_fatal and room.status == "active":
                room.status = "error"
                marked_error += 1
    await db.commit()
    logger.warning(
        "olcrtc room failure room=%s provider=%s fp=%s sticky=%s error=%s detail=%s",
        room_db_id,
        prov,
        fp[:12],
        cleared_sticky,
        marked_error,
        (detail or "")[:80],
    )
    return {
        "ok": True,
        "marked_error": marked_error > 0,
        "sticky_cleared": cleared_sticky,
        "hint": "fetch /olcrtc-config again for a new room",
    }


async def heartbeat(
    db: AsyncSession,
    *,
    room_db_id: str,
    fingerprint: str = "",
    provider: str = "",
    device_type: str = "",
    online: bool = True,
) -> dict[str, Any]:
    """Держит online через sticky. online=false — leave (удаляет sticky + recount)."""
    try:
        rid = uuid.UUID(room_db_id)
    except ValueError:
        return {"ok": False, "detail": "bad room_db_id"}
    room = await db.get(OlcrtcRoom, rid)
    if not room:
        return {"ok": False, "detail": "room not found"}

    prov = (provider or room.provider or "").strip().lower()
    dt = _device_type_for_sticky(device_type, room)
    fp = fingerprint.strip()

    if online:
        room.last_healthy_at = _now()
        if fp:
            await _save_sticky(db, fp, prov, dt, room.id, commit=False)
        await _recount_room_online(db, room)
    else:
        if fp and prov:
            await _clear_sticky_fp_provider(db, fp, prov)
        await _recount_room_online(db, room)

    await db.commit()
    return {"ok": True, "room": room_to_dict(room)}


async def reconcile_stale_online(db: AsyncSession) -> int:
    """Снять sticky без heartbeat и пересчитать online_count."""
    cutoff = _now() - timedelta(seconds=HEARTBEAT_STALE_SEC)
    stale = (
        await db.execute(
            select(OlcrtcRoomSticky).where(OlcrtcRoomSticky.updated_at < cutoff)
        )
    ).scalars().all()
    affected = {st.room_id for st in stale}
    if stale:
        await db.execute(
            delete(OlcrtcRoomSticky).where(OlcrtcRoomSticky.updated_at < cutoff)
        )
    # Комнаты с online>0 без sticky — тоже выровнять
    rooms = (
        await db.execute(
            select(OlcrtcRoom).where(OlcrtcRoom.status == "active")
        )
    ).scalars().all()
    fixed = 0
    for room in rooms:
        if room.id in affected or int(room.online_count or 0) > 0:
            before = int(room.online_count or 0)
            await _recount_room_online(db, room)
            if int(room.online_count or 0) != before:
                fixed += 1
    if fixed or stale:
        await db.commit()
    return fixed + len(stale)


async def pick_cell_for_new_room(db: AsyncSession):
    """Placement комнаты на соту: queen по умолчанию, worker при overload queen olcrtc."""
    from app.services.hive_service import ensure_queen_cell, _list_assignable_cells
    from app.services.olcrtc_rooms_db import list_rooms

    queen = await ensure_queen_cell(db)
    rooms = await list_rooms(db, status="active")
    queen_rooms = [r for r in rooms if r.cell_id is None or r.cell_id == queen.id]
    if len(queen_rooms) < 40:
        return queen
    workers = [c for c in await _list_assignable_cells(db) if not c.is_queen]
    if not workers:
        return queen
    counts: dict[uuid.UUID, int] = {w.id: 0 for w in workers}
    for r in rooms:
        if r.cell_id in counts:
            counts[r.cell_id] += 1
    best = min(workers, key=lambda w: counts.get(w.id, 0))
    return best
