"""Назначение комнаты olcrtc: sticky + max_clients + draining (плоскость отдельно от WDTT Hive).

Session-mode («как VK»): create on demand на fingerprint → leave = teardown комнаты+unit.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.olcrtc_room import OlcrtcRoom, OlcrtcRoomSticky
from app.services.olcrtc_rooms_db import (
    create_room_row,
    delete_room_row,
    ensure_rooms_synced,
    render_unit_yaml,
    room_to_dict,
)
from app.services.olcrtc_settings import (
    DEFAULT_TRANSPORTS,
    load_olcrtc_settings,
    normalize_device_type,
    normalize_room_id,
)

logger = logging.getLogger(__name__)

HEARTBEAT_STALE_SEC = 120
LINK_WAIT_SEC = 45
LINK_POLL_SEC = 2.0
# Все комнаты заняты — лучше пустить с просадкой скорости, чем отказать:
# агент дотянет пул в ближайшем цикле. (только legacy pool-mode)
OVERFLOW_PER_ROOM = 2
NO_ROOM_DETAIL = (
    "Нет свободных комнат обхода (вариант 2). Попробуйте позже или другой провайдер."
)

# Сериализация create Playwright (один за раз на процесс API).
_create_global_lock = asyncio.Lock()
_fp_locks: dict[str, asyncio.Lock] = {}
_fp_locks_guard = asyncio.Lock()


async def _fp_lock(key: str) -> asyncio.Lock:
    async with _fp_locks_guard:
        lock = _fp_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _fp_locks[key] = lock
        return lock


async def _agent_session_mode(db: AsyncSession) -> bool:
    try:
        from ai.olcrtc_room_agent import load_agent_state

        state = await load_agent_state(db)
        return bool(state.session_mode)
    except Exception:
        return True


async def _agent_max_clients(db: AsyncSession) -> int:
    try:
        from ai.olcrtc_room_agent import load_agent_state

        state = await load_agent_state(db)
        if state.session_mode:
            return 1
        return max(1, int(state.max_clients or 1))
    except Exception:
        return 1


async def _wait_unit_linked(unit: str, *, timeout_sec: float = LINK_WAIT_SEC) -> bool:
    from ai.olcrtc_host_provision_client import host_unit_health

    deadline = asyncio.get_event_loop().time() + timeout_sec
    while asyncio.get_event_loop().time() < deadline:
        st = await host_unit_health(unit)
        if st.get("healthy") is True:
            return True
        await asyncio.sleep(LINK_POLL_SEC)
    return False


async def _apply_room_unit(db: AsyncSession, room: OlcrtcRoom) -> dict[str, Any]:
    from ai.olcrtc_host_provision_client import apply_units_via_host

    settings = await load_olcrtc_settings(db)
    yaml_text = render_unit_yaml(settings, room)
    return await apply_units_via_host({room.unit_name: yaml_text}, remove=[])


async def _teardown_room(db: AsyncSession, room: OlcrtcRoom, *, reason: str) -> None:
    """Удалить комнату + sticky + unit на хосте (+ WB remote DELETE)."""
    from ai.olcrtc_host_provision_client import apply_units_via_host

    unit = room.unit_name
    rid = room.id
    provider = (room.provider or "").strip().lower()
    remote_room = (room.room_url or "").strip()
    if provider == "wbstream" and remote_room:
        try:
            from app.services.olcrtc_room_accounts import resolve_wbstream_access_token
            from ai.olcrtc_wb_api import delete_wbstream_room_api

            tok = await resolve_wbstream_access_token(db)
            if tok:
                await delete_wbstream_room_api(tok, remote_room)
        except Exception:
            logger.debug("wb remote delete failed room=%s", remote_room[:40], exc_info=True)
    await delete_room_row(db, rid, reason=reason)
    try:
        await apply_units_via_host({}, remove=[unit])
    except Exception:
        logger.exception("olcrtc teardown apply remove failed unit=%s", unit)


async def ensure_session_room(
    db: AsyncSession,
    *,
    fingerprint: str,
    device_type: str = "",
    provider: str = "telemost",
) -> OlcrtcRoom | None:
    """Create-on-demand: sticky healthy → reuse; idle spare → claim; иначе create → Link."""
    from ai.olcrtc_host_provision_client import create_room_best, host_unit_health
    from app.services.olcrtc_room_accounts import load_room_accounts, resolve_storage_state

    await ensure_rooms_synced(db)
    prov = (provider or "telemost").strip().lower() or "telemost"
    dt = normalize_device_type(device_type) or "pc"
    fp = fingerprint.strip()[:128]
    if not fp:
        return None

    lock = await _fp_lock(f"{fp}:{prov}:{dt}")
    async with lock:
        sticky = await _sticky_row(db, fp, prov, dt)
        if sticky:
            room = await db.get(OlcrtcRoom, sticky.room_id)
            if room and room.status == "active" and _matches_device(room, dt):
                health = await host_unit_health(room.unit_name)
                if health.get("healthy") is True or health.get("healthy") is None:
                    sticky.updated_at = _now()
                    await _recount_room_online(db, room)
                    room.last_healthy_at = _now()
                    await db.commit()
                    return room
                await _teardown_room(db, room, reason="session ensure: unit unhealthy")

        # Свободная spare-комната слота (warm / leftover) — без Playwright.
        idle = await _least_loaded_room(db, provider=prov, device_type=dt, overflow=0)
        if idle and int(idle.online_count or 0) <= 0:
            from app.services.olcrtc_settings import is_placeholder_room

            if is_placeholder_room(idle.room_url):
                await _teardown_room(db, idle, reason="session ensure: placeholder idle")
            else:
                health = await host_unit_health(idle.unit_name)
                if health.get("healthy") is True or health.get("healthy") is None:
                    await _save_sticky(db, fp, prov, dt, idle.id, commit=False)
                    await _recount_room_online(db, idle)
                    idle.last_healthy_at = _now()
                    await db.commit()
                    logger.info(
                        "ensure_session_room reuse idle unit=%s room=%s",
                        idle.unit_name,
                        idle.room_url,
                    )
                    return idle
                await _teardown_room(db, idle, reason="session ensure: idle unit unhealthy")

        accounts = await load_room_accounts(db)
        storage = None
        acc_list = accounts.telemost if prov == "telemost" else accounts.wbstream
        for acc in acc_list:
            storage = resolve_storage_state(acc)
            if storage:
                break
        wb_token = ""
        if prov == "wbstream":
            try:
                from app.services.olcrtc_room_accounts import (
                    resolve_wbstream_access_token,
                    sync_wbstream_auth_token_to_settings,
                )
                from ai.olcrtc_host_provision_client import push_storage_to_host

                wb_token = await sync_wbstream_auth_token_to_settings(db) or ""
                if not wb_token:
                    wb_token = await resolve_wbstream_access_token(db)
                if storage:
                    await push_storage_to_host("wbstream", storage)
            except Exception:
                logger.debug("wb pre-create sync failed", exc_info=True)
        async with _create_global_lock:
            result = await create_room_best(
                prov, storage, headless=True, access_token=wb_token
            )
            if not result.ok or not result.room_id:
                logger.warning(
                    "ensure_session_room create fail provider=%s: %s",
                    prov,
                    (result.message or "")[:160],
                )
                return None
            cell = None
            try:
                cell = await pick_cell_for_new_room(db)
            except Exception:
                pass
            cell_id = None if not cell or getattr(cell, "is_queen", True) else cell.id
            row = await create_room_row(
                db,
                provider=prov,
                room_url=result.room_id,
                slot_label=dt,
                device_types=[dt],
                max_clients=1,
                cell_id=cell_id,
                status="provisioning",
            )
            room_id = row.id
            unit_name = row.unit_name
            applied = await _apply_room_unit(db, row)
            if not applied.get("ok"):
                logger.warning(
                    "ensure_session_room apply fail unit=%s: %s",
                    unit_name,
                    applied.get("message"),
                )
                fresh = await db.get(OlcrtcRoom, room_id)
                if fresh:
                    await _teardown_room(db, fresh, reason="session ensure: apply failed")
                return None
            linked = await _wait_unit_linked(unit_name)
            fresh = await db.get(OlcrtcRoom, room_id)
            if not fresh:
                logger.warning(
                    "ensure_session_room room vanished after create id=%s unit=%s",
                    room_id,
                    unit_name,
                )
                try:
                    from ai.olcrtc_host_provision_client import apply_units_via_host

                    await apply_units_via_host({}, remove=[unit_name])
                except Exception:
                    pass
                return None
            if not linked:
                logger.warning(
                    "ensure_session_room Link timeout unit=%s room=%s",
                    unit_name,
                    result.room_id,
                )
                await _teardown_room(db, fresh, reason="session ensure: Link timeout")
                return None
            fresh.status = "active"
            fresh.last_healthy_at = _now()
            fresh.last_error = None
            await db.commit()
            row = fresh

        await _save_sticky(db, fp, prov, dt, row.id, commit=True)
        row = await db.get(OlcrtcRoom, row.id)
        if not row:
            return None
        await _recount_room_online(db, row)
        row.last_healthy_at = _now()
        await db.commit()
        logger.info(
            "ensure_session_room ok provider=%s slot=%s unit=%s room=%s",
            prov,
            dt,
            row.unit_name,
            result.room_id,
        )
        return row


async def release_session_room(
    db: AsyncSession,
    *,
    room_db_id: str = "",
    fingerprint: str = "",
    provider: str = "",
    reason: str = "leave",
) -> dict[str, Any]:
    """Leave / fatal: снять sticky; в session_mode — снести пустую комнату+unit."""
    session = await _agent_session_mode(db)
    cleared = 0
    torn = 0
    fp = fingerprint.strip()
    prov = (provider or "").strip().lower()
    rooms: set[uuid.UUID] = set()

    if (room_db_id or "").strip():
        try:
            rooms.add(uuid.UUID(room_db_id.strip()))
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
            rooms.add(st.room_id)
        cleared += await _clear_sticky_fp_provider(db, fp, prov)
    elif fp:
        rows = (
            await db.execute(
                select(OlcrtcRoomSticky).where(
                    OlcrtcRoomSticky.fingerprint == fp[:128],
                )
            )
        ).scalars().all()
        for st in rows:
            rooms.add(st.room_id)
            prov = prov or st.provider
        if rooms:
            cleared += int(
                (
                    await db.execute(
                        delete(OlcrtcRoomSticky).where(
                            OlcrtcRoomSticky.fingerprint == fp[:128]
                        )
                    )
                ).rowcount
                or 0
            )

    for rid in list(rooms):
        room = await db.get(OlcrtcRoom, rid)
        if not room:
            continue
        await _recount_room_online(db, room)
        if session and int(room.online_count or 0) <= 0:
            await _teardown_room(db, room, reason=f"session release: {reason}")
            torn += 1
        else:
            await db.commit()

    return {"ok": True, "sticky_cleared": cleared, "torn_down": torn, "session_mode": session}


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
    """online_count = число sticky на комнату (один fingerprint = один слот).

    Без обрезки по max_clients: при переливе админка и агент должны видеть
    реальную нагрузку, иначе перегруженная комната выглядит просто «полной».
    """
    result = await db.execute(
        select(func.count())
        .select_from(OlcrtcRoomSticky)
        .where(OlcrtcRoomSticky.room_id == room.id)
    )
    room.online_count = max(0, int(result.scalar() or 0))
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


def _room_accepts_new(
    room: OlcrtcRoom,
    *,
    allow_overflow_sticky: bool = False,
    overflow: int = 0,
) -> bool:
    if room.status == "draining":
        return allow_overflow_sticky
    if room.status != "active":
        return False
    if allow_overflow_sticky:
        return True
    return int(room.online_count or 0) < int(room.max_clients or 1) + max(0, overflow)


async def _least_loaded_room(
    db: AsyncSession,
    *,
    provider: str,
    device_type: str,
    overflow: int = 0,
) -> OlcrtcRoom | None:
    """Выбрать комнату слота с минимальным online.

    Важно: FOR UPDATE SKIP LOCKED на *всех* active провайдера (pc+android)
    локал весь пул на время транзакции → параллельный Android/PC видел
    пустой SELECT и получал «нет свободных комнат» при живых 0/2 в админке.
    Теперь: фильтр по слоту → кандидаты без лока → лок по одной.
    """
    dt = normalize_device_type(device_type) or device_type.strip().lower() or "pc"
    ids_result = await db.execute(
        select(OlcrtcRoom.id)
        .where(
            OlcrtcRoom.provider == provider,
            OlcrtcRoom.status == "active",
            or_(
                OlcrtcRoom.slot_label == dt,
                OlcrtcRoom.device_types.contains([dt]),
            ),
        )
        .order_by(OlcrtcRoom.online_count.asc(), OlcrtcRoom.created_at.asc())
        .limit(32)
    )
    for rid in ids_result.scalars().all():
        locked = await db.execute(
            select(OlcrtcRoom).where(OlcrtcRoom.id == rid).with_for_update(skip_locked=True)
        )
        room = locked.scalar_one_or_none()
        if room is None:
            continue
        if _matches_device(room, dt) and _room_accepts_new(room, overflow=overflow):
            return room
    return None


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
        # Своё место уже посчитано в online_count — на заполненность не смотрим,
        # иначе устройство выбивало само себя из комнаты при каждом запросе.
        if room and _matches_device(room, dt) and room.status in ("active", "draining"):
            sticky.updated_at = _now()
            if reserve:
                await _recount_room_online(db, room)
            await db.commit()
            return room

    chosen = await _least_loaded_room(db, provider=provider, device_type=dt)
    if not chosen:
        # Слоты могли остаться за клиентами, которые давно отвалились без leave.
        if await reconcile_stale_online(db):
            chosen = await _least_loaded_room(db, provider=provider, device_type=dt)
    if not chosen:
        chosen = await _least_loaded_room(
            db, provider=provider, device_type=dt, overflow=OVERFLOW_PER_ROOM
        )
        if chosen:
            logger.warning(
                "olcrtc pool overflow: %s/%s room=%s online=%s/%s — агенту пора добавить комнату",
                provider,
                dt,
                chosen.unit_name,
                chosen.online_count,
                chosen.max_clients,
            )
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
    """olcrtc снят с продукта — клиентам всегда disabled (WDTT only)."""
    _ = (db, fingerprint, preferred_provider)
    return {
        "enabled": False,
        "crypto_key": "",
        "socks_host": "127.0.0.1",
        "socks_port": 8808,
        "assigned_slot": "",
        "device_type": normalize_device_type(device_type) or "",
        "pool_denied": True,
        "pool_denied_detail": "olcrtc disabled",
        "providers": {},
        "session_mode": False,
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
    """Клиент: peer/room dead → sticky clear; session fatal → teardown; else status=error."""
    await ensure_rooms_synced(db)
    session = await _agent_session_mode(db)
    detail_l = (detail or "").lower()
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
    if session:
        # Session: любой failure = leave+teardown (как выход из VK-слота)
        released = await release_session_room(
            db,
            room_db_id=room_db_id,
            fingerprint=fingerprint,
            provider=provider,
            reason=f"failure: {(detail or '')[:80]}",
        )
        return {
            "ok": True,
            "marked_error": False,
            "sticky_cleared": released.get("sticky_cleared", 0),
            "torn_down": released.get("torn_down", 0),
            "session_mode": True,
            "hint": "fetch /olcrtc-config again for a new room",
        }

    cleared_sticky = 0
    marked_error = 0
    affected_rooms: set[uuid.UUID] = set()
    fp = fingerprint.strip()
    prov = (provider or "").strip().lower()
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
    """Держит online через sticky. online=false — leave (+ session teardown)."""
    if not online:
        released = await release_session_room(
            db,
            room_db_id=room_db_id,
            fingerprint=fingerprint,
            provider=provider,
            reason="heartbeat offline",
        )
        return {"ok": True, "released": released}

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

    room.last_healthy_at = _now()
    if fp:
        await _save_sticky(db, fp, prov, dt, room.id, commit=False)
    await _recount_room_online(db, room)
    await db.commit()
    return {"ok": True, "room": room_to_dict(room)}


async def reconcile_stale_online(db: AsyncSession) -> int:
    """Снять sticky без heartbeat и выровнять online_count.

    Session-mode: пустые комнаты после stale → teardown (как leave).
    """
    cutoff = _now() - timedelta(seconds=HEARTBEAT_STALE_SEC)
    removed = int(
        (
            await db.execute(
                delete(OlcrtcRoomSticky).where(OlcrtcRoomSticky.updated_at < cutoff)
            )
        ).rowcount
        or 0
    )
    live_count = (
        select(func.count())
        .select_from(OlcrtcRoomSticky)
        .where(OlcrtcRoomSticky.room_id == OlcrtcRoom.id)
        .scalar_subquery()
    )
    fixed = int(
        (
            await db.execute(
                update(OlcrtcRoom)
                .where(OlcrtcRoom.online_count != live_count)
                .values(online_count=live_count)
            )
        ).rowcount
        or 0
    )
    if removed or fixed:
        await db.commit()

    torn = 0
    if removed and await _agent_session_mode(db):
        empty = (
            await db.execute(
                select(OlcrtcRoom).where(
                    OlcrtcRoom.status == "active",
                    OlcrtcRoom.online_count <= 0,
                )
            )
        ).scalars().all()
        for room in empty:
            # Не трогать bootstrap_warm spare сразу после create — только если
            # комната «протухла» по last_healthy (нет heartbeat > stale).
            healthy = room.last_healthy_at
            if healthy and healthy > cutoff:
                continue
            await _teardown_room(db, room, reason="stale reconcile: empty session")
            torn += 1
    return fixed + removed + torn


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
