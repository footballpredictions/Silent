"""olcrtc 2.0 assign — occupancy 1:1 (max_clients=1 TM и WB).
sticky по fingerprint, leave = снять sticky (комнату НЕ убивать).
failure/carrier-dead = teardown. Exit only on Hive cell.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
from app.services.olcrtc2_cell_units import (
    SETTLE_AFTER_APPLY_SEC,
    apply_olcrtc2_unit,
    ensure_unit_ready,
    probe_olcrtc2_unit,
    resolve_olcrtc2_cell,
    teardown_olcrtc2_unit,
)
from app.services.olcrtc2_create import create_olcrtc2_room
from app.services.olcrtc2_settings import (
    TELEMOST_WARM_PER_DT_CAP,
    WBSTREAM_WARM_PER_DT_CAP,
    denied_config,
    load_olcrtc2_settings,
    room_to_public_config,
    warm_pool_for,
)

logger = logging.getLogger(__name__)

# Sticky без heartbeat снимаем; комнаты живут (Telemost ~сутки / WB пока srv жив).
# 300с: клиент HB ~30с; раньше 180с + leave-on-restart рвали живые сессии ~3–10 мин.
HEARTBEAT_STALE_SEC = 300
# Не teardown «пустых» warm, если комната недавно была healthy (клиент ещё на peer).
RECENT_HEALTHY_KEEP_SEC = 900
# Excess idle (stickies=0): 15 мин keep оставлял 40 unit после inflate warm=20.
EXCESS_WARM_KEEP_SEC = 90
# Occupancy 1:1 — shared vp8channel рвёт соседей (TM и WB).
DEFAULT_MAX_CLIENTS = 1
TELEMOST_MAX_CLIENTS = 1
WBSTREAM_MAX_CLIENTS = 1
NO_ROOM_DETAIL = (
    "Нет свободных комнат olcrtc2. Агент пополняет warm-пул — повторите через 10–30 с."
)

_create_global_lock = asyncio.Lock()
_create_prov_locks: dict[str, asyncio.Lock] = {}
_create_prov_locks_guard = asyncio.Lock()
_fp_locks: dict[str, asyncio.Lock] = {}
_fp_locks_guard = asyncio.Lock()
# За один цикл агента не плодим десятки комнат (create+settle ~8с).
WARM_CREATE_BUDGET = 6
# Claim под per-(provider,dt) lock: concurrent assign не переполнит max_clients.
_claim_locks: dict[str, asyncio.Lock] = {}
_claim_locks_guard = asyncio.Lock()
# first failure per (fp,provider,room) is soft (sticky clear only), second in window is hard teardown
_failure_first_seen_at: dict[str, float] = {}
FAILURE_HARD_ESCALATE_SEC = 25.0
# Burst warm: при серии pool-denied временно повышаем warm-цель и затем авто-отпускаем.
BURST_DENY_WINDOW_SEC = 20.0
BURST_DENY_THRESHOLD = 3
BURST_HOLD_SEC = 120.0
BURST_WARM_BONUS_BY_PROVIDER = {"telemost": 1, "wbstream": 1}
_pool_denied_events: deque[tuple[float, str, str]] = deque(maxlen=512)
_burst_until_by_provider: dict[str, float] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _create_lock(provider: str) -> asyncio.Lock:
    p = (provider or "telemost").strip().lower()
    async with _create_prov_locks_guard:
        lock = _create_prov_locks.get(p)
        if lock is None:
            lock = asyncio.Lock()
            _create_prov_locks[p] = lock
        return lock


def _max_rooms_for_provider(provider: str, *, target_online: int, warm_per_dt: int) -> int:
    """Потолок комнат на провайдера: 150 онлайн + запас PC и Android."""
    max_c = max(1, _max_clients_for(provider))
    seats = max(0, int(target_online or 0))
    occupied = (seats + max_c - 1) // max_c
    return occupied + 2 * max(0, int(warm_per_dt or 0))


def _note_pool_denied(provider: str, device_type: str = "") -> None:
    prov = _norm_prov(provider)
    dt = _norm_dt(device_type)
    now = time.time()
    _pool_denied_events.append((now, prov, dt))
    cutoff = now - BURST_DENY_WINDOW_SEC
    recent = 0
    for ts, p, _ in _pool_denied_events:
        if p == prov and ts >= cutoff:
            recent += 1
    if recent >= BURST_DENY_THRESHOLD:
        prev = _burst_until_by_provider.get(prov, 0.0)
        until = now + BURST_HOLD_SEC
        _burst_until_by_provider[prov] = max(prev, until)
        logger.warning(
            "olcrtc2 burst warm ON provider=%s recent_denied=%s hold=%ss",
            prov,
            recent,
            int(BURST_HOLD_SEC),
        )


def _warm_target_with_burst(settings: dict[str, Any], provider: str) -> int:
    base = warm_pool_for(settings, provider)
    prov = _norm_prov(provider)
    now = time.time()
    until = _burst_until_by_provider.get(prov, 0.0)
    if until <= now:
        _burst_until_by_provider.pop(prov, None)
        return base
    bonus = int(BURST_WARM_BONUS_BY_PROVIDER.get(prov, 1) or 0)
    target = max(0, base + bonus)
    if prov == "telemost":
        return min(TELEMOST_WARM_PER_DT_CAP, target)
    if prov == "wbstream":
        return min(WBSTREAM_WARM_PER_DT_CAP, target)
    return target


async def _count_provider_rooms(db: AsyncSession, provider: str) -> int:
    n = (
        await db.execute(
            select(func.count())
            .select_from(Olcrtc2Room)
            .where(
                Olcrtc2Room.provider == provider,
                Olcrtc2Room.status.in_(("active", "provisioning", "warming")),
            )
        )
    ).scalar()
    return int(n or 0)


async def _fp_lock(key: str) -> asyncio.Lock:
    async with _fp_locks_guard:
        lock = _fp_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _fp_locks[key] = lock
        return lock


async def _claim_lock(key: str) -> asyncio.Lock:
    async with _claim_locks_guard:
        lock = _claim_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _claim_locks[key] = lock
        return lock


def _norm_dt(device_type: str) -> str:
    dt = (device_type or "pc").strip().lower()
    return dt if dt in ("pc", "android", "ios") else "pc"


def _norm_prov(provider: str, settings: dict[str, Any]) -> str:
    p = (provider or settings.get("provider") or "telemost").strip().lower()
    return p if p in ("telemost", "wbstream") else "telemost"


def _max_clients_for(provider: str) -> int:
    p = (provider or "").strip().lower()
    if p == "telemost":
        return TELEMOST_MAX_CLIENTS
    if p == "wbstream":
        return WBSTREAM_MAX_CLIENTS
    return DEFAULT_MAX_CLIENTS


def _unit_name() -> str:
    return f"o2-{uuid.uuid4().hex[:12]}"


async def _carrier_room_alive(room: Olcrtc2Room) -> bool | None:
    """HTTP-probe носителя (WB join / Telemost connection).

    systemd active ≠ живая конференция: WB часто даёт join 404 при «active» unit.
    True=жива, False=мертва, None=неизвестно (сеть/5xx) — не рвём.
    """
    url = (room.room_url or "").strip()
    if not url:
        return False
    try:
        from ai.olcrtc_room_liveness import probe_room

        probe = await probe_room(room.provider or "", url)
        if probe.is_dead:
            logger.warning(
                "olcrtc2 carrier DEAD provider=%s unit=%s room=%s: %s",
                room.provider,
                room.unit_name,
                url[:40],
                (probe.reason or "")[:120],
            )
            return False
        if probe.is_alive:
            return True
        logger.info(
            "olcrtc2 carrier ? provider=%s unit=%s: %s",
            room.provider,
            room.unit_name,
            (probe.reason or "")[:80],
        )
        return None
    except Exception as e:
        logger.warning("olcrtc2 carrier probe err unit=%s: %s", room.unit_name, e)
        return None


async def _tear_dead_room(
    db: AsyncSession,
    room: Olcrtc2Room,
    *,
    sticky: Olcrtc2Sticky | None = None,
    reason: str = "carrier dead",
) -> None:
    if sticky is not None:
        await db.delete(sticky)
    await db.execute(delete(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id == room.id))
    await teardown_olcrtc2_unit(db, room)
    await _remote_delete_room(room)
    await db.delete(room)
    await db.commit()
    logger.warning(
        "olcrtc2 tear %s unit=%s room=%s",
        reason,
        room.unit_name,
        (room.room_url or "")[:40],
    )


async def _save_sticky(
    db: AsyncSession,
    fingerprint: str,
    provider: str,
    device_type: str,
    room_id: uuid.UUID,
    *,
    commit: bool = True,
) -> None:
    fp = fingerprint[:128]
    existing = (
        await db.execute(
            select(Olcrtc2Sticky).where(
                Olcrtc2Sticky.fingerprint == fp,
                Olcrtc2Sticky.provider == provider,
                Olcrtc2Sticky.device_type == device_type,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.room_id = room_id
        existing.updated_at = _now()
    else:
        db.add(
            Olcrtc2Sticky(
                fingerprint=fp,
                provider=provider,
                device_type=device_type,
                room_id=room_id,
            )
        )
    if commit:
        await db.commit()


async def _touch_devices_online(
    db: AsyncSession,
    fingerprint: str,
    *,
    device_type: str = "",
    cell_id: uuid.UUID | None = None,
) -> None:
    """olcrtc без wdtt keepalive — иначе админка «онлайн» видит 0/1."""
    fp = (fingerprint or "").strip()[:128]
    if not fp:
        return
    try:
        from app.models.device import Device

        q = select(Device).where(
            Device.device_fingerprint == fp,
            Device.is_active == True,  # noqa: E712
        )
        dt = (device_type or "").strip().lower()
        if dt:
            q = q.where(Device.device_type == dt)
        devices = (await db.execute(q)).scalars().all()
        now = _now()
        queen_id: uuid.UUID | None = None
        for d in devices:
            d.is_connected = True
            d.last_connected = now
            if cell_id and d.cell_id is None:
                # Не перетираем текущую WDTT-привязку соты (queen/worker),
                # чтобы heartbeat звонка не выглядел как возврат балансировки на 1/2.
                d.cell_id = cell_id
            elif cell_id and d.cell_id == cell_id:
                # Одноразово лечим старые записи, которые уже были "утащены" на olcrtc-соту.
                if queen_id is None:
                    from app.services.hive_service import ensure_queen_cell

                    queen = await ensure_queen_cell(db)
                    queen_id = queen.id
                if queen_id:
                    d.cell_id = queen_id
    except Exception:
        logger.debug("olcrtc2 device touch failed", exc_info=True)


async def _recount(db: AsyncSession, room: Olcrtc2Room) -> None:
    n = (
        await db.execute(
            select(func.count()).select_from(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id == room.id)
        )
    ).scalar() or 0
    room.online_count = int(n)


async def _count_free_rooms(db: AsyncSession, *, provider: str, device_type: str) -> int:
    rows = (
        await db.execute(
            select(Olcrtc2Room).where(
                Olcrtc2Room.provider == provider,
                Olcrtc2Room.device_type == device_type,
                Olcrtc2Room.status == "active",
            )
        )
    ).scalars().all()
    n = 0
    for room in rows:
        stickies = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Olcrtc2Sticky)
                    .where(Olcrtc2Sticky.room_id == room.id)
                )
            ).scalar()
            or 0
        )
        if stickies == 0:
            n += 1
    return n


async def _remote_delete_room(room: Olcrtc2Room) -> None:
    """Best-effort delete remote WB conference after local teardown."""
    if (room.provider or "") != "wbstream":
        return
    tok = (room.auth_token or "").strip()
    rid = (room.room_url or "").strip()
    if not tok.startswith("eyJ") or not rid:
        return
    try:
        from ai.olcrtc_wb_api import delete_wbstream_room_api

        await delete_wbstream_room_api(tok, rid)
    except Exception:
        logger.debug("olcrtc2 wb remote delete failed", exc_info=True)


async def _provision_room(
    db: AsyncSession,
    *,
    provider: str,
    device_type: str,
    storage: dict | None,
    wb_token: str = "",
) -> Olcrtc2Room | None:
    """Create Telemost room + apply olcrtc2@unit on cell. No sticky (warm or assign adds it)."""
    async with await _create_lock(provider):
        result = await create_olcrtc2_room(
            db, provider=provider, storage_state=storage, access_token=wb_token
        )
        if not result.ok or not result.room_id:
            logger.warning(
                "olcrtc2 provision create fail provider=%s: %s",
                provider,
                (result.message or "")[:160],
            )
            return None

        if provider == "wbstream" and not (wb_token or "").strip().startswith("eyJ"):
            logger.warning("olcrtc2 provision: wbstream without JWT — refuse")
            return None

        cell = await resolve_olcrtc2_cell(db, provider=provider)
        if not cell:
            logger.warning("olcrtc2 provision: no cell for provider=%s", provider)
            return None

        key = secrets.token_hex(32)
        unit = _unit_name()
        row = Olcrtc2Room(
            provider=provider,
            room_url=result.room_id,
            crypto_key=key,
            slot_label=device_type,
            device_type=device_type,
            cell_id=cell.id,
            unit_name=unit,
            status="provisioning",
            max_clients=_max_clients_for(provider),
            online_count=0,
            auth_token=wb_token if provider == "wbstream" else None,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

        applied = await apply_olcrtc2_unit(db, row)
        if not applied.get("ok"):
            row.status = "error"
            row.last_error = str(applied.get("message") or "apply failed")[:300]
            await db.commit()
            await teardown_olcrtc2_unit(db, row)
            await db.delete(row)
            await db.commit()
            return None

        # Дать srv войти в комнату до выдачи клиенту (иначе peer connected → code=1).
        await asyncio.sleep(SETTLE_AFTER_APPLY_SEC)

        row.status = "active"
        row.last_healthy_at = _now()
        row.last_error = None
        await db.commit()
        logger.info(
            "olcrtc2 provisioned dt=%s unit=%s room=%s",
            device_type,
            row.unit_name,
            row.room_url,
        )
        return row


async def _resolve_storage(db: AsyncSession, prov: str) -> tuple[dict | None, str]:
    storage = None
    wb_token = ""
    try:
        from app.services.olcrtc_room_accounts import (
            load_room_accounts,
            resolve_storage_state,
            resolve_wbstream_access_token,
            sync_wbstream_auth_token_to_settings,
        )

        accounts = await load_room_accounts(db)
        acc_list = accounts.telemost if prov == "telemost" else accounts.wbstream
        for acc in acc_list:
            storage = resolve_storage_state(acc)
            if storage:
                break
        if prov == "wbstream":
            wb_token = await sync_wbstream_auth_token_to_settings(db) or ""
            if not wb_token:
                wb_token = await resolve_wbstream_access_token(db) or ""
    except Exception:
        logger.debug("olcrtc2 account resolve failed", exc_info=True)
    return storage, wb_token


async def ensure_session_room(
    db: AsyncSession,
    *,
    fingerprint: str,
    device_type: str = "",
    provider: str = "",
) -> Olcrtc2Room | None:
    settings = await load_olcrtc2_settings(db)
    if not settings.get("enabled") or not settings.get("agent_enabled"):
        return None
    fp = (fingerprint or "").strip()
    if not fp:
        return None
    dt = _norm_dt(device_type)
    prov = _norm_prov(provider, settings)
    lock = await _fp_lock(f"{fp}:{prov}:{dt}")
    async with lock:
        # sticky hit
        st = (
            await db.execute(
                select(Olcrtc2Sticky).where(
                    Olcrtc2Sticky.fingerprint == fp[:128],
                    Olcrtc2Sticky.provider == prov,
                    Olcrtc2Sticky.device_type == dt,
                )
            )
        ).scalar_one_or_none()
        if st:
            row = await db.get(Olcrtc2Room, st.room_id)
            if row and row.status in ("active", "provisioning") and row.room_url:
                unit_ok = await ensure_unit_ready(db, row)
                # Telemost: не HTTP-probe на каждый assign (до 12с) — unit хватает.
                carrier: bool | None = True
                if unit_ok and (row.provider or "") == "wbstream":
                    carrier = await _carrier_room_alive(row)
                # sticky reconnect: None (сеть) не рвём; False (404) — tear.
                if unit_ok and carrier is not False:
                    row.last_healthy_at = _now()
                    await _recount(db, row)
                    await db.commit()
                    return row
                logger.warning(
                    "olcrtc2 sticky dead unit=%s room=%s unit_ok=%s carrier=%s — drop",
                    row.unit_name,
                    row.room_url,
                    unit_ok,
                    carrier,
                )
                await _tear_dead_room(
                    db,
                    row,
                    sticky=st,
                    reason="sticky dead unit/carrier",
                )
            elif st:
                await db.delete(st)
                await db.commit()

        # Occupancy 1:1: только пустая комната (stickies == 0), не shared max=3/25.
        # Claim под lock + FOR UPDATE, иначе concurrent посадит 2 fp на одну room.
        for _warm_try in range(6):
            claim = await _claim_lock(f"{prov}:{dt}")
            reserved: Olcrtc2Room | None = None
            async with claim:
                idle = (
                    await db.execute(
                        select(Olcrtc2Room)
                        .where(
                            Olcrtc2Room.provider == prov,
                            Olcrtc2Room.device_type == dt,
                            Olcrtc2Room.status == "active",
                        )
                        .order_by(
                            Olcrtc2Room.online_count.asc(),
                            Olcrtc2Room.created_at.asc(),
                        )
                        .limit(16)
                        .with_for_update(skip_locked=True)
                    )
                ).scalars().all()
                for cand in idle:
                    stickies = int(
                        (
                            await db.execute(
                                select(func.count())
                                .select_from(Olcrtc2Sticky)
                                .where(Olcrtc2Sticky.room_id == cand.id)
                            )
                        ).scalar()
                        or 0
                    )
                    want_max = _max_clients_for(prov)
                    if int(cand.max_clients or 0) != want_max:
                        cand.max_clients = want_max
                    if stickies > 0:
                        cand.online_count = stickies
                        continue
                    await _save_sticky(db, fp, prov, dt, cand.id, commit=False)
                    await _touch_devices_online(
                        db,
                        fp,
                        device_type=dt,
                        cell_id=cand.cell_id,
                    )
                    await _recount(db, cand)
                    cand.last_healthy_at = _now()
                    await db.commit()
                    reserved = cand
                    break

            if reserved is None:
                break

            unit_ok = await ensure_unit_ready(db, reserved)
            # Как sticky: False = tear; None (сеть/5xx) ≠ мёртвая комната.
            # Раньше требовали carrier is True → при ?/таймауте Yandex рвали warm
            # и шли в on-demand (Playwright+settle 8с) → тумблер 30с+.
            carrier: bool | None = None
            if unit_ok and (reserved.provider or "") == "wbstream":
                carrier = await _carrier_room_alive(reserved)
            elif unit_ok:
                # Telemost: unit active достаточно; HTTP connection probe до 12с и ложные tear.
                carrier = True
            if unit_ok and carrier is not False:
                await _recount(db, reserved)
                reserved.last_healthy_at = _now()
                await db.commit()
                logger.info(
                    "olcrtc2 pool hit provider=%s dt=%s unit=%s room=%s online=%s/%s carrier=%s",
                    prov,
                    dt,
                    reserved.unit_name,
                    reserved.room_url,
                    reserved.online_count,
                    reserved.max_clients,
                    carrier,
                )
                return reserved

            logger.warning(
                "olcrtc2 pool dead unit=%s unit_ok=%s carrier=%s — teardown+retry",
                reserved.unit_name,
                unit_ok,
                carrier,
            )
            await db.execute(
                delete(Olcrtc2Sticky).where(
                    Olcrtc2Sticky.fingerprint == fp[:128],
                    Olcrtc2Sticky.provider == prov,
                    Olcrtc2Sticky.device_type == dt,
                )
            )
            await _tear_dead_room(db, reserved, reason="pool dead unit/carrier")

        storage, wb_token = await _resolve_storage(db, prov)
        row = await _provision_room(
            db, provider=prov, device_type=dt, storage=storage, wb_token=wb_token
        )
        if not row:
            return None
        unit_ok = await ensure_unit_ready(db, row)
        if not unit_ok:
            logger.warning(
                "olcrtc2 on-demand unit not ready unit=%s — teardown",
                row.unit_name,
            )
            await _tear_dead_room(db, row, reason="on-demand unit not ready")
            return None
        await _save_sticky(db, fp, prov, dt, row.id, commit=False)
        await _touch_devices_online(
            db,
            fp,
            device_type=dt,
            cell_id=row.cell_id,
        )
        await _recount(db, row)
        row.last_healthy_at = _now()
        await db.commit()
        logger.info(
            "olcrtc2 ensure ok provider=%s dt=%s unit=%s room=%s (on-demand)",
            prov,
            dt,
            row.unit_name,
            row.room_url,
        )
        return row


async def ensure_warm_pool(db: AsyncSession) -> dict[str, Any]:
    """Агент: heal мёртвых unit + держать warm_pool_per_dt свободных комнат."""
    settings = await load_olcrtc2_settings(db)
    if not settings.get("enabled") or not settings.get("agent_enabled"):
        return {"ok": False, "skipped": "disabled"}
    healed = 0
    torn = 0
    # Probe-only heal (без re-apply+sleep на всех комнатах — блокировало /olcrtc2-config).
    # Carrier HTTP (WB join) — только wbstream и пачками: иначе 60+ join = минуты блокировки агента.
    actives = (
        await db.execute(select(Olcrtc2Room).where(Olcrtc2Room.status == "active"))
    ).scalars().all()
    carrier_budget = 16
    for room in actives:
        stickies = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Olcrtc2Sticky)
                    .where(Olcrtc2Sticky.room_id == room.id)
                )
            ).scalar()
            or 0
        )
        # Клиент на peer: warm-heal НЕ рвёт unit/carrier.
        # Ложный probe (таймаут cell-agent) иначе убивал VPN через ~90с цикла агента.
        if stickies > 0:
            healed += 1
            continue
        # Sticky мог отвалиться (HB через VPN), а peer ещё жив — не tear.
        healthy_age = None
        if room.last_healthy_at:
            healthy_age = (_now() - room.last_healthy_at).total_seconds()
        if healthy_age is not None and healthy_age < RECENT_HEALTHY_KEEP_SEC:
            logger.info(
                "olcrtc2 warm heal keep recent-healthy unit=%s age=%.0fs (no sticky)",
                room.unit_name,
                healthy_age,
            )
            healed += 1
            continue
        probe = await probe_olcrtc2_unit(db, room)
        unit_ok = bool(probe.get("unknown") or probe.get("active"))
        if not unit_ok:
            msg = str(probe.get("message") or "").lower()
            soft = any(
                x in msg
                for x in (
                    "timeout",
                    "connect",
                    "secret",
                    "cell missing",
                    "refused",
                    "reset",
                    "temporarily",
                )
            )
            if soft:
                logger.info(
                    "olcrtc2 warm heal skip tear unit=%s (probe soft-fail: %s)",
                    room.unit_name,
                    (probe.get("message") or "")[:80],
                )
                healed += 1
                continue
            await _tear_dead_room(db, room, reason="warm heal unit dead")
            torn += 1
            continue
        # WB carrier HTTP-join на active опасен (max_clients=1 / antibot) —
        # не tear по carrier, только unit. Иначе пустые warm + ложный 404 → каскад.
        if (room.provider or "") == "wbstream" and carrier_budget > 0:
            carrier_budget -= 1
            carrier = await _carrier_room_alive(room)
            if carrier is False:
                logger.warning(
                    "olcrtc2 warm heal carrier soft-dead unit=%s — leave warm (no tear)",
                    room.unit_name,
                )
                healed += 1
                continue
        healed += 1

    # Застрявшие warming (bg restart умер) → tear, чтобы ensure_warm_pool создал новые.
    warming = (
        await db.execute(select(Olcrtc2Room).where(Olcrtc2Room.status == "warming"))
    ).scalars().all()
    now = _now()
    for room in warming:
        age = (now - (room.last_healthy_at or room.created_at or now)).total_seconds()
        if age < 45:
            continue
        await db.execute(delete(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id == room.id))
        await teardown_olcrtc2_unit(db, room)
        await db.delete(room)
        await db.commit()
        torn += 1
        logger.warning("olcrtc2 warming stale tear unit=%s age=%.0fs", room.unit_name, age)

    from app.services.olcrtc2_settings import enabled_providers

    target_online = int(settings.get("target_online") or 150)
    created = 0
    by_key: dict[str, int] = {}
    targets: dict[str, int] = {}
    budget = WARM_CREATE_BUDGET
    headroom: dict[str, int] = {}
    combos: list[tuple[str, str, int]] = []
    for prov in enabled_providers(settings):
        target = _warm_target_with_burst(settings, prov)
        targets[prov] = target
        cap = _max_rooms_for_provider(
            prov, target_online=target_online, warm_per_dt=target
        )
        total = await _count_provider_rooms(db, prov)
        headroom[prov] = cap - total
        for dt in ("pc", "android"):
            free = await _count_free_rooms(db, provider=prov, device_type=dt)
            by_key[f"{prov}:{dt}"] = free
            combos.append((prov, dt, free))
    if not any(targets.values()):
        return {"ok": True, "created": 0, "healed": healed, "torn": torn, "target": 0}
    combos.sort(key=lambda x: x[2])
    for prov, dt, free in combos:
        if budget <= 0:
            break
        target = targets.get(prov, 0)
        if target <= 0:
            continue
        storage, wb_token = await _resolve_storage(db, prov)
        while free < target and budget > 0:
            if headroom.get(prov, 0) <= 0:
                logger.info(
                    "olcrtc2 warm skip %s:%s — потолок комнат под target_online=%s",
                    prov,
                    dt,
                    target_online,
                )
                break
            row = await _provision_room(
                db, provider=prov, device_type=dt, storage=storage, wb_token=wb_token
            )
            if not row:
                break
            created += 1
            budget -= 1
            free += 1
            headroom[prov] = headroom.get(prov, 0) - 1
            by_key[f"{prov}:{dt}"] = free
            logger.info("olcrtc2 warm +1 %s:%s free=%s/%s", prov, dt, free, target)
    return {
        "ok": True,
        "created": created,
        "healed_ok": healed,
        "torn": torn,
        "free": by_key,
        "target": targets,
        "target_online": target_online,
        "providers": enabled_providers(settings),
    }


async def release_session_room(
    db: AsyncSession,
    *,
    room_db_id: str = "",
    fingerprint: str = "",
    provider: str = "",
    reason: str = "leave",
) -> dict[str, Any]:
    """leave/offline как 1.0.160: снять sticky + recount. Комнату и unit НЕ трогаем.
    failure/* → teardown (мёртвая конференция / peer fatal).
    """
    cleared = 0
    torn = 0
    soft_kept = 0
    fp = fingerprint.strip()
    prov = (provider or "").strip().lower()
    rooms: set[uuid.UUID] = set()
    hard = reason.startswith("failure") or "fatal" in reason.lower()

    if (room_db_id or "").strip():
        try:
            rooms.add(uuid.UUID(room_db_id.strip()))
        except ValueError:
            pass

    if hard:
        if fp and prov:
            rows = (
                await db.execute(
                    select(Olcrtc2Sticky).where(
                        Olcrtc2Sticky.fingerprint == fp[:128],
                        Olcrtc2Sticky.provider == prov,
                    )
                )
            ).scalars().all()
            for st in rows:
                rooms.add(st.room_id)
                await db.delete(st)
                cleared += 1
            if rows:
                await db.commit()
        elif fp:
            rows = (
                await db.execute(
                    select(Olcrtc2Sticky).where(Olcrtc2Sticky.fingerprint == fp[:128])
                )
            ).scalars().all()
            for st in rows:
                rooms.add(st.room_id)
                await db.delete(st)
                cleared += 1
            if rows:
                await db.commit()
        for rid in rooms:
            room = await db.get(Olcrtc2Room, rid)
            if not room:
                continue
            await db.execute(delete(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id == room.id))
            await _recount(db, room)
            await teardown_olcrtc2_unit(db, room)
            await _remote_delete_room(room)
            await db.delete(room)
            torn += 1
            await db.commit()
            logger.info(
                "olcrtc2 release tear unit=%s room=%s reason=%s",
                room.unit_name,
                room.room_url,
                reason[:40],
            )
    else:
        # soft leave: только sticky этого fp(+prov), комната живёт в пуле
        if fp and prov:
            rows = (
                await db.execute(
                    select(Olcrtc2Sticky).where(
                        Olcrtc2Sticky.fingerprint == fp[:128],
                        Olcrtc2Sticky.provider == prov,
                    )
                )
            ).scalars().all()
            for st in rows:
                rooms.add(st.room_id)
                await db.delete(st)
                cleared += 1
        elif fp:
            rows = (
                await db.execute(
                    select(Olcrtc2Sticky).where(Olcrtc2Sticky.fingerprint == fp[:128])
                )
            ).scalars().all()
            for st in rows:
                rooms.add(st.room_id)
                await db.delete(st)
                cleared += 1
        elif rooms:
            # room_db_id без fp — снять все sticky этой комнаты нельзя (чужие клиенты).
            # Только recount.
            pass
        for rid in rooms:
            room = await db.get(Olcrtc2Room, rid)
            if not room:
                continue
            room.status = "active"
            room.last_healthy_at = _now()
            room.last_error = None
            await _recount(db, room)
            soft_kept += 1
            logger.info(
                "olcrtc2 soft leave → sticky cleared unit=%s room=%s online=%s reason=%s",
                room.unit_name,
                room.room_url,
                room.online_count,
                reason[:40],
            )
        if cleared or soft_kept:
            await db.commit()

    logger.info(
        "olcrtc2 release reason=%s cleared=%s torn=%s soft_kept=%s",
        reason,
        cleared,
        torn,
        soft_kept,
    )
    return {
        "ok": True,
        "sticky_cleared": cleared,
        "torn_down": torn,
        "soft_kept": soft_kept,
        "restart_bg": 0,
        "session_mode": False,
        "pool_mode": True,
    }


async def _restart_warm_unit_bg(room_id: uuid.UUID) -> None:
    """После leave: re-apply srv, settle → active. Не держит HTTP leave."""
    from app.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            room = await db.get(Olcrtc2Room, room_id)
            if not room:
                return
            applied = await apply_olcrtc2_unit(db, room)
            if not applied.get("ok"):
                logger.warning(
                    "olcrtc2 leave bg re-apply fail unit=%s: %s — teardown",
                    room.unit_name,
                    applied.get("message"),
                )
                await teardown_olcrtc2_unit(db, room)
                await db.delete(room)
                await db.commit()
                return
            await asyncio.sleep(SETTLE_AFTER_APPLY_SEC)
            room = await db.get(Olcrtc2Room, room_id)
            if not room:
                return
            room.status = "active"
            room.last_healthy_at = _now()
            room.last_error = None
            await db.commit()
            logger.info(
                "olcrtc2 leave bg ready unit=%s room=%s",
                room.unit_name,
                room.room_url,
            )
    except Exception:
        logger.exception("olcrtc2 leave bg restart room_id=%s", room_id)


async def heartbeat(
    db: AsyncSession,
    *,
    room_db_id: str,
    fingerprint: str = "",
    provider: str = "",
    device_type: str = "",
    online: bool = True,
) -> dict[str, Any]:
    if not online:
        return await release_session_room(
            db,
            room_db_id=room_db_id,
            fingerprint=fingerprint,
            provider=provider,
            reason="heartbeat_offline",
        )
    try:
        rid = uuid.UUID(room_db_id.strip())
    except ValueError:
        return {"ok": False, "detail": "bad room_db_id"}
    room = await db.get(Olcrtc2Room, rid)
    if not room:
        return {"ok": False, "detail": "room not found"}
    room.last_healthy_at = _now()
    if fingerprint:
        await _save_sticky(
            db,
            fingerprint,
            provider or room.provider,
            _norm_dt(device_type or room.device_type),
            room.id,
            commit=False,
        )
        await _touch_devices_online(
            db,
            fingerprint,
            device_type=_norm_dt(device_type or room.device_type),
            cell_id=room.cell_id,
        )
    await _recount(db, room)
    await db.commit()
    return {"ok": True, "online_count": room.online_count}


async def report_room_failure(
    db: AsyncSession,
    *,
    room_db_id: str = "",
    fingerprint: str = "",
    provider: str = "",
    device_type: str = "",
    detail: str = "",
) -> dict[str, Any]:
    fp = (fingerprint or "").strip()[:128]
    prov = (provider or "").strip().lower() or "telemost"
    rid = (room_db_id or "").strip()
    key = f"{fp}|{prov}|{rid}"
    now = time.time()
    last = _failure_first_seen_at.get(key)
    hard = last is not None and (now - last) <= FAILURE_HARD_ESCALATE_SEC
    if hard:
        _failure_first_seen_at.pop(key, None)
        reason = f"failure:{detail[:80]}"
    else:
        _failure_first_seen_at[key] = now
        # first hit: keep room/unit, clear sticky only (client will request fresh config)
        reason = f"suspect_failure:{detail[:80]}"
    return await release_session_room(
        db,
        room_db_id=room_db_id,
        fingerprint=fingerprint,
        provider=provider,
        reason=reason,
    )


async def assign_public_config(
    db: AsyncSession,
    *,
    device_type: str = "",
    fingerprint: str = "",
    preferred_provider: str = "",
) -> dict[str, Any]:
    settings = await load_olcrtc2_settings(db)
    dt = _norm_dt(device_type)
    prov = _norm_prov(preferred_provider, settings)
    fp = (fingerprint or "").strip()
    from app.services.olcrtc2_settings import enabled_providers

    allowed = enabled_providers(settings)
    if prov not in allowed:
        return denied_config(
            settings,
            device_type=dt,
            detail=f"провайдер {prov} выключен в админке (Warm: {', '.join(allowed)})",
            fingerprint=fp,
        )

    if not settings.get("enabled"):
        return denied_config(
            settings, device_type=dt, detail="olcrtc2 disabled", fingerprint=fp
        )

    # Product path: agent session-mode
    if settings.get("agent_enabled"):
        if not fp:
            return denied_config(
                settings,
                device_type=dt,
                detail="Нет fingerprint устройства — откройте меню после входа / перезапустите приложение",
                fingerprint=fp,
            )
        row = await ensure_session_room(
            db, fingerprint=fp, device_type=dt, provider=prov
        )
        if row and row.room_url and len(row.crypto_key) == 64:
            return room_to_public_config(
                settings,
                room_url=row.room_url,
                crypto_key=row.crypto_key,
                provider=row.provider,
                device_type=dt,
                room_db_id=str(row.id),
                unit_name=row.unit_name,
                fingerprint=fp,
                auth_token=row.auth_token or "",
            )
        _note_pool_denied(prov, dt)
        return denied_config(
            settings,
            device_type=dt,
            detail=NO_ROOM_DETAIL,
            fingerprint=fp,
        )

    # Diag fallback: single static room from settings
    room = (settings.get("room") or "").strip()
    key = (settings.get("crypto_key") or "").strip()
    if room and len(key) == 64:
        return room_to_public_config(
            settings,
            room_url=room,
            crypto_key=key,
            provider=prov,
            device_type=dt,
            room_db_id="olcrtc2-static",
            unit_name="olcrtc2-static",
            fingerprint=fp,
        )
    return denied_config(
        settings,
        device_type=dt,
        detail="включите agent_enabled в админке (Варианты обхода → olcrtc 2.0) или задайте diag room",
        fingerprint=fp,
    )


async def prune_stale_sessions(db: AsyncSession) -> dict[str, Any]:
    """Как 1.0.160: stale sticky снять + recount; комнаты живут.
    Tear только error / stuck provisioning / excess empty warm.
    """
    from datetime import timedelta

    settings = await load_olcrtc2_settings(db)
    cutoff = _now() - timedelta(seconds=HEARTBEAT_STALE_SEC)

    # 1) Снять протухшие sticky без убийства комнат
    stale_stickies = (
        await db.execute(select(Olcrtc2Sticky).where(Olcrtc2Sticky.updated_at < cutoff))
    ).scalars().all()
    sticky_cleared = 0
    affected_rooms: set[uuid.UUID] = set()
    for st in stale_stickies:
        affected_rooms.add(st.room_id)
        await db.delete(st)
        sticky_cleared += 1
    if sticky_cleared:
        await db.commit()
        for rid in affected_rooms:
            room = await db.get(Olcrtc2Room, rid)
            if room:
                await _recount(db, room)
        await db.commit()
        logger.info("olcrtc2 prune stale stickies=%s rooms_touched=%s", sticky_cleared, len(affected_rooms))

    rows = (
        await db.execute(
            select(Olcrtc2Room).where(
                Olcrtc2Room.status.in_(("active", "error", "provisioning"))
            )
        )
    ).scalars().all()
    torn = 0
    free_kept: dict[str, list[Olcrtc2Room]] = {}

    for room in rows:
        stickies = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Olcrtc2Sticky)
                    .where(Olcrtc2Sticky.room_id == room.id)
                )
            ).scalar()
            or 0
        )
        age_ok = bool(
            room.created_at and room.created_at >= (_now() - timedelta(seconds=HEARTBEAT_STALE_SEC))
        )

        if room.status == "error":
            await teardown_olcrtc2_unit(db, room)
            await _remote_delete_room(room)
            await db.delete(room)
            torn += 1
            await db.commit()
            continue

        if stickies > 0:
            # Живые клиенты / свежие sticky — комнату не трогаем
            want = _max_clients_for(room.provider or "")
            if int(room.max_clients or 1) != want:
                room.max_clients = want
                await db.commit()
            continue

        if room.status == "provisioning" and age_ok:
            continue
        if room.status == "provisioning" and not age_ok:
            await teardown_olcrtc2_unit(db, room)
            await _remote_delete_room(room)
            await db.delete(room)
            torn += 1
            await db.commit()
            continue

        want = _max_clients_for(room.provider or "")
        if int(room.max_clients or 1) != want:
            room.max_clients = want
            await db.commit()

        key = f"{room.provider}:{room.device_type or 'pc'}"
        free_kept.setdefault(key, []).append(room)

    for key, rooms in free_kept.items():
        rooms.sort(key=lambda r: r.created_at or _now())
        prov = (key.split(":")[0] if ":" in key else "") or "telemost"
        keep_n = max(0, warm_pool_for(settings, prov))
        excess = rooms[keep_n:]
        for room in excess:
            # Клиент мог потерять sticky (HB fail / баг leave), но peer ещё жив.
            # Для idle excess 15 мин keep = Сота1 на 100% после inflate warm=20.
            healthy_at = room.last_healthy_at or room.created_at
            if healthy_at:
                age = (_now() - healthy_at).total_seconds()
                if age < EXCESS_WARM_KEEP_SEC:
                    logger.info(
                        "olcrtc2 prune keep recent-healthy unit=%s age=%.0fs (skip excess tear)",
                        room.unit_name,
                        age,
                    )
                    continue
            await teardown_olcrtc2_unit(db, room)
            await _remote_delete_room(room)
            await db.delete(room)
            torn += 1
            await db.commit()

    return {
        "ok": True,
        "torn_down": torn,
        "sticky_cleared": sticky_cleared,
        "warm_target": {
            "telemost": warm_pool_for(settings, "telemost"),
            "wbstream": warm_pool_for(settings, "wbstream"),
        },
    }


async def pool_stats(db: AsyncSession) -> dict[str, Any]:
    rows = (await db.execute(select(Olcrtc2Room))).scalars().all()
    active = [r for r in rows if r.status == "active"]
    free_pc = 0
    free_android = 0
    for r in active:
        stickies = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Olcrtc2Sticky)
                    .where(Olcrtc2Sticky.room_id == r.id)
                )
            ).scalar()
            or 0
        )
        if stickies == 0:
            if (r.device_type or "") == "android":
                free_android += 1
            else:
                free_pc += 1
    sticky_total = int(
        (await db.execute(select(func.count()).select_from(Olcrtc2Sticky))).scalar() or 0
    )
    return {
        "rooms": len(rows),
        "active": len(active),
        # Sticky = живые сессии (не дрейфующий online_count).
        "online": sticky_total,
        "sessions": sticky_total,
        "provisioning": sum(1 for r in rows if r.status == "provisioning"),
        "error": sum(1 for r in rows if r.status == "error"),
        "warm_free_pc": free_pc,
        "warm_free_android": free_android,
    }
