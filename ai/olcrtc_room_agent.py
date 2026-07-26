"""Агент провижининга комнат olcrtc (Jitsi + Telemost + WB Stream).

Не связан с VK-агентом хешей. Не делает рандомную регистрацию.

Масштаб:
- Jitsi: guest URL без аккаунта → основной объём до target_capacity.
- Telemost / WB: Playwright на host-сервисе (Chromium вне Docker) + storage_state.
- Держит минимум active-комнат на TM/WB (target_rooms_*), heal status=error.
"""
from __future__ import annotations

import asyncio
import json
import logging
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
from ai.olcrtc_host_provision_client import (
    create_room_best,
    host_provision_status,
    push_storage_to_host,
)
from ai.olcrtc_room_provision import playwright_available

logger = logging.getLogger(__name__)

AGENT_KEY = "olcrtc_room_agent"
CHECK_INTERVAL_SECONDS = 1800  # 30 min
STARTUP_DELAY_SECONDS = 25
PROVIDERS_PLAYWRIGHT = ("telemost", "wbstream")
REQUIRED_SLOTS = ("pc", "android")
TARGET_FREE_RATIO = 0.10
TARGET_CAPACITY = 1100
# Сколько active-комнат держать на TM/WB (pc+android суммарно)
TARGET_ROOMS_TELEMOST = 4
TARGET_ROOMS_WBSTREAM = 4
MAX_CREATE_PER_CYCLE = 24
DEFAULT_MAX_CLIENTS = 1000


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
    target_rooms_telemost: int = TARGET_ROOMS_TELEMOST
    target_rooms_wbstream: int = TARGET_ROOMS_WBSTREAM
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
            "target_rooms_telemost": self.target_rooms_telemost,
            "target_rooms_wbstream": self.target_rooms_wbstream,
            "max_clients": self.max_clients,
            "playwright_available": playwright_available(),
            "managed_providers": list(PROVIDERS_PLAYWRIGHT),
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
        target_rooms_telemost=max(0, int(d.get("target_rooms_telemost") or TARGET_ROOMS_TELEMOST)),
        target_rooms_wbstream=max(0, int(d.get("target_rooms_wbstream") or TARGET_ROOMS_WBSTREAM)),
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
            "target_rooms_telemost": state.target_rooms_telemost,
            "target_rooms_wbstream": state.target_rooms_wbstream,
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


def _storage_for(accounts: Any, provider: str) -> dict[str, Any] | None:
    acc_list = accounts.telemost if provider == "telemost" else accounts.wbstream
    for acc in acc_list:
        storage = resolve_storage_state(acc)
        if storage:
            return storage
    return None


async def _sync_storage_to_host(state: AgentState, accounts: Any) -> None:
    for provider in PROVIDERS_PLAYWRIGHT:
        storage = _storage_for(accounts, provider)
        if not storage:
            continue
        ok = await push_storage_to_host(provider, storage)
        _log(state, f"host storage {provider}: {'ok' if ok else 'skip/fail'}")


async def _provision_playwright(
    db: AsyncSession,
    state: AgentState,
    *,
    provider: str,
    slot_label: str,
    storage: dict[str, Any] | None,
) -> bool:
    _log(state, f"{provider}/{slot_label}: creating room (host/local)…")
    result = await create_room_best(provider, storage, headless=True)
    if not result.ok or not result.room_id:
        raw = (result.message or "").strip()
        hint = raw
        low = raw.lower()
        if "all connection attempts failed" in low or "err_connection" in low:
            hint = (
                f"{raw} — Playwright на хосте не достучался до сайта "
                f"{'stream.wb.ru' if provider == 'wbstream' else 'telemost.yandex.ru'}. "
                f"Проверьте cookies аккаунта (Сохранить аккаунты), сеть Улья и "
                f"silent-olcrtc-host-provision (systemctl status)."
            )
        elif "storage_state" in low or "нет storage" in low:
            hint = f"{raw} — заново сохраните storage_state в админке (аккаунт протух)."
        state.last_error = f"{provider}/{slot_label}: ошибка — {hint}"
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
    _log(
        state,
        f"{provider}/{slot_label}: ok → {result.room_id} unit={row.unit_name} via={result.message}",
    )
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


async def _active_room_count(db: AsyncSession, *, provider: str) -> int:
    rooms = await list_rooms(db, provider=provider, status="active")
    return len(rooms)


async def _pick_slot_for_provider(db: AsyncSession, *, provider: str) -> str:
    pc_cap = await _slot_capacity(db, provider=provider, slot="pc")
    an_cap = await _slot_capacity(db, provider=provider, slot="android")
    return "pc" if pc_cap <= an_cap else "android"


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

    host_st = await host_provision_status()
    _log(
        state,
        f"host-provision reachable={host_st.get('reachable')} "
        f"pw={host_st.get('playwright')} tm_state={host_st.get('telemost_state')} "
        f"wb_state={host_st.get('wbstream_state')} url={host_st.get('url') or '-'}",
    )
    await _sync_storage_to_host(state, accounts)

    # 0) status=error → пересоздать
    error_rooms = await list_rooms(db, status="error")
    for room in error_rooms[:12]:
        slot = (room.slot_label or "pc").strip().lower() or "pc"
        if room.provider == "jitsi":
            # Jitsi снят с поддержки — drain старых комнат
            room.status = "draining"
            room.last_error = "jitsi removed"
            created_any = True
            _log(state, f"drain legacy jitsi/{slot} unit={room.unit_name}")
            continue
        if room.provider in PROVIDERS_PLAYWRIGHT:
            storage = _storage_for(accounts, room.provider)
            result = await create_room_best(room.provider, storage, headless=True)
            if result.ok and result.room_id:
                room.room_url = result.room_id
                room.status = "active"
                room.online_count = 0
                room.last_error = ""
                created_any = True
                _log(
                    state,
                    f"heal error {room.provider}/{slot}: → {result.room_id} unit={room.unit_name}",
                )
            else:
                _log(
                    state,
                    f"heal error {room.provider}/{slot}: fail — {result.message}",
                )
                state.last_error = result.message[:200]
    if created_any:
        await db.commit()

    # 1) минимум pc/android в settings JSON (placeholder → создать)
    for provider in PROVIDERS_PLAYWRIGHT:
        pcfg = settings.providers.get(provider)
        if not pcfg or not pcfg.enabled:
            _log(state, f"{provider}: skip (disabled)")
            continue
        rooms = list(pcfg.rooms) if pcfg.rooms else []
        for sid in REQUIRED_SLOTS:
            _ensure_slot(rooms, sid)
        storage = _storage_for(accounts, provider)
        for sid in REQUIRED_SLOTS:
            slot = _ensure_slot(rooms, sid)
            if not _needs_room(slot.url):
                continue
            if await _provision_playwright(
                db, state, provider=provider, slot_label=sid, storage=storage
            ):
                created_any = True
                # обновить JSON слот свежим id из БД
                active = await list_rooms(db, provider=provider, status="active")
                for r in active:
                    if r.slot_label == sid or sid in (r.device_types or []):
                        slot.url = r.room_url
                        break
        pcfg.rooms = rooms
        settings.providers[provider] = pcfg

    # 2) догнать target_rooms для TM/WB (не только placeholder)
    created_cycle = 0
    for provider in PROVIDERS_PLAYWRIGHT:
        pcfg = settings.providers.get(provider)
        if not pcfg or not pcfg.enabled:
            continue
        target = (
            state.target_rooms_telemost
            if provider == "telemost"
            else state.target_rooms_wbstream
        )
        storage = _storage_for(accounts, provider)
        while created_cycle < MAX_CREATE_PER_CYCLE:
            n = await _active_room_count(db, provider=provider)
            if n >= target:
                _log(state, f"{provider}: rooms ok {n}/{target}")
                break
            slot_label = await _pick_slot_for_provider(db, provider=provider)
            if await _provision_playwright(
                db, state, provider=provider, slot_label=slot_label, storage=storage
            ):
                created_any = True
            else:
                break
            created_cycle += 1

    # 3) метрики пула (TM+WB only; Jitsi не расширяем)
    metrics = await pool_metrics(db)
    _log(
        state,
        f"pool free={metrics.get('free_slots')}/{metrics.get('capacity_total')} "
        f"online={metrics.get('online_total')} target_cap={state.target_capacity}",
    )

    if created_any:
        await save_olcrtc_settings(db, settings)
        state.last_ok = _now_iso()
        if state.auto_apply_yaml:
            try:
                files = await write_all_unit_yaml_from_db(db)
                settings.srv_message = (
                    f"Агент записал YAML ({len(files)} unit’ов). "
                    f"На VPS: python scripts/apply_olcrtc_units_from_db.py "
                    f"(или deploy_olcrtc_cell.py для сот)."
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
