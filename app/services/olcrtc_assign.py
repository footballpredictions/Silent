"""Назначение комнаты olcrtc: sticky + max_clients + draining (плоскость отдельно от WDTT Hive)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
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


async def _save_sticky(
    db: AsyncSession,
    fingerprint: str,
    provider: str,
    device_type: str,
    room_id: uuid.UUID,
) -> None:
    fp = fingerprint.strip()[:128]
    if not fp:
        return
    dt = normalize_device_type(device_type) or "pc"
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
    await db.commit()


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
) -> OlcrtcRoom | None:
    """Выдать комнату. Новый fingerprint резервирует слот (online_count+1), иначе все
    клиенты без heartbeat садятся в одну комнату и 1000+ на бумаге не работает.
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
            # sticky на overflowing active — только если уже был; новым не
            if room.status == "active" and int(room.online_count or 0) >= int(room.max_clients or 1):
                # переполнена — ищем другую
                pass
            elif room.status in ("active", "draining"):
                return room

    # FOR UPDATE SKIP LOCKED — параллельные assign не бьют в одну строку
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
    # резерв слота сразу при выдаче (heartbeat потом только refresh)
    chosen.online_count = min(
        int(chosen.max_clients or 1), int(chosen.online_count or 0) + 1
    )
    chosen.last_healthy_at = _now()
    if fp:
        await _save_sticky(db, fp, provider, dt, chosen.id)
    else:
        await db.commit()
    return chosen


async def assign_public_config(
    db: AsyncSession,
    *,
    device_type: str = "",
    fingerprint: str = "",
) -> dict[str, Any]:
    """Как public_client_config, но room из БД с cap/sticky. 503 → error_code в JSON."""
    settings = await load_olcrtc_settings(db)
    key_ok = len(settings.crypto_key) == 64
    providers_out: dict[str, Any] = {}
    assigned_slot = ""
    any_provider_ok = False
    wanted_enabled = 0
    dt = normalize_device_type(device_type)

    for name, p in settings.providers.items():
        room_url = ""
        room_slot = ""
        room_uuid = ""
        enabled = bool(settings.enabled and p.enabled and key_ok)
        denied = False
        if enabled:
            wanted_enabled += 1
            room = await pick_room(
                db, provider=name, device_type=device_type, fingerprint=fingerprint
            )
            if room:
                room_url = normalize_room_id(name, room.room_url)
                room_slot = room.slot_label
                room_uuid = str(room.id)
                any_provider_ok = True
                if not assigned_slot:
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

    # rooms_count per provider
    for name in providers_out:
        result = await db.execute(
            select(OlcrtcRoom).where(
                OlcrtcRoom.provider == name, OlcrtcRoom.status == "active"
            )
        )
        providers_out[name]["rooms_count"] = len(list(result.scalars().all()))

    # pool_denied только если ни один включённый провайдер не дал комнату
    # (пустой WB не должен блокировать Jitsi/Telemost на массе)
    pool_denied = bool(settings.enabled and key_ok and wanted_enabled > 0 and not any_provider_ok)

    return {
        "enabled": bool(settings.enabled and key_ok),
        "crypto_key": settings.crypto_key if (settings.enabled and key_ok) else "",
        "providers": providers_out,
        "socks_host": "127.0.0.1",
        "socks_port": 8808,
        "assigned_slot": assigned_slot,
        "device_type": dt,
        "jitsi_https_proxy": "http://132.243.234.162:8080"
        if (settings.enabled and key_ok)
        else "",
        "pool_denied": pool_denied,
        "pool_denied_detail": NO_ROOM_DETAIL if pool_denied else "",
    }


async def heartbeat(
    db: AsyncSession,
    *,
    room_db_id: str,
    fingerprint: str = "",
    provider: str = "",
    online: bool = True,
) -> dict[str, Any]:
    """Клиент держит online_count. При online=false — decrement (disconnect)."""
    try:
        rid = uuid.UUID(room_db_id)
    except ValueError:
        return {"ok": False, "detail": "bad room_db_id"}
    room = await db.get(OlcrtcRoom, rid)
    if not room:
        return {"ok": False, "detail": "room not found"}

    # Простой счётчик: при heartbeat online — bump last_healthy и clamp count
    # Точный unique-count через sticky+TTL был бы тяжелее; для MVP:
    # online=true → online_count = max(online_count, 1) и +0 sticky refresh;
    # используем Redis-like: если fingerprint sticky на эту комнату — не двойной инкремент.
    if online:
        room.last_healthy_at = _now()
        if fingerprint.strip():
            st = await _sticky_row(
                db, fingerprint, provider or room.provider, room.slot_label
            )
            if not st or st.room_id != room.id:
                room.online_count = min(
                    int(room.max_clients), int(room.online_count or 0) + 1
                )
                await _save_sticky(
                    db,
                    fingerprint,
                    provider or room.provider,
                    room.slot_label,
                    room.id,
                )
            else:
                # refresh only
                st.updated_at = _now()
        else:
            room.online_count = min(
                int(room.max_clients), max(1, int(room.online_count or 0))
            )
    else:
        room.online_count = max(0, int(room.online_count or 0) - 1)

    await db.commit()
    return {"ok": True, "room": room_to_dict(room)}


async def reconcile_stale_online(db: AsyncSession) -> int:
    """Сбросить online_count у комнат без heartbeat (грубая защита от залипания)."""
    # Sticky старше HEARTBEAT_STALE — не трогаем count агрессивно; только обнуляем
    # комнаты active с online>0 и last_healthy слишком старым.
    cutoff = _now() - timedelta(seconds=HEARTBEAT_STALE_SEC * 3)
    result = await db.execute(
        select(OlcrtcRoom).where(
            OlcrtcRoom.status == "active", OlcrtcRoom.online_count > 0
        )
    )
    fixed = 0
    for room in result.scalars().all():
        if room.last_healthy_at and room.last_healthy_at < cutoff:
            room.online_count = 0
            fixed += 1
    if fixed:
        await db.commit()
    return fixed


async def pick_cell_for_new_room(db: AsyncSession):
    """Placement комнаты на соту: queen по умолчанию, worker при overload queen olcrtc."""
    from app.services.hive_service import ensure_queen_cell, _list_assignable_cells
    from app.services.olcrtc_rooms_db import list_rooms

    queen = await ensure_queen_cell(db)
    rooms = await list_rooms(db, status="active")
    queen_rooms = [r for r in rooms if r.cell_id is None or r.cell_id == queen.id]
    # простой порог: >40 unit на queen → spill
    if len(queen_rooms) < 40:
        return queen
    workers = [c for c in await _list_assignable_cells(db) if not c.is_queen]
    if not workers:
        return queen
    # min rooms on cell
    counts: dict[uuid.UUID, int] = {w.id: 0 for w in workers}
    for r in rooms:
        if r.cell_id in counts:
            counts[r.cell_id] += 1
    best = min(workers, key=lambda w: counts.get(w.id, 0))
    return best
