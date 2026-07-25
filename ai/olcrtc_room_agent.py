"""Агент провижининга комнат olcrtc под массу (1000+).

Не связан с VK-агентом хешей. Не делает рандомную регистрацию.

Масштаб:
- Jitsi: создаёт URL без аккаунта (guest room name) → основной путь на массу.
- WB/Telemost: только через Playwright storage_state стабильных аккаунтов.
- Держит capacity_total >= target_capacity (дефолт 1100 = 1000 online + ~10%).
- free_ratio — доп. запас под нагрузкой (когда online > 0).
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import AppSetting
from app.services.olcrtc_room_accounts import (
    load_room_accounts,
    resolve_storage_state,
)
from app.services.olcrtc_settings import (
    OlcrtcRoomSlot,
    is_placeholder_room,
    load_olcrtc_settings,
    save_olcrtc_settings,
)
from app.services.olcrtc_rooms_db import (
    create_room_row,
    list_rooms,
    pool_metrics,
    sync_rooms_from_settings_json,
    write_all_unit_yaml_from_db,
)
from app.services.olcrtc_assign import pick_cell_for_new_room, reconcile_stale_online
from ai.olcrtc_room_provision import create_room, playwright_available

logger = logging.getLogger(__name__)

AGENT_KEY = "olcrtc_room_agent"
CHECK_INTERVAL_SECONDS = 1800  # 30 min
STARTUP_DELAY_SECONDS = 25
PROVIDERS_PLAYWRIGHT = ("wbstream", "telemost")
REQUIRED_SLOTS = ("pc", "android")
TARGET_FREE_RATIO = 0.10
TARGET_CAPACITY = 1100  # слотов под ~1000 online + запас
MAX_CREATE_PER_CYCLE = 24
DEFAULT_MAX_CLIENTS = 25

JITSI_BASE_PC = "https://meet.egovm.ru/SilentVpnOlcrtcHive"
JITSI_BASE_ANDROID = "https://meet.playform.ru/SilentVpnOlcrtcHiveAndroid"


@dataclass
class AgentState:
    enabled: bool = False
    last_run_at: str = ""
    last_error: str = ""
    last_ok: str = ""
    run_log: list[str] = field(default_factory=list)
    cooldown_until: str = ""
    auto_apply_yaml: bool = True
    target_free_ratio: float = TARGET_FREE_RATIO
    target_capacity: int = TARGET_CAPACITY
    max_clients: int = DEFAULT_MAX_CLIENTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "last_ok": self.last_ok,
            "run_log": list(self.run_log)[-40:],
            "cooldown_until": self.cooldown_until,
            "auto_apply_yaml": self.auto_apply_yaml,
            "target_free_ratio": self.target_free_ratio,
            "target_capacity": self.target_capacity,
            "max_clients": self.max_clients,
            "playwright_available": playwright_available(),
            "managed_providers": ["jitsi", *PROVIDERS_PLAYWRIGHT],
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_agent_state(raw: dict[str, Any] | None) -> AgentState:
    d = raw or {}
    log = d.get("run_log") or []
    if not isinstance(log, list):
        log = []
    return AgentState(
        enabled=bool(d.get("enabled", False)),
        last_run_at=str(d.get("last_run_at") or ""),
        last_error=str(d.get("last_error") or ""),
        last_ok=str(d.get("last_ok") or ""),
        run_log=[str(x) for x in log][-40:],
        cooldown_until=str(d.get("cooldown_until") or ""),
        auto_apply_yaml=bool(d.get("auto_apply_yaml", True)),
        target_free_ratio=float(d.get("target_free_ratio") or TARGET_FREE_RATIO),
        target_capacity=max(0, int(d.get("target_capacity") or TARGET_CAPACITY)),
        max_clients=max(1, int(d.get("max_clients") or DEFAULT_MAX_CLIENTS)),
    )


async def load_agent_state(db: AsyncSession) -> AgentState:
    result = await db.execute(select(AppSetting).where(AppSetting.key == AGENT_KEY))
    row = result.scalar_one_or_none()
    if not row:
        return AgentState()
    try:
        return parse_agent_state(json.loads(row.value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return AgentState()


async def save_agent_state(db: AsyncSession, state: AgentState) -> AgentState:
    payload = json.dumps(
        {
            "enabled": state.enabled,
            "last_run_at": state.last_run_at,
            "last_error": state.last_error,
            "last_ok": state.last_ok,
            "run_log": state.run_log[-40:],
            "cooldown_until": state.cooldown_until,
            "auto_apply_yaml": state.auto_apply_yaml,
            "target_free_ratio": state.target_free_ratio,
            "target_capacity": state.target_capacity,
            "max_clients": state.max_clients,
        },
        ensure_ascii=False,
    )
    result = await db.execute(select(AppSetting).where(AppSetting.key == AGENT_KEY))
    row = result.scalar_one_or_none()
    if row:
        row.value = payload
    else:
        db.add(AppSetting(key=AGENT_KEY, value=payload))
    await db.commit()
    return state


def _log(state: AgentState, line: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    state.run_log.append(f"{ts} {line}")
    state.run_log = state.run_log[-40:]
    logger.info("olcrtc_room_agent: %s", line)


def _ensure_slot(rooms: list[OlcrtcRoomSlot], slot_id: str) -> OlcrtcRoomSlot:
    for r in rooms:
        if r.id == slot_id or slot_id in (r.device_types or []):
            return r
    slot = OlcrtcRoomSlot(id=slot_id, url="", max_clients=4, device_types=[slot_id])
    rooms.append(slot)
    return slot


def _needs_room(url: str) -> bool:
    return is_placeholder_room(url)


def _jitsi_url(slot_label: str) -> str:
    base = JITSI_BASE_ANDROID if slot_label == "android" else JITSI_BASE_PC
    suffix = secrets.token_hex(3)
    return f"{base}-{suffix}"


async def _provision_jitsi(
    db: AsyncSession,
    state: AgentState,
    *,
    slot_label: str,
) -> bool:
    url = _jitsi_url(slot_label)
    cell = await pick_cell_for_new_room(db)
    cell_id = None if getattr(cell, "is_queen", True) else cell.id
    row = await create_room_row(
        db,
        provider="jitsi",
        room_url=url,
        slot_label=slot_label,
        device_types=[slot_label],
        max_clients=state.max_clients,
        cell_id=cell_id,
        status="active",
    )
    _log(state, f"jitsi/{slot_label}: ok → {url} unit={row.unit_name}")
    return True


async def _provision_playwright(
    db: AsyncSession,
    state: AgentState,
    *,
    provider: str,
    slot_label: str,
    storage: dict,
) -> bool:
    if not playwright_available():
        state.last_error = f"{provider}/{slot_label}: playwright недоступен"
        _log(state, state.last_error)
        return False
    _log(state, f"{provider}/{slot_label}: creating room…")
    result = await create_room(provider, storage, headless=True)
    if not result.ok or not result.room_id:
        state.last_error = f"{provider}/{slot_label}: fail — {result.message}"
        _log(state, state.last_error)
        return False
    cell = await pick_cell_for_new_room(db)
    cell_id = None if getattr(cell, "is_queen", True) else cell.id
    row = await create_room_row(
        db,
        provider=provider,
        room_url=result.room_id,
        slot_label=slot_label,
        device_types=[slot_label],
        max_clients=state.max_clients,
        cell_id=cell_id,
        status="active",
    )
    _log(state, f"{provider}/{slot_label}: ok → {result.room_id} unit={row.unit_name}")
    return True


def _needs_expand(metrics: dict[str, Any], state: AgentState) -> bool:
    cap = int(metrics.get("capacity_total") or 0)
    free = int(metrics.get("free_slots") or 0)
    online = int(metrics.get("online_total") or 0)
    target_cap = int(state.target_capacity or TARGET_CAPACITY)
    if cap < target_cap:
        return True
    if online <= 0:
        return False
    ratio = (free / cap) if cap else 0.0
    return ratio < float(state.target_free_ratio or TARGET_FREE_RATIO)


async def _slot_capacity(db: AsyncSession, *, provider: str, slot: str) -> int:
    rooms = await list_rooms(db, provider=provider, status="active")
    return sum(
        int(r.max_clients or 0)
        for r in rooms
        if r.slot_label == slot or slot in (r.device_types or [])
    )


async def heal_rooms(db: AsyncSession, *, force: bool = False) -> AgentState:
    state = await load_agent_state(db)
    if not state.enabled and not force:
        return state

    state.last_run_at = _now_iso()
    state.last_error = ""
    created_any = False

    await sync_rooms_from_settings_json(db)
    await reconcile_stale_online(db)
    settings = await load_olcrtc_settings(db)
    accounts = await load_room_accounts(db)

    # 1) минимум pc/android для WB/Telemost (нужны cookies)
    for provider in PROVIDERS_PLAYWRIGHT:
        pcfg = settings.providers.get(provider)
        if not pcfg or not pcfg.enabled:
            _log(state, f"{provider}: skip (disabled)")
            continue
        rooms = list(pcfg.rooms) if pcfg.rooms else []
        for sid in REQUIRED_SLOTS:
            _ensure_slot(rooms, sid)
        acc_list = accounts.telemost if provider == "telemost" else accounts.wbstream
        storage = None
        for acc in acc_list:
            storage = resolve_storage_state(acc)
            if storage:
                break
        for sid in REQUIRED_SLOTS:
            slot = _ensure_slot(rooms, sid)
            if not _needs_room(slot.url):
                # если в JSON есть, но в БД нет — sync уже сделал; иначе skip
                continue
            if not storage:
                state.last_error = f"{provider}/{sid}: нет storage_state"
                _log(state, state.last_error)
                continue
            if await _provision_playwright(
                db, state, provider=provider, slot_label=sid, storage=storage
            ):
                created_any = True
        settings.providers[provider] = pcfg

    # 2) масштаб: capacity до target_capacity (Jitsi — основной автопуть)
    metrics = await pool_metrics(db)
    _log(
        state,
        f"pool free={metrics.get('free_slots')}/{metrics.get('capacity_total')} "
        f"online={metrics.get('online_total')} target_cap={state.target_capacity}",
    )
    created_cycle = 0
    jitsi_cfg = settings.providers.get("jitsi")
    jitsi_on = bool(jitsi_cfg and jitsi_cfg.enabled)

    while _needs_expand(metrics, state) and created_cycle < MAX_CREATE_PER_CYCLE:
        # балансируем pc/android по ёмкости jitsi
        if jitsi_on:
            pc_cap = await _slot_capacity(db, provider="jitsi", slot="pc")
            an_cap = await _slot_capacity(db, provider="jitsi", slot="android")
            slot_label = "pc" if pc_cap <= an_cap else "android"
            if await _provision_jitsi(db, state, slot_label=slot_label):
                created_any = True
                metrics = await pool_metrics(db)
            created_cycle += 1
            continue

        # fallback: playwright providers если jitsi выключен
        provider = PROVIDERS_PLAYWRIGHT[created_cycle % len(PROVIDERS_PLAYWRIGHT)]
        pcfg = settings.providers.get(provider)
        if not pcfg or not pcfg.enabled:
            created_cycle += 1
            if created_cycle >= MAX_CREATE_PER_CYCLE:
                break
            continue
        acc_list = accounts.telemost if provider == "telemost" else accounts.wbstream
        storage = None
        for acc in acc_list:
            storage = resolve_storage_state(acc)
            if storage:
                break
        if not storage:
            state.last_error = f"pool expand: нет аккаунта для {provider}"
            _log(state, state.last_error)
            break
        slot_label = REQUIRED_SLOTS[created_cycle % len(REQUIRED_SLOTS)]
        if await _provision_playwright(
            db, state, provider=provider, slot_label=slot_label, storage=storage
        ):
            created_any = True
            metrics = await pool_metrics(db)
        created_cycle += 1

    if created_any:
        await save_olcrtc_settings(db, settings)
        state.last_ok = _now_iso()
        if state.auto_apply_yaml:
            try:
                files = await write_all_unit_yaml_from_db(db)
                settings.srv_message = (
                    f"room agent wrote {len(files)} units; "
                    "run apply_olcrtc_units_from_db.py / deploy_olcrtc_cell.py"
                )
                settings.srv_status = "pending_apply"
                await save_olcrtc_settings(db, settings)
                _log(state, f"yaml units: {len(files)}")
            except Exception as e:
                _log(state, f"yaml write error: {e}")
                state.last_error = str(e)[:200]
    else:
        _log(state, "no rooms created this cycle")

    await save_agent_state(db, state)
    return state


async def agent_heal_background(*, force: bool = False) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await heal_rooms(db, force=force)
    except Exception:
        logger.exception("olcrtc_room_agent heal failed")


async def monitor_loop() -> None:
    logger.info("olcrtc room agent monitor starting…")
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                state = await load_agent_state(db)
                if state.enabled:
                    await heal_rooms(db, force=False)
        except Exception:
            logger.exception("olcrtc room agent monitor error")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_room_agent_background():
    loop = asyncio.get_event_loop()
    task = loop.create_task(monitor_loop())
    logger.info("olcrtc room agent monitor started")
    return task
