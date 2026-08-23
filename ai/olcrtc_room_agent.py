"""Агент провижининга комнат olcrtc (Telemost + WB Stream).

Не связан с VK-агентом хешей. Не делает рандомную регистрацию.

Session-mode (по умолчанию, «как VK»):
1) sync WB auth.token из storage_state
2) host-health prune мёртвых
3) heal status=error → пересоздать ту же «дырку»
4) optional bootstrap_warm (1 spare pc/android) — без min_free autoscale
5) YAML/unit apply

Legacy pool-mode (session_mode=false): + autoscale min_free + idle GC.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import AppSetting
from app.services.olcrtc_room_accounts import (
    load_room_accounts,
    resolve_storage_state,
    sync_wbstream_auth_token_to_settings,
)
from app.services.olcrtc_settings import (
    OlcrtcRoomSlot,
    is_placeholder_room,
    load_olcrtc_settings,
    save_olcrtc_settings,
)
from app.services.olcrtc_rooms_db import (
    _clear_sticky_for_room,
    create_room_row,
    delete_room_row,
    list_rooms,
    pool_metrics,
    sync_rooms_from_settings_json,
    write_all_unit_yaml_from_db,
)
from app.services.olcrtc_assign import pick_cell_for_new_room, reconcile_stale_online
from ai.olcrtc_host_provision_client import (
    apply_units_via_host,
    create_room_best,
    host_provision_status,
    host_unit_health,
    push_storage_to_host,
)
from ai.olcrtc_room_liveness import probe_room
from ai.olcrtc_room_provision import playwright_available

logger = logging.getLogger(__name__)

AGENT_KEY = "olcrtc_room_agent"
CHECK_INTERVAL_SECONDS = 150  # ~2.5 мин — prune/heal без долгого ожидания
STARTUP_DELAY_SECONDS = 25
SCALE_DEBOUNCE_SECONDS = 45
PROVIDERS_PLAYWRIGHT = ("telemost", "wbstream")
REQUIRED_SLOTS = ("pc", "android")
# Legacy (не крутят скейл в session_mode; оставлены в state для старых клиентов API)
TARGET_FREE_RATIO = 0.10
TARGET_CAPACITY = 0
TARGET_ROOMS_TELEMOST = 0
TARGET_ROOMS_WBSTREAM = 0
MAX_CREATE_PER_CYCLE = 1  # один Playwright за цикл; host Semaphore(1)
MAX_PROBE_PER_CYCLE = 20
DEFAULT_MAX_CLIENTS = 1  # session: 1 сессия = 1 комната
# Session-mode: без фонового запаса. Pool-mode legacy: min_free/min_rooms.
MIN_FREE_PER_SLOT = 0
MIN_ROOMS_PER_SLOT = 0
MAX_ROOMS_PER_SLOT = 64
IDLE_ROOM_TTL_MIN = 5


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
    liveness_prune: bool = True
    last_liveness: dict[str, Any] = field(default_factory=dict)
    min_free_per_slot: int = MIN_FREE_PER_SLOT
    min_rooms_per_slot: int = MIN_ROOMS_PER_SLOT
    max_rooms_per_slot: int = MAX_ROOMS_PER_SLOT
    idle_room_ttl_min: int = IDLE_ROOM_TTL_MIN
    auto_units: bool = True
    idle_since: dict[str, str] = field(default_factory=dict)
    last_scale: dict[str, Any] = field(default_factory=dict)
    # VK-like: create on demand, без min_free autoscale / create-spam
    session_mode: bool = True
    # 0 = нет spare; 1 = одна прогретая комната на pc и android (telemost)
    bootstrap_warm: int = 0

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
            "liveness_prune": self.liveness_prune,
            "last_liveness": dict(self.last_liveness or {}),
            "min_free_per_slot": self.min_free_per_slot,
            "min_rooms_per_slot": self.min_rooms_per_slot,
            "max_rooms_per_slot": self.max_rooms_per_slot,
            "idle_room_ttl_min": self.idle_room_ttl_min,
            "auto_units": self.auto_units,
            "last_scale": dict(self.last_scale or {}),
            "session_mode": self.session_mode,
            "bootstrap_warm": self.bootstrap_warm,
            "playwright_available": playwright_available(),
            "managed_providers": list(PROVIDERS_PLAYWRIGHT),
            "check_interval_seconds": CHECK_INTERVAL_SECONDS,
            "scale_debounce_seconds": SCALE_DEBOUNCE_SECONDS,
            "legacy_targets": {
                "target_capacity": self.target_capacity,
                "target_free_ratio": self.target_free_ratio,
                "target_rooms_telemost": self.target_rooms_telemost,
                "target_rooms_wbstream": self.target_rooms_wbstream,
            },
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_agent_state(raw: dict[str, Any] | None) -> AgentState:
    d = raw or {}
    log = d.get("run_log") or []
    if not isinstance(log, list):
        log = []
    live = d.get("last_liveness") or {}
    if not isinstance(live, dict):
        live = {}
    idle = d.get("idle_since") or {}
    if not isinstance(idle, dict):
        idle = {}
    scale = d.get("last_scale") or {}
    if not isinstance(scale, dict):
        scale = {}
    # session_mode: явный False → legacy pool; иначе True (в т.ч. старые JSON без ключа)
    session_mode = True if "session_mode" not in d else bool(d.get("session_mode"))
    state = AgentState(
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
        liveness_prune=bool(d.get("liveness_prune", True)),
        last_liveness=live,
        min_free_per_slot=max(0, int(d.get("min_free_per_slot") or MIN_FREE_PER_SLOT)),
        min_rooms_per_slot=max(0, int(d.get("min_rooms_per_slot") or MIN_ROOMS_PER_SLOT)),
        max_rooms_per_slot=max(1, int(d.get("max_rooms_per_slot") or MAX_ROOMS_PER_SLOT)),
        idle_room_ttl_min=max(1, int(d.get("idle_room_ttl_min") or IDLE_ROOM_TTL_MIN)),
        auto_units=bool(d.get("auto_units", True)),
        idle_since={str(k): str(v) for k, v in idle.items()},
        last_scale=scale,
        session_mode=session_mode,
        bootstrap_warm=max(0, min(2, int(d.get("bootstrap_warm") or 0))),
    )
    # Старый дефолт 45 мин → 5 (анти-пложение).
    if "idle_room_ttl_min" not in d or int(d.get("idle_room_ttl_min") or 0) == 45:
        state.idle_room_ttl_min = IDLE_ROOM_TTL_MIN
    # Миграция session-mode: убрать массовый пул-скейл из старых state.
    if state.session_mode and "session_mode" not in d:
        state.min_free_per_slot = 0
        state.min_rooms_per_slot = 0
        if state.max_clients > 1 and state.max_clients in (2, 25, 200):
            state.max_clients = 1
    return state


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
            "liveness_prune": state.liveness_prune,
            "last_liveness": state.last_liveness,
            "min_free_per_slot": state.min_free_per_slot,
            "min_rooms_per_slot": state.min_rooms_per_slot,
            "max_rooms_per_slot": state.max_rooms_per_slot,
            "idle_room_ttl_min": state.idle_room_ttl_min,
            "auto_units": state.auto_units,
            "idle_since": state.idle_since,
            "last_scale": state.last_scale,
            "session_mode": state.session_mode,
            "bootstrap_warm": state.bootstrap_warm,
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


async def _sync_wb_auth(db: AsyncSession, state: AgentState) -> bool:
    """Достать JWT из WB storage_state → settings.providers.wbstream.auth_token."""
    try:
        tok = await sync_wbstream_auth_token_to_settings(db)
        if tok:
            _log(state, f"wb auth.token synced len={len(tok)}")
            return True
        _log(state, "wb auth.token: нет accessToken в storage_state")
    except Exception as e:
        _log(state, f"wb auth.token sync fail: {e}"[:160])
    return False


async def _prune_dead_rooms(db: AsyncSession, state: AgentState) -> int:
    """Проверить active TM/WB; мёртвые — hard-delete (+sticky).

    Guest HTTP-join ≠ host в комнате. Пустая «живая» room даёт 403 guest на клиенте.
    После guest-ok дополнительно смотрим journal olcrtc@unit (Link connected).
    """
    if not state.liveness_prune:
        _log(state, "liveness_prune=off — skip")
        return 0

    rooms = []
    for provider in PROVIDERS_PLAYWRIGHT:
        rooms.extend(await list_rooms(db, provider=provider, status="active"))
    for st in ("error", "draining"):
        for provider in PROVIDERS_PLAYWRIGHT:
            for r in await list_rooms(db, provider=provider, status=st):
                err = (r.last_error or "").lower()
                if err.startswith("admin:"):
                    continue
                if any(
                    x in err
                    for x in (
                        "liveness",
                        "not found",
                        "протух",
                        "guests cannot",
                        "status 403",
                        "status 404",
                        "host unhealthy",
                        "мертв",
                    )
                ):
                    rooms.append(r)

    seen: set[Any] = set()
    uniq = []
    for r in rooms:
        if r.id in seen:
            continue
        seen.add(r.id)
        uniq.append(r)

    alive_n = dead_n = unknown_n = deleted = 0
    details: list[dict[str, Any]] = []
    for room in uniq[:MAX_PROBE_PER_CYCLE]:
        if room.provider not in PROVIDERS_PLAYWRIGHT:
            continue
        if is_placeholder_room(room.room_url):
            # Placeholder не живая комната — снести без probe (session wipe leftovers).
            if await delete_room_row(db, room.id, reason="placeholder"):
                deleted += 1
                _log(state, f"liveness DEAD {room.provider}/{room.unit_name} room=PLACEHOLDER")
            continue
        # Не трогать комнаты, которые ещё поднимают srv (session ensure).
        if (room.status or "") == "provisioning":
            continue
        # Grace: только что созданные active — дать Link/host догнать.
        created = getattr(room, "created_at", None)
        if created is not None:
            try:
                age = datetime.now(timezone.utc).replace(tzinfo=None) - (
                    created.replace(tzinfo=None) if getattr(created, "tzinfo", None) else created
                )
                if age.total_seconds() < 90:
                    continue
            except Exception:
                pass
        probe = await probe_room(room.provider, room.room_url)
        item: dict[str, Any] = {
            "unit": room.unit_name,
            "provider": room.provider,
            "room": (room.room_url or "")[:48],
            "alive": probe.alive,
            "reason": probe.reason[:120],
            "http": probe.http_status,
        }
        details.append(item)
        if probe.is_alive:
            # Guest join OK — проверяем, что host unit реально в комнате.
            unit = (room.unit_name or "").strip()
            if unit:
                uh = await host_unit_health(unit)
                item["host"] = {
                    "healthy": uh.get("healthy"),
                    "active": uh.get("active"),
                    "link": uh.get("link_connected"),
                    "msg": str(uh.get("message") or "")[:80],
                }
                if uh.get("healthy") is False:
                    dead_n += 1
                    reason = (
                        f"host unhealthy: {uh.get('message') or uh.get('active')}"
                    )[:500]
                    _log(
                        state,
                        f"liveness HOST-DEAD {room.provider}/{unit} "
                        f"room={room.room_url[:36]} — {reason[:80]}",
                    )
                    ok = await delete_room_row(db, room.id, reason=reason)
                    if ok:
                        deleted += 1
                        item["deleted"] = True
                        item["alive"] = False
                    else:
                        room.status = "error"
                        room.last_error = reason
                    continue
                if uh.get("healthy") is None:
                    # host-provision недоступен — не валим, guest-ok достаточно
                    item["host_skip"] = True
            alive_n += 1
            room.last_healthy_at = datetime.now(timezone.utc).replace(tzinfo=None)
            # Ручные draining/offline из админки не поднимаем обратно в active —
            # иначе «Закрыть набор» / «Выключить» откатываются через ~цикл агента.
            if room.status in ("draining", "offline"):
                item["admin_hold"] = room.status
                continue
            room.last_error = None
            if room.status != "active":
                room.status = "active"
            continue
        if probe.alive is None:
            unknown_n += 1
            _log(
                state,
                f"liveness ? {room.provider}/{room.unit_name}: {probe.reason[:80]}",
            )
            continue
        dead_n += 1
        reason = f"liveness dead: {probe.reason}"[:500]
        _log(
            state,
            f"liveness DEAD {room.provider}/{room.unit_name} "
            f"room={room.room_url[:36]} — {probe.reason[:80]}",
        )
        ok = await delete_room_row(db, room.id, reason=reason)
        if ok:
            deleted += 1
            item["deleted"] = True
        else:
            room.status = "error"
            room.last_error = reason

    await db.commit()
    state.last_liveness = {
        "at": _now_iso(),
        "alive": alive_n,
        "dead": dead_n,
        "unknown": unknown_n,
        "deleted": deleted,
        "probed": len(details),
        "sample": details[:12],
    }
    _log(
        state,
        f"liveness probed={len(details)} alive={alive_n} dead={dead_n} "
        f"unknown={unknown_n} deleted={deleted}",
    )
    return deleted


async def _provision_playwright(
    db: AsyncSession,
    state: AgentState,
    *,
    provider: str,
    slot_label: str,
    storage: dict[str, Any] | None,
) -> bool:
    _log(state, f"{provider}/{slot_label}: creating room…")
    access_token = ""
    if provider == "wbstream":
        access_token = await sync_wbstream_auth_token_to_settings(db) or ""
    result = await create_room_best(
        provider, storage, headless=True, access_token=access_token
    )
    if not result.ok or not result.room_id:
        raw = (result.message or "").strip()
        hint = raw
        low = raw.lower()
        if "antibot" in low or "498" in low or "__wbaas" in low:
            hint = (
                f"{raw} — WB Playwright antibot; API create предпочтителен "
                f"(нужен свежий JWT в storage_state)."
            )
            state.cooldown_until = (
                datetime.now(timezone.utc) + timedelta(hours=6)
            ).isoformat()
        elif "wb api" in low and ("token" in low or "owner" in low):
            hint = f"{raw} — обновите cookies WB в админке (storage_state)."
        elif "all connection attempts failed" in low or "err_connection" in low:
            hint = (
                f"{raw} — Playwright на хосте не достучался до сайта "
                f"{'stream.wb.ru' if provider == 'wbstream' else 'telemost.yandex.ru'}. "
                f"Проверьте cookies аккаунта (Сохранить аккаунты), сеть Улья и "
                f"silent-olcrtc-host-provision (systemctl status)."
            )
        elif "storage_state" in low or "нет storage" in low:
            hint = f"{raw} — заново сохраните storage_state в админке (аккаунт протух)."
        # Если в слоте уже есть живые комнаты — клиенты работают; Playwright-сбой
        # при «досоздать запас» не должен красить всю панель красным.
        existing = _rooms_of_slot(
            await list_rooms(db, provider=provider, status="active"), slot_label
        )
        already_ok = _free_slots(existing) >= max(1, state.min_free_per_slot) or len(existing) > 0
        msg = f"{provider}/{slot_label}: ошибка — {hint}"
        if already_ok:
            _log(state, f"{msg} (пул уже есть — не блокируем)")
        else:
            state.last_error = msg
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


def _wb_in_cooldown(state: AgentState) -> bool:
    raw = (state.cooldown_until or "").strip()
    if not raw:
        return False
    try:
        until = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < until
    except Exception:
        return False


def _rooms_of_slot(rooms: list[Any], slot: str) -> list[Any]:
    return [r for r in rooms if r.slot_label == slot or slot in (r.device_types or [])]


def _free_slots(rooms: list[Any]) -> int:
    return sum(max(0, int(r.max_clients or 0) - int(r.online_count or 0)) for r in rooms)


async def _slot_capacity(db: AsyncSession, *, provider: str, slot: str) -> int:
    rooms = await list_rooms(db, provider=provider, status="active")
    return sum(int(r.max_clients or 0) for r in _rooms_of_slot(rooms, slot))


async def _active_room_count(db: AsyncSession, *, provider: str) -> int:
    rooms = await list_rooms(db, provider=provider, status="active")
    return len(rooms)


async def _pick_slot_for_provider(db: AsyncSession, *, provider: str) -> str:
    pc_cap = await _slot_capacity(db, provider=provider, slot="pc")
    an_cap = await _slot_capacity(db, provider=provider, slot="android")
    return "pc" if pc_cap <= an_cap else "android"


async def _autoscale_pool(
    db: AsyncSession,
    state: AgentState,
    settings: Any,
    accounts: Any,
) -> int:
    """Держать запас свободных слотов на каждой паре (провайдер, pc|android).

    Раньше цель была «4 комнаты на провайдера» — при `max_clients=2` это восемь
    мест на всех, дальше пул не рос и клиент получал «нет свободных комнат».
    """
    created = 0
    plan: list[dict[str, Any]] = []
    for provider in PROVIDERS_PLAYWRIGHT:
        pcfg = settings.providers.get(provider)
        if not pcfg or not pcfg.enabled:
            continue
        if provider == "wbstream" and _wb_in_cooldown(state):
            _log(state, f"{provider}: скейл отложен (antibot cooldown)")
            continue
        storage = _storage_for(accounts, provider)
        for slot in REQUIRED_SLOTS:
            while created < MAX_CREATE_PER_CYCLE:
                rooms = _rooms_of_slot(
                    await list_rooms(db, provider=provider, status="active"), slot
                )
                free = _free_slots(rooms)
                need_min_rooms = len(rooms) < state.min_rooms_per_slot
                need_free = free < state.min_free_per_slot
                if not (need_min_rooms or need_free):
                    plan.append(
                        {"provider": provider, "slot": slot, "rooms": len(rooms), "free": free}
                    )
                    break
                if len(rooms) >= state.max_rooms_per_slot:
                    _log(
                        state,
                        f"{provider}/{slot}: упёрлись в лимит {state.max_rooms_per_slot} комнат "
                        f"(свободно {free}) — поднимите «максимум комнат» или max_clients",
                    )
                    break
                why = "меньше минимума комнат" if need_min_rooms else f"свободно {free}"
                _log(
                    state,
                    f"{provider}/{slot}: скейл вверх ({why} < {state.min_free_per_slot})",
                )
                if not await _provision_playwright(
                    db, state, provider=provider, slot_label=slot, storage=storage
                ):
                    break
                created += 1
    state.last_scale = {"at": _now_iso(), "created": created, "slots": plan}
    return created


async def _gc_idle_rooms(db: AsyncSession, state: AgentState) -> list[str]:
    """Снести давно пустые комнаты сверх нужного запаса, чтобы пул не разрастался."""
    removed: list[str] = []
    now = datetime.now(timezone.utc)
    seen_units: set[str] = set()
    for provider in PROVIDERS_PLAYWRIGHT:
        for slot in REQUIRED_SLOTS:
            rooms = _rooms_of_slot(
                await list_rooms(db, provider=provider, status="active"), slot
            )
            for room in rooms:
                seen_units.add(room.unit_name)
            idle_rooms = [r for r in rooms if int(r.online_count or 0) <= 0]
            busy_free = _free_slots([r for r in rooms if int(r.online_count or 0) > 0])
            # Сортируем от самой новой — старые комнаты стабильнее (их уже прогрели).
            for room in sorted(idle_rooms, key=lambda r: r.created_at or now, reverse=True):
                if len(rooms) - len(removed) <= state.min_rooms_per_slot:
                    break
                keep_free = busy_free + sum(
                    int(r.max_clients or 0)
                    for r in idle_rooms
                    if r.unit_name != room.unit_name and r.unit_name not in removed
                )
                if keep_free < state.min_free_per_slot:
                    break
                first_seen = state.idle_since.get(room.unit_name)
                if not first_seen:
                    state.idle_since[room.unit_name] = _now_iso()
                    continue
                try:
                    since = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
                    if since.tzinfo is None:
                        since = since.replace(tzinfo=timezone.utc)
                except ValueError:
                    state.idle_since[room.unit_name] = _now_iso()
                    continue
                if now - since < timedelta(minutes=state.idle_room_ttl_min):
                    continue
                unit = room.unit_name
                if await delete_room_row(
                    db, room.id, reason=f"idle > {state.idle_room_ttl_min} мин"
                ):
                    removed.append(unit)
                    state.idle_since.pop(unit, None)
                    _log(state, f"убрана простаивающая комната {provider}/{slot} unit={unit}")
    # Комнаты снова заняты или уже удалены — забываем отметку простоя.
    for unit in list(state.idle_since):
        if unit not in seen_units or unit in removed:
            state.idle_since.pop(unit, None)
    busy_units = {
        r.unit_name
        for provider in PROVIDERS_PLAYWRIGHT
        for r in await list_rooms(db, provider=provider, status="active")
        if int(r.online_count or 0) > 0
    }
    for unit in busy_units:
        state.idle_since.pop(unit, None)
    return removed


async def heal_rooms(db: AsyncSession, *, force: bool = False) -> AgentState:
    state = await load_agent_state(db)
    if not state.enabled and not force:
        return state

    state.last_run_at = _now_iso()
    state.last_error = ""
    changed = False

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
    if await _sync_wb_auth(db, state):
        changed = True
        settings = await load_olcrtc_settings(db)

    deleted = await _prune_dead_rooms(db, state)
    if deleted:
        changed = True
        settings = await load_olcrtc_settings(db)

    error_rooms = await list_rooms(db, status="error")
    for room in error_rooms[:12]:
        slot = (room.slot_label or "pc").strip().lower() or "pc"
        if room.provider == "jitsi":
            room.status = "draining"
            room.last_error = "jitsi removed"
            changed = True
            _log(state, f"drain legacy jitsi/{slot} unit={room.unit_name}")
            continue
        if room.provider in PROVIDERS_PLAYWRIGHT:
            if room.provider == "wbstream" and _wb_in_cooldown(state):
                _log(
                    state,
                    f"heal error wbstream/{slot}: skip (antibot cooldown {state.cooldown_until})",
                )
                continue
            storage = _storage_for(accounts, room.provider)
            heal_tok = ""
            if room.provider == "wbstream":
                heal_tok = await sync_wbstream_auth_token_to_settings(db) or ""
            result = await create_room_best(
                room.provider, storage, headless=True, access_token=heal_tok
            )
            if result.ok and result.room_id:
                # Старые sticky держали прошлый room_id → ложный online / залипание.
                cleared = await _clear_sticky_for_room(db, room.id)
                room.room_url = result.room_id
                room.status = "active"
                room.online_count = 0
                room.last_error = None
                room.last_healthy_at = datetime.now(timezone.utc).replace(tzinfo=None)
                changed = True
                _log(
                    state,
                    f"heal error {room.provider}/{slot}: → {result.room_id} "
                    f"unit={room.unit_name} sticky_cleared={cleared}",
                )
            else:
                msg = (result.message or "")[:200]
                _log(state, f"heal error {room.provider}/{slot}: fail — {msg}")
                peers = [
                    r
                    for r in await list_rooms(db, provider=room.provider, status="active")
                    if (r.slot_label or "") == slot or slot in (r.device_types or [])
                ]
                if not peers:
                    state.last_error = f"{room.provider}/{slot}: {msg}"
                low = msg.lower()
                if room.provider == "wbstream" and (
                    "antibot" in low or "498" in low or "__wbaas" in low
                ):
                    state.cooldown_until = (
                        datetime.now(timezone.utc) + timedelta(hours=6)
                    ).isoformat()
                elif "antibot" not in low:
                    await delete_room_row(db, room.id, reason=f"heal fail: {msg}")
                    changed = True
                    _log(state, f"deleted unrecovered error unit={room.unit_name}")
    if changed:
        await db.commit()

    # Плейсхолдеры в settings JSON подтягиваем к реальным комнатам пула.
    # В session_mode комнаты создаёт assign (ensure_session_room), не autoscale.
    all_active = await list_rooms(db, status="active")
    for room in all_active:
        want_max = 1 if state.session_mode else state.max_clients
        if int(room.max_clients or 0) != want_max:
            room.max_clients = want_max
            changed = True
    for provider in PROVIDERS_PLAYWRIGHT:
        pcfg = settings.providers.get(provider)
        if not pcfg or not pcfg.enabled:
            _log(state, f"{provider}: выключен в настройках — пропуск")
            continue
        rooms = list(pcfg.rooms) if pcfg.rooms else []
        active = await list_rooms(db, provider=provider, status="active")
        for sid in REQUIRED_SLOTS:
            slot = _ensure_slot(rooms, sid)
            want_max = 1 if state.session_mode else state.max_clients
            if int(slot.max_clients or 0) != want_max:
                slot.max_clients = want_max
                changed = True
            if not _needs_room(slot.url):
                continue
            for r in _rooms_of_slot(active, sid):
                slot.url = r.room_url
                changed = True
                break
        pcfg.rooms = rooms
        settings.providers[provider] = pcfg

    if state.session_mode:
        warm = await _bootstrap_warm_rooms(db, state, settings, accounts)
        if warm:
            changed = True
        state.last_scale = {
            "at": _now_iso(),
            "mode": "session",
            "created": warm,
            "note": "no autoscale; create on assign",
        }
        _log(state, f"session-mode: prune+heal only (warm={warm})")
        gc_units: list[str] = []
    else:
        if await _autoscale_pool(db, state, settings, accounts):
            changed = True
        gc_units = await _gc_idle_rooms(db, state)
        if gc_units:
            changed = True

    metrics = await pool_metrics(db)
    _log(
        state,
        f"пул: свободно {metrics.get('free_slots')}/{metrics.get('capacity_total')} "
        f"мест, онлайн {metrics.get('online_total')}, комнат {metrics.get('rooms_active')}"
        + (" [session]" if state.session_mode else ""),
    )

    if changed:
        await save_olcrtc_settings(db, settings)
        state.last_ok = _now_iso()
        if state.auto_apply_yaml:
            try:
                files = await write_all_unit_yaml_from_db(db)
                await _apply_units_on_host(state, files, gc_units, settings)
                await save_olcrtc_settings(db, settings)
            except Exception as e:
                _log(state, f"ошибка применения YAML/unit'ов: {e}")
                state.last_error = str(e)[:200]
    else:
        _log(state, "изменений в пуле нет")

    await save_agent_state(db, state)
    return state


async def _bootstrap_warm_rooms(
    db: AsyncSession,
    state: AgentState,
    settings: Any,
    accounts: Any,
) -> int:
    """Опционально одна spare-комната на pc/android (telemost) — без min_free spam."""
    want = max(0, int(state.bootstrap_warm or 0))
    if want <= 0:
        return 0
    created = 0
    provider = "telemost"
    pcfg = settings.providers.get(provider)
    if not pcfg or not pcfg.enabled:
        return 0
    storage = _storage_for(accounts, provider)
    for slot in REQUIRED_SLOTS:
        if created >= MAX_CREATE_PER_CYCLE:
            break
        rooms = _rooms_of_slot(
            await list_rooms(db, provider=provider, status="active"), slot
        )
        idle = [r for r in rooms if int(r.online_count or 0) <= 0]
        if len(idle) >= want:
            continue
        _log(state, f"bootstrap_warm {provider}/{slot}: создаём spare")
        if await _provision_playwright(
            db, state, provider=provider, slot_label=slot, storage=storage
        ):
            created += 1
    return created


async def _apply_units_on_host(
    state: AgentState,
    files: dict[str, str],
    removed_units: list[str],
    settings: Any,
) -> None:
    """Разложить YAML и поднять/погасить srv на Улье."""
    if not state.auto_units:
        settings.srv_status = "pending_apply"
        settings.srv_message = (
            f"YAML на {len(files)} unit’ов записан. Автоподъём unit’ов выключен — "
            f"на VPS: python scripts/apply_olcrtc_units_from_db.py"
        )
        _log(state, f"yaml unit'ов: {len(files)} (автоподъём выключен)")
        return

    result = await apply_units_via_host(files, removed_units)
    if result.get("ok"):
        started = int(result.get("started") or 0)
        stopped = int(result.get("stopped") or 0)
        failed = [
            a for a in (result.get("applied") or []) if not a.get("ok")
        ]
        settings.srv_status = "applied" if not failed else "partial"
        settings.srv_message = (
            f"Агент поднял srv: активно {started} из {len(files)}"
            + (f", погашено {stopped}" if stopped else "")
            + (f", с ошибкой {len(failed)}" if failed else "")
        )
        _log(
            state,
            f"unit'ы на Улье: запущено {started}/{len(files)}"
            + (f", остановлено {stopped}" if stopped else "")
            + (f", ошибок {len(failed)}" if failed else ""),
        )
        if failed:
            state.last_error = "; ".join(
                f"{a.get('unit')}: {a.get('message')}" for a in failed[:3]
            )[:300]
    else:
        settings.srv_status = "pending_apply"
        msg = str(result.get("message") or "host-provision недоступен")
        settings.srv_message = (
            f"YAML записан ({len(files)} unit’ов), но автоподъём не сработал: {msg}. "
            f"На VPS: python scripts/apply_olcrtc_units_from_db.py"
        )
        state.last_error = msg[:300]
        _log(state, f"unit'ы не применены: {msg}")


_scale_lock = asyncio.Lock()
_last_scale_mono: float = 0.0


async def agent_heal_background(*, force: bool = False) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await heal_rooms(db, force=force)
    except Exception:
        logger.exception("olcrtc_room_agent heal failed")


async def _debounced_scale(reason: str) -> None:
    """Legacy pool-mode: heal/scale после deny. В session_mode — no-op (create в assign)."""
    global _last_scale_mono
    import time

    async with AsyncSessionLocal() as db:
        state = await load_agent_state(db)
        if state.session_mode:
            logger.info(
                "olcrtc on-demand scale skipped (session_mode): %s",
                reason[:80],
            )
            return

    async with _scale_lock:
        now = time.monotonic()
        if now - _last_scale_mono < SCALE_DEBOUNCE_SECONDS:
            logger.info(
                "olcrtc on-demand scale skipped (debounce %.0fs): %s",
                SCALE_DEBOUNCE_SECONDS,
                reason[:80],
            )
            return
        _last_scale_mono = now
    logger.info("olcrtc on-demand scale: %s", reason[:120])
    await agent_heal_background(force=True)


def request_scale_on_shortage(reason: str = "") -> None:
    """Из assign при deny — не блокировать ответ клиенту. Session-mode: no-op."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_debounced_scale(reason or "pool shortage"))


async def monitor_loop() -> None:
    logger.info("olcrtc room agent disabled (VK/WDTT only)")


def start_room_agent_background():
    loop = asyncio.get_event_loop()
    task = loop.create_task(monitor_loop())
    logger.info("olcrtc room agent monitor started")
    return task
