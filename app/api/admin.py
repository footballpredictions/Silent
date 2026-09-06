"""Admin API — dashboard, user management, VK credentials, system stats."""
import json
import os
import psutil
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, BackgroundTasks, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import tempfile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, case, update, or_
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models import User, Subscription, Device, VkHash, AppSetting, PromoCode, Payment, VkLinkSession, ReferralReward
from app.core.deps import get_admin_credentials, get_admin_session_jti
from app.config import settings
from app.schemas.vpn import ThemeResponse
from app.services.theme_settings import load_theme
from app.services.system_info import get_cpu_info
from app.services.proc_stats import read_host_load
from app.services import update_service
from app.services import admin_auth_service
import uuid as uuid_mod

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/sessions")
async def list_admin_sessions(
    _: bool = Depends(get_admin_credentials),
    current_jti: str | None = Depends(get_admin_session_jti),
    db: AsyncSession = Depends(get_db),
):
    """Trusted admin devices (one row per phone/PC), like user devices."""
    sessions = await admin_auth_service.list_admin_sessions(db, current_jti)
    return {"sessions": sessions, "devices": sessions}


@router.post("/logout")
async def admin_logout(
    _: bool = Depends(get_admin_credentials),
    current_jti: str | None = Depends(get_admin_session_jti),
    db: AsyncSession = Depends(get_db),
):
    """Выход: закрыть текущую сессию, trusted device оставить."""
    await admin_auth_service.revoke_session_by_jti(db, current_jti, revoke_device=False)
    return {"ok": True}


@router.delete("/sessions/{session_id}")
async def revoke_admin_session(
    session_id: str,
    _: bool = Depends(get_admin_credentials),
    current_jti: str | None = Depends(get_admin_session_jti),
    db: AsyncSession = Depends(get_db),
):
    try:
        sid = uuid_mod.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session id")
    from sqlalchemy import select
    from app.models.admin_auth import AdminSession
    res = await db.execute(select(AdminSession).where(AdminSession.id == sid))
    target = res.scalar_one_or_none()
    was_current = bool(target and current_jti and target.token_jti == current_jti)
    # Удаление из меню = забыть устройство целиком (как у пользователей)
    if target and target.device_id:
        ok = await admin_auth_service.revoke_trusted_device(db, target.device_id)
    else:
        ok = await admin_auth_service.revoke_admin_session(db, sid, revoke_device=True)
        if not ok:
            ok = await admin_auth_service.revoke_trusted_device(db, sid)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True, "was_current": was_current}


@router.delete("/devices/{device_id}")
async def revoke_admin_device(
    device_id: str,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    try:
        did = uuid_mod.UUID(device_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid device id")
    ok = await admin_auth_service.revoke_trusted_device(db, did)
    if not ok:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"ok": True}


def _utc_iso(dt: datetime | None) -> str | None:
    """Naive UTC → ISO with Z so admin UI can convert to Europe/Moscow correctly."""
    if dt is None:
        return None
    s = dt.isoformat()
    if dt.tzinfo is None and not s.endswith("Z") and "+" not in s[-6:]:
        return s + "Z"
    return s


async def _count_users_with_vpn_access(db: AsyncSession) -> tuple[int, int]:
    """Счётчики дашборда без N+1 и без ensure_trial как побочного эффекта."""
    from app.services.vpn_service import BOOTSTRAP_USER_EMAIL
    from app.services.subscription_service import users_with_vpn_access_ids

    not_bootstrap = User.email != BOOTSTRAP_USER_EMAIL
    total = int(
        (await db.execute(select(func.count()).select_from(User).where(not_bootstrap))).scalar_one() or 0
    )
    active_ids = await users_with_vpn_access_ids(db)
    return total, len(active_ids)


@router.get("/stats")
async def get_stats(
    light: bool = Query(False, description="CPU/RAM/счётчики без VK-списков — для полла дашборда"),
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard system stats."""
    # CPU/RAM/канал — хост VPS (/host/proc), не cgroup контейнера API
    load = read_host_load(cpu_interval=0.1)
    cpu = float(load.get("cpu_percent") or 0.0)
    cpu_info = get_cpu_info(cpu)
    if load.get("cpu_cores"):
        cpu_info["cpu_cores"] = int(load["cpu_cores"])
    disk = psutil.disk_usage("/")

    from app.services.vpn_service import BOOTSTRAP_USER_EMAIL
    from app.services.peak_online import record_online_peak
    from app.services.hive_service import vpn_online_shown_total

    total_users, active_subs = await _count_users_with_vpn_access(db)
    connected_devices = await vpn_online_shown_total(db)
    peak_online, peak_online_at = await record_online_peak(db, int(connected_devices or 0))

    mem_total = float(load.get("memory_total_gb") or 0.0)
    mem_used = float(load.get("memory_used_gb") or 0.0)
    mem_pct = float(load.get("memory_percent") or 0.0)
    system = {
        "cpu_percent": cpu,
        **cpu_info,
        "memory_total_gb": mem_total,
        "memory_used_gb": mem_used,
        "memory_percent": mem_pct,
        "disk_total_gb": round(disk.total / (1024**3), 1),
        "disk_used_gb": round(disk.used / (1024**3), 1),
        "disk_percent": disk.percent,
        "network_interface": load.get("network_interface"),
        "network_mbps_rx": float(load.get("network_mbps_rx") or 0.0),
        "network_mbps_tx": float(load.get("network_mbps_tx") or 0.0),
        "network_util_percent": float(load.get("network_util_percent") or 0.0),
        "network_link_capacity_mbps": float(
            load.get("network_link_capacity_mbps") or settings.HIVE_LINK_CAPACITY_MBPS
        ),
    }
    users_block = {
        "total": total_users,
        "active_subscriptions": active_subs,
        "connected_devices": connected_devices,
        "peak_online_devices": peak_online,
        "peak_online_at": peak_online_at,
    }
    if light:
        return {
            "system": system,
            "users": users_block,
            "vk_hash_summary": {},
            "vk_users": [],
            "vk_hashes": [],
        }

    from app.models.hive_cell import HiveCell
    from app.services.hive_slots import assign_online_to_cell_id, node_title_for_slot, slot_for_cell

    users_result = await db.execute(
        select(User)
        .where(User.email != BOOTSTRAP_USER_EMAIL)
        .order_by(User.created_at.desc())
    )
    all_users = users_result.scalars().all()
    user_ids = [u.id for u in all_users]

    devices_by_user: dict = {}
    if user_ids:
        devices_result = await db.execute(
            select(Device).where(Device.user_id.in_(user_ids))
        )
        for d in devices_result.scalars().all():
            devices_by_user.setdefault(d.user_id, []).append(d)

    hive_cells = list((await db.execute(select(HiveCell))).scalars().all())
    queen_cell = next((c for c in hive_cells if c.is_queen), None)
    known_cell_ids = {c.id for c in hive_cells}
    slot_to_id = {slot_for_cell(c): c.id for c in hive_cells if slot_for_cell(c)}
    id_to_slot = {c.id: slot_for_cell(c) or "server1" for c in hive_cells}

    # VK hashes — все пользователи + legacy (без user_id)
    from ai.vk_manager import MAX_HASHES

    hashes_result = await db.execute(
        select(VkHash)
        .where(VkHash.is_active == True)
        .order_by(VkHash.user_id.nullsfirst(), VkHash.slot_index)
    )
    all_hashes = hashes_result.scalars().all()
    legacy_hashes = [h for h in all_hashes if h.user_id is None]
    by_user_id: dict = {}
    for h in all_hashes:
        if h.user_id:
            by_user_id.setdefault(h.user_id, []).append(h)

    vk_users = []
    flat_hashes = []
    for u in all_users:
        user_hashes = by_user_id.get(u.id, [])
        user_devices = devices_by_user.get(u.id, [])
        last_seen = getattr(u, "last_seen_at", None)
        for d in user_devices:
            for ts in (d.last_connected, d.created_at):
                if ts and (last_seen is None or ts > last_seen):
                    last_seen = ts
        device_names = []
        online_device_names = []
        online_devices = []
        for d in user_devices:
            name = (d.device_name or "").strip()
            if name and name not in device_names:
                device_names.append(name)
            if not d.is_connected:
                continue
            nid = assign_online_to_cell_id(
                device_cell_id=d.cell_id,
                preferred=getattr(d, "preferred_server", None),
                queen_id=queen_cell.id if queen_cell else None,
                slot_to_id=slot_to_id,
                known_ids=known_cell_ids,
            )
            node = node_title_for_slot(id_to_slot.get(nid) or "server1")
            label = name or "устройство"
            online_devices.append({"name": label, "node": node})
            if name and name not in online_device_names:
                online_device_names.append(name)
        dev_online = len(online_devices)
        # Один хеш на слот в отображении (дубликаты — артефакт старого агента)
        best_by_slot: dict[int, VkHash] = {}
        for h in user_hashes:
            slot = h.slot_index
            if slot < 0 or slot >= MAX_HASHES:
                continue
            prev = best_by_slot.get(slot)
            if prev is None:
                best_by_slot[slot] = h
                continue
            h_score = (int(h.fail_count or 0), -(h.updated_at.timestamp() if h.updated_at else 0))
            p_score = (int(prev.fail_count or 0), -(prev.updated_at.timestamp() if prev.updated_at else 0))
            if h_score < p_score:
                best_by_slot[slot] = h
        unique_hashes = [best_by_slot[s] for s in sorted(best_by_slot)]
        slot_rows = [
            {
                "slot": h.slot_index,
                "hash": h.hash_value,
                "is_active": h.is_active,
                "fail_count": h.fail_count,
                "last_error_code": int(getattr(h, "last_error_code", 0) or 0),
                "last_checked": h.last_checked,
            }
            for h in unique_hashes
        ]
        for row in slot_rows:
            flat_hashes.append({
                **row,
                "user_email": u.email,
                "user_connected": dev_online > 0,
            })
        vk_users.append({
            "user_id": str(u.id),
            "user_email": u.email,
            "user_connected": dev_online > 0,
            "last_seen_at": _utc_iso(last_seen),
            "created_at": _utc_iso(getattr(u, "created_at", None)),
            "device_names": device_names,
            "online_device_names": online_device_names,
            "online_devices": online_devices,
            "slots_filled": len(unique_hashes),
            "slots_max": MAX_HASHES,
            "hashes": slot_rows,
        })

    legacy_rows = [
        {
            "slot": h.slot_index,
            "hash": h.hash_value,
            "user_email": "(legacy, без пользователя)",
            "user_connected": False,
            "is_active": h.is_active,
            "fail_count": h.fail_count,
            "last_error_code": int(getattr(h, "last_error_code", 0) or 0),
            "last_checked": h.last_checked,
        }
        for h in legacy_hashes
    ]
    flat_hashes.extend(legacy_rows)

    per_user_active = sum(len(v) for v in by_user_id.values())
    users_with_any = sum(1 for u in vk_users if u["slots_filled"] > 0)
    users_complete = sum(1 for u in vk_users if u["slots_filled"] >= MAX_HASHES)

    return {
        "system": system,
        "users": users_block,
        "vk_hash_summary": {
            "total_active": len(all_hashes),
            "per_user_active": per_user_active,
            "legacy_orphan": len(legacy_hashes),
            "users_total": len(all_users),
            "users_with_any": users_with_any,
            "users_complete": users_complete,
            "slots_max": MAX_HASHES,
        },
        "vk_users": vk_users,
        "vk_hashes": flat_hashes,
    }


@router.get("/users")
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=100000, description="Не задан — все пользователи"),
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    admin_email = settings.ADMIN_LOGIN.lower()
    q = (
        select(User)
        .where(User.email != "__bootstrap__@silent.local")
        .order_by(
            case(
                ((User.is_admin == True) | (func.lower(User.email) == admin_email), 0),
                else_=1,
            ),
            User.created_at.desc(),
        )
        .offset(skip)
    )
    if limit is not None:
        q = q.limit(limit)
    result = await db.execute(q)
    users = result.scalars().all()

    from app.services.test_mode_settings import is_registration_test_mode_enabled
    global_test = await is_registration_test_mode_enabled(db)

    from app.services.subscription_service import TEST_PLAN, is_user_admin

    user_ids = [u.id for u in users]
    dev_map: dict = {}
    online_map: dict = {}
    hash_map: dict = {}
    subs_by_user: dict = {}
    if user_ids:
        for uid, n in (
            await db.execute(
                select(Device.user_id, func.count(Device.id))
                .where(Device.user_id.in_(user_ids), Device.is_active == True)  # noqa: E712
                .group_by(Device.user_id)
            )
        ).all():
            dev_map[uid] = int(n)
        for uid, n in (
            await db.execute(
                select(Device.user_id, func.count(Device.id))
                .where(Device.user_id.in_(user_ids), Device.is_connected == True)  # noqa: E712
                .group_by(Device.user_id)
            )
        ).all():
            online_map[uid] = int(n)
        for uid, n in (
            await db.execute(
                select(VkHash.user_id, func.count(VkHash.id))
                .where(VkHash.user_id.in_(user_ids), VkHash.is_active == True)  # noqa: E712
                .group_by(VkHash.user_id)
            )
        ).all():
            hash_map[uid] = int(n)
        for sub in (
            await db.execute(
                select(Subscription)
                .where(
                    Subscription.user_id.in_(user_ids),
                    Subscription.status == "active",
                )
                .order_by(Subscription.expires_at.desc())
            )
        ).scalars().all():
            subs_by_user.setdefault(sub.user_id, []).append(sub)

    out = []
    for user in users:
        admin = is_user_admin(user)
        individual_test = bool(getattr(user, "test_mode_personal", False))
        excluded = bool(getattr(user, "test_mode_excluded", False))
        in_test = (not admin) and (individual_test or (global_test and not excluded))
        sub = None
        for candidate in subs_by_user.get(user.id, []):
            if not candidate.is_active:
                continue
            if candidate.plan_type == TEST_PLAN and not in_test:
                continue
            sub = candidate
            break
        hash_count = hash_map.get(user.id, 0)
        dev_count = dev_map.get(user.id, 0)

        out.append({
            "id": str(user.id),
            "display_id": user.display_id,
            "email": user.email,
            "is_verified": user.is_verified,
            "is_active": user.is_active,
            "is_admin": admin,
            "is_test_user": individual_test,
            "test_mode_excluded": excluded,
            "in_test_mode": in_test,
            "created_at": user.created_at,
            "bootstrap_hash": (user.bootstrap_hash[:12] + "...") if user.bootstrap_hash else None,
            "server_hashes": hash_count,
            "referral_code": user.referral_code,
            "referred_by_user_id": str(user.referred_by_user_id) if user.referred_by_user_id else None,
            "pending_promo_code": user.pending_promo_code,
            "acquisition": (
                "referral" if user.referred_by_user_id
                else ("promo" if user.pending_promo_code else "organic")
            ),
            "subscription": {
                "active": True if admin or in_test else (sub.is_active if sub else False),
                "plan": "unlimited" if admin else ("test" if in_test else (sub.plan_type if sub else None)),
                "expires_at": None if admin or in_test else (sub.expires_at if sub else None),
            },
            "devices_count": dev_count,
            "is_online": online_map.get(user.id, 0) > 0,
            "online_devices": online_map.get(user.id, 0),
        })
    return out


class RegistrationTestModeRequest(BaseModel):
    enabled: bool


class RegistrationDisabledRequest(BaseModel):
    disabled: bool


@router.get("/subscriptions/registration-test-mode")
async def get_registration_test_mode(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.test_mode_settings import is_registration_test_mode_enabled

    return {"enabled": await is_registration_test_mode_enabled(db)}


@router.post("/subscriptions/registration-test-mode")
async def set_registration_test_mode_endpoint(
    req: RegistrationTestModeRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.test_mode_settings import set_registration_test_mode

    enabled, affected = await set_registration_test_mode(db, req.enabled)
    return {"enabled": enabled, "users_affected": affected}


@router.get("/subscriptions/users")
async def list_subscription_users_endpoint(
    q: str = Query("", description="email или display_id"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=500),
    filter: str = Query("all", description="all|active|inactive|unpaid"),
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Список для меню Подписки: пагинация; при q — все совпадения по базе."""
    from app.services.admin_subscription_ops import list_subscription_users

    mode = (filter or "all").strip().lower()
    if mode not in ("all", "active", "inactive", "unpaid"):
        mode = "all"
    return await list_subscription_users(
        db, q=q, page=page, page_size=page_size, filter_mode=mode
    )


@router.get("/subscriptions/orphan-payments")
async def list_orphan_payments_endpoint(
    limit: int = Query(30, ge=1, le=100),
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Оплаты completed без выданной подписки."""
    from app.services.admin_subscription_ops import list_orphan_payments

    return {"items": await list_orphan_payments(db, limit=limit)}


@router.get("/subscriptions/by-code/{code}")
async def lookup_subscription_by_code(
    code: str,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.admin_subscription_ops import lookup_payment_by_support_code

    data = await lookup_payment_by_support_code(db, code)
    if not data:
        raise HTTPException(status_code=404, detail="Код не найден")
    return data


@router.post("/subscriptions/by-code/{code}/activate")
async def activate_subscription_by_code(
    code: str,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Ручная выдача подписки по коду из письма после оплаты YuMoney."""
    from app.services.admin_subscription_ops import activate_subscription_by_support_code

    return await activate_subscription_by_support_code(db, code)


@router.get("/users/{user_id}/subscription-history")
async def user_subscription_history_endpoint(
    user_id: str,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.admin_subscription_ops import user_subscription_history

    return await user_subscription_history(db, user_id)


@router.get("/settings/registration")
async def get_registration_settings(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Доп. настройки: блокировка регистрации при инцидентах."""
    from app.services.registration_settings import (
        REGISTRATION_DISABLED_MESSAGE,
        is_registration_disabled,
    )

    disabled = await is_registration_disabled(db)
    return {
        "registration_disabled": disabled,
        "message": REGISTRATION_DISABLED_MESSAGE,
    }


@router.post("/settings/registration")
async def set_registration_settings(
    req: RegistrationDisabledRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.registration_settings import (
        REGISTRATION_DISABLED_MESSAGE,
        set_registration_disabled,
    )

    disabled = await set_registration_disabled(db, req.disabled)
    return {
        "registration_disabled": disabled,
        "message": REGISTRATION_DISABLED_MESSAGE,
    }


class ThreatFilterRequest(BaseModel):
    enabled: bool


@router.get("/settings/threat-filter")
async def get_threat_filter_settings(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Доп. настройки: DNS-фильтр угроз (HaGeZi TIF на Улье)."""
    from app.services.threat_filter_settings import get_threat_filter_status

    return await get_threat_filter_status(db)


@router.post("/settings/threat-filter")
async def set_threat_filter_settings(
    req: ThreatFilterRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.threat_filter_settings import (
        get_threat_filter_status,
        set_threat_filter_enabled,
    )

    await set_threat_filter_enabled(db, req.enabled)
    return await get_threat_filter_status(db)


class Olcrtc2SettingsRequest(BaseModel):
    enabled: bool | None = None
    agent_enabled: bool | None = None
    provider: str | None = None
    room: str | None = None
    crypto_key: str | None = None
    socks_port: int | None = None
    cell_ip: str | None = None
    cell_ip_wbstream: str | None = None
    cell_provision_url: str | None = None
    cells: dict[str, str] | None = None
    providers_enabled: list[str] | None = None
    transport: str | None = None
    warm_pool_per_dt: int | None = None
    warm_pool_by_provider: dict[str, int] | None = None
    target_online: int | None = None
    generate_key: bool | None = None


@router.get("/olcrtc2")
async def get_olcrtc2_admin(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """olcrtc 2.0 — выключен (WDTT only)."""
    from app.services.olcrtc2_assign import pool_stats
    from app.services.olcrtc2_settings import load_olcrtc2_settings

    settings = await load_olcrtc2_settings(db)
    stats = await pool_stats(db)
    status = {
        "product_on": False,
        "agent_on": False,
        "session_mode": True,
        "pool": stats,
        "disabled_reason": "VK/WDTT only",
    }
    return {**settings, "agent": status}


@router.post("/olcrtc2")
async def set_olcrtc2_admin(
    req: Olcrtc2SettingsRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    import secrets

    from app.services.olcrtc2_assign import pool_stats
    from app.services.olcrtc2_settings import load_olcrtc2_settings, save_olcrtc2_settings

    patch = req.model_dump(exclude_none=True)
    if patch.pop("generate_key", False):
        patch["crypto_key"] = secrets.token_hex(32)
    try:
        data = await save_olcrtc2_settings(db, patch)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    stats = await pool_stats(db)
    status = {
        "product_on": False,
        "agent_on": False,
        "session_mode": True,
        "pool": stats,
        "disabled_reason": "VK/WDTT only",
    }
    return {**data, "agent": status}


@router.get("/olcrtc2/stats")
async def get_olcrtc2_stats(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.olcrtc2_assign import pool_stats

    stats = await pool_stats(db)
    return {
        "product_on": False,
        "agent_on": False,
        "session_mode": True,
        "pool": stats,
        "disabled_reason": "VK/WDTT only",
    }


@router.post("/olcrtc2/apply-cell")
async def apply_olcrtc2_cell_admin(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Diag: одна статическая room → env на соту. Продукт использует per-unit apply."""
    from app.services.olcrtc2_cell import apply_olcrtc2_to_cell

    return await apply_olcrtc2_to_cell(db)


class VpsCleanupRequest(BaseModel):
    enabled: bool
    interval_days: int | None = None
    journal_max_mb: int | None = None
    run_now: bool | None = None


@router.get("/settings/vps-cleanup")
async def get_vps_cleanup_settings(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Доп. настройки: автоочистка Улья (journal/Docker/tmp)."""
    from app.services.vps_cleanup_settings import get_vps_cleanup_status

    return await get_vps_cleanup_status(db)


@router.post("/settings/vps-cleanup")
async def set_vps_cleanup_settings(
    req: VpsCleanupRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.vps_cleanup_settings import set_vps_cleanup

    return await set_vps_cleanup(
        db,
        enabled=req.enabled,
        interval_days=req.interval_days,
        journal_max_mb=req.journal_max_mb,
        run_now=req.run_now,
    )


class GrantSubscriptionRequest(BaseModel):
    plan_type: str


@router.post("/users/{user_id}/grant-subscription")
async def grant_user_subscription(
    user_id: str,
    req: GrantSubscriptionRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Ручная выдача подписки (three_days / monthly / two_months / quarterly / half_year / yearly / unlimited)."""
    import uuid
    from app.services.subscription_service import grant_manual_subscription

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    sub = await grant_manual_subscription(db, user, req.plan_type.strip().lower())
    return {
        "status": "granted",
        "plan_type": sub.plan_type,
        "expires_at": sub.expires_at,
    }


@router.post("/users/{user_id}/revoke-subscription")
async def revoke_user_subscription(
    user_id: str,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Отозвать активную подписку пользователя."""
    import uuid
    from app.services.subscription_service import revoke_subscription, is_user_admin

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if is_user_admin(user):
        raise HTTPException(status_code=400, detail="Нельзя отозвать подписку у администратора")

    cancelled = await revoke_subscription(db, user)
    return {"status": "revoked", "cancelled": cancelled}


class UserTestModeRequest(BaseModel):
    enabled: bool


@router.post("/users/{user_id}/test-mode")
async def set_user_test_mode(
    user_id: str,
    req: UserTestModeRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Персональный тестовый режим (безлимит) для одного пользователя."""
    import uuid
    from app.services.subscription_service import set_user_personal_test_mode, is_user_admin

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if is_user_admin(user):
        raise HTTPException(status_code=400, detail="Администратору тестовый режим не нужен")

    data = await set_user_personal_test_mode(db, user, req.enabled)
    return {
        "status": "enabled" if req.enabled else "disabled",
        **data,
    }


@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: str,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    import uuid
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.is_active = not user.is_active
    await db.commit()
    return {"status": "banned" if not user.is_active else "unbanned", "is_active": user.is_active}


@router.post("/users/{user_id}/verify")
async def verify_user(
    user_id: str,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Ручная верификация email без письма."""
    import uuid
    from app.services.vpn_service import BOOTSTRAP_USER_EMAIL

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.email == BOOTSTRAP_USER_EMAIL:
        raise HTTPException(status_code=400, detail="Нельзя верифицировать системного пользователя")
    if user.is_verified:
        return {"status": "already_verified", "is_verified": True}

    user.is_verified = True
    user.verification_token = None
    await db.commit()
    from app.services.subscription_service import apply_post_verification_benefits
    await apply_post_verification_benefits(db, user)
    return {"status": "verified", "is_verified": True}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Удалить пользователя и все связанные данные."""
    import uuid
    from app.services.vpn_service import BOOTSTRAP_USER_EMAIL

    uid = uuid.UUID(user_id)
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.email == BOOTSTRAP_USER_EMAIL:
        raise HTTPException(status_code=400, detail="Нельзя удалить системного пользователя")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Нельзя удалить администратора")

    await db.execute(delete(VkHash).where(VkHash.user_id == uid))
    await db.execute(delete(VkLinkSession).where(VkLinkSession.user_id == uid))
    await db.execute(delete(Device).where(Device.user_id == uid))
    await db.execute(delete(Payment).where(Payment.user_id == uid))
    await db.execute(delete(Subscription).where(Subscription.user_id == uid))
    await db.execute(
        delete(ReferralReward).where(
            (ReferralReward.inviter_id == uid) | (ReferralReward.invitee_id == uid)
        )
    )
    await db.execute(
        update(User).where(User.referred_by_user_id == uid).values(referred_by_user_id=None)
    )
    await db.delete(user)
    await db.commit()
    return {"status": "deleted", "id": user_id}


# ─── VK: bot auth → AI agent → manual hashes ─────────────────────────────────

class VkHashManualRequest(BaseModel):
    hash: str
    slot: int
    user_id: Optional[str] = None


class VkOAuthFinishRequest(BaseModel):
    state: str
    access_token: str
    expires_in: int | None = None


class VkPasswordAuthRequest(BaseModel):
    login: str
    password: str


class VkOAuthPasteRequest(BaseModel):
    state: str
    paste: str


@router.get("/vk/status")
async def vk_panel_status(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.vk_agent_auth import get_auth_status
    from ai.vk_manager import MAX_HASHES
    status = await get_auth_status(db)
    status["hashes_active"] = (await db.execute(
        select(func.count(VkHash.id)).where(VkHash.is_active == True)
    )).scalar_one()
    status["hashes_per_user"] = (await db.execute(
        select(func.count(VkHash.id)).where(VkHash.is_active == True, VkHash.user_id.isnot(None))
    )).scalar_one()
    from app.services.vpn_service import BOOTSTRAP_USER_EMAIL
    from app.services.user_hash_service import list_users_for_monitor

    monitor_ids = await list_users_for_monitor(db)
    status["users_for_agent"] = len(monitor_ids)
    users_needing = 0
    for uid in monitor_ids:
        from app.services.user_hash_service import count_active_server_hashes
        cnt = await count_active_server_hashes(db, uid)
        if cnt < MAX_HASHES:
            users_needing += 1
    status["users_needing_hashes"] = users_needing
    status["max_hashes"] = MAX_HASHES
    status["hashes_dead"] = (await db.execute(
        select(func.count(VkHash.id)).where(
            VkHash.user_id.isnot(None),
            or_(VkHash.is_active == False, VkHash.last_error_code == 1),  # noqa: E712
        )
    )).scalar_one() or 0
    status["hashes_probe_pending"] = (await db.execute(
        select(func.count(VkHash.id)).where(
            VkHash.is_active == True,  # noqa: E712
            VkHash.last_error_code == 2,
        )
    )).scalar_one() or 0
    from app.services.vk_agent_auth import _setting
    from ai.vk_hash_liveness import (
        SETTING_LAST,
        SETTING_LAST_MSG,
        PROBE_BUDGET,
    )
    status["probe_last_run"] = await _setting(db, SETTING_LAST)
    status["probe_last_message"] = await _setting(db, SETTING_LAST_MSG)
    status["probe_budget"] = PROBE_BUDGET
    return status


@router.post("/vk/bot-auth/start")
async def vk_bot_auth_start(
    request: Request,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.config import settings
    from app.models import VkLinkSession
    import secrets
    from datetime import timedelta
    from app.services.vk_calls_auth import build_calls_admin_auth_urls, format_calls_uuid

    state = secrets.token_urlsafe(32)
    db.add(VkLinkSession(
        state=state,
        user_id=None,
        code_verifier="kate",
        expires_at=datetime.utcnow() + timedelta(minutes=15),
        purpose="agent",
    ))
    await db.commit()
    urls = build_calls_admin_auth_urls(state)
    bot_url = settings.VK_BOT_WRITE_URL or f"https://vk.com/write-{settings.VK_GROUP_ID}"
    return {
        **urls,
        "state": state,
        "bot_url": bot_url,
        "auth_mode": "vk_calls_silent",
        "paste_hint": (
            "1) «Войти через VK Звонки» → popup → авторизация. "
            "2) После «Продолжить» скопируйте URL из адресной строки (Ctrl+L → Ctrl+C). "
            "3) Вставьте URL с payload=… или silent_token=… → «Сохранить». "
            "Kate OAuth в браузере VK больше не поддерживает."
        ),
    }


@router.post("/vk/bot-auth/paste")
async def vk_bot_auth_paste(
    req: VkOAuthPasteRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить токен: silent_token (VK Звонки) или code из Kate OAuth."""
    from app.services.vk_agent_auth import (
        parse_vk_oauth_paste,
        complete_agent_auth,
        save_agent_token_direct,
        paste_to_server_token,
    )
    from app.services.vk_calls_auth import (
        parse_silent_token_from_paste,
        exchange_silent_token,
        is_calls_login_start_url,
    )

    paste = (req.paste or "").strip()
    if is_calls_login_start_url(paste):
        raise HTTPException(
            status_code=400,
            detail=(
                "Это ссылка на начало входа (id.vk.com/auth), а не результат. "
                "Нажмите «Войти через VK Звonки», войдите, нажмите «Продолжить», "
                "скопируйте URL из адресной строки (Ctrl+L → Ctrl+C) и вставьте сюда. "
                "Нужен URL вида oauth.vk.com/blank.html?payload=… или …#silent_token=…"
            ),
        )

    silent, silent_uuid = parse_silent_token_from_paste(paste)
    if silent:
        access, uid, err = await exchange_silent_token(silent, silent_uuid or "")
        if not access:
            raise HTTPException(status_code=400, detail=err or "Не удалось обменять silent_token")
        ok, message, uid = await save_agent_token_direct(db, access, None)
        if not ok:
            raise HTTPException(status_code=400, detail=message)
        return {"success": True, "message": message, "vk_user_id": uid}

    token, expires_in, err = await paste_to_server_token(req.paste, db)
    if err:
        raise HTTPException(status_code=400, detail=err)
    if not token:
        raise HTTPException(status_code=400, detail="Не удалось получить token")

    _, _, state_from_url, _ = parse_vk_oauth_paste(req.paste)
    state = (state_from_url or req.state or "").strip()
    if state:
        ok, message, uid = await complete_agent_auth(db, state, token, expires_in)
        if not ok and ("Сессия" in message or "истекла" in message.lower()):
            ok, message, uid = await save_agent_token_direct(db, token, expires_in)
    else:
        ok, message, uid = await save_agent_token_direct(db, token, expires_in)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message, "vk_user_id": uid}


@router.post("/vk/oauth/finish")
async def vk_oauth_finish(
    req: VkOAuthFinishRequest,
    db: AsyncSession = Depends(get_db),
):
    """Public: static page posts Android access_token after OAuth."""
    from app.services.vk_agent_auth import complete_agent_auth
    ok, message, uid = await complete_agent_auth(
        db, req.state, req.access_token.strip(), req.expires_in,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message, "vk_user_id": uid}


@router.get("/vk/oauth/callback")
async def vk_oauth_callback_code(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Fallback: authorization_code from Android client."""
    if error:
        return HTMLResponse(
            f"<body style='background:#000;color:#fff;font-family:sans-serif;padding:40px'>"
            f"<h2>Ошибка VK</h2><p>{error_description or error}</p></body>",
            status_code=400,
        )
    if not code or not state:
        return HTMLResponse("<p>Нет code/state</p>", status_code=400)

    from app.services.vk_agent_auth import (
        agent_oauth_redirect_uri,
        exchange_android_code,
        complete_agent_auth,
    )
    base = str(request.base_url).rstrip("/")
    if base.startswith("http://"):
        base = base.replace("http://", "https://", 1)
    redirect_uri = agent_oauth_redirect_uri(base)
    token_data, err = await exchange_android_code(code, redirect_uri)
    if not token_data:
        return HTMLResponse("<p>Не удалось обменять code на token</p>", status_code=400)

    ok, message, uid = await complete_agent_auth(
        db,
        state,
        token_data["access_token"],
        token_data.get("expires_in"),
    )
    if not ok:
        return HTMLResponse(
            f"<body style='background:#000;color:#f88;font-family:sans-serif;padding:40px'>"
            f"<h2>Ошибка</h2><p>{message}</p></body>",
            status_code=400,
        )
    return HTMLResponse(
        f"<body style='background:#000;color:#4ade80;font-family:sans-serif;padding:40px;text-align:center'>"
        f"<h2>VK подключён</h2><p>ID {uid}. Закройте окно.</p>"
        f"<script>setTimeout(function(){{window.close()}},2000)</script></body>"
    )


@router.post("/vk/bot-auth/password")
async def vk_bot_auth_password(
    req: VkPasswordAuthRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Android client password grant — works for calls.create from server."""
    from app.services.vk_agent_auth import (
        password_login,
        save_stored_token,
        save_agent_credentials,
        validate_token,
        test_calls_permission,
        set_calls_verified,
    )
    login = req.login.strip()
    await save_agent_credentials(db, login, req.password)
    token, msg = await password_login(login, req.password)
    if not token:
        if any(x in (msg or "").lower() for x in ("заблокировал", "flood", "pogingen", "paar uur", "too many")):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{msg} Логин сохранён на сервере — через несколько часов нажмите "
                    "«Войти по логину и паролю» снова или «Подключить агента»."
                ),
            )
        raise HTTPException(status_code=400, detail=msg)
    await save_stored_token(db, token)
    ok, detail, uid = await validate_token(token)
    if not ok:
        raise HTTPException(status_code=400, detail=detail)
    calls_ok, calls_msg = await test_calls_permission(token)
    if not calls_ok:
        await set_calls_verified(db, False)
        raise HTTPException(status_code=400, detail=f"Звонки недоступны: {calls_msg}")
    await set_calls_verified(db, True)
    return {"success": True, "vk_user_id": uid, "message": "VK авторизован (Android API)"}


@router.get("/vk/bot-auth/status")
async def vk_bot_auth_poll(
    state: str,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.models import VkLinkSession
    result = await db.execute(
        select(VkLinkSession).where(VkLinkSession.state == state, VkLinkSession.purpose == "agent")
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return {"completed": session.completed, "vk_user_id": session.vk_user_id}


@router.post("/vk/agent/connect")
async def vk_agent_connect(
    background_tasks: BackgroundTasks,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.vk_agent_auth import set_agent_enabled, set_calls_verified, clear_flood_cooldown
    from ai.vk_manager import VkManager, agent_heal_background

    manager = VkManager(db)
    ok, err = await manager.ensure_authenticated(verify_calls=True)
    await manager.close()
    if not ok:
        raise HTTPException(status_code=400, detail=err or "VK не может создавать звонки")
    await set_calls_verified(db, True)
    await clear_flood_cooldown(db)
    await set_agent_enabled(db, True)
    background_tasks.add_task(agent_heal_background)

    return {
        "success": True,
        "message": "Агент подключён. Хеши для пользователей создаются в фоне (1–3 мин).",
        "agent_connected": True,
        "agent_enabled": True,
    }


@router.post("/vk/agent/sync-env")
async def vk_agent_sync_env(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Перечитать VK_AGENT_ACCESS_TOKEN из .env и проверить calls.create."""
    from app.services.vk_agent_auth import resolve_agent_token, get_env_agent_token
    if not get_env_agent_token():
        raise HTTPException(
            status_code=400,
            detail="VK_AGENT_ACCESS_TOKEN не задан в .env на сервере",
        )
    token, msg = await resolve_agent_token(db, verify_calls=True)
    if not token:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@router.post("/vk/agent/clear-flood")
async def vk_agent_clear_flood(
    background_tasks: BackgroundTasks,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Снять серверную паузу flood (от старого аккаунта) и запустить создание хешей."""
    from app.services.vk_agent_auth import is_agent_enabled, clear_flood_cooldown, set_agent_run_log
    from ai.vk_manager import agent_heal_background, VkManager

    if not await is_agent_enabled(db):
        raise HTTPException(status_code=400, detail="Сначала подключите агента")

    manager = VkManager(db)
    ok, err = await manager.ensure_authenticated(verify_calls=False)
    await manager.close()
    if not ok:
        raise HTTPException(status_code=400, detail=err or "Токен VK не работает")

    await clear_flood_cooldown(db)
    await set_agent_run_log(db, "Пауза flood снята вручную, запуск создания хешей (без liveness)…", ok=True)
    background_tasks.add_task(agent_heal_background, fill_only=True)
    return {
        "success": True,
        "message": "Пауза снята. Создание хешей запущено в фоне, без пачки preview.",
    }


@router.post("/vk/agent/dedupe-hashes")
async def vk_agent_dedupe_hashes(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.user_hash_service import dedupe_all_user_hash_slots

    removed = await dedupe_all_user_hash_slots(db)
    return {
        "success": True,
        "message": f"Удалено {removed} лишних строк хешей (дубликаты слотов)",
        "removed": removed,
    }


@router.post("/vk/agent/restore-hashes")
async def vk_agent_restore_hashes(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Вернуть деактивированные хеши (is_active=false), не удаляя их."""
    count = (await db.execute(
        select(func.count(VkHash.id)).where(
            VkHash.is_active == False,
            VkHash.user_id.isnot(None),
            VkHash.hash_value != "",
        )
    )).scalar_one() or 0
    if count == 0:
        return {"success": True, "message": "Нет деактивированных хешей для восстановления", "restored": 0}

    await db.execute(
        update(VkHash)
        .where(VkHash.is_active == False, VkHash.user_id.isnot(None))
        .values(is_active=True, fail_count=0, last_error_code=0)
    )
    await db.commit()
    return {
        "success": True,
        "message": f"Восстановлено {count} хешей (снова активны). Новые слоты — через «Создать хеши».",
        "restored": count,
    }


@router.post("/vk/agent/sync-hashes")
async def vk_agent_sync_hashes(
    background_tasks: BackgroundTasks,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Принудительно создать/проверить хеши для всех пользователей (фон)."""
    from app.services.vk_agent_auth import is_agent_enabled
    from app.services.user_hash_service import dedupe_all_user_hash_slots
    from ai.vk_manager import agent_heal_background

    if not await is_agent_enabled(db):
        raise HTTPException(status_code=400, detail="Сначала подключите агента")
    removed = await dedupe_all_user_hash_slots(db)
    background_tasks.add_task(agent_heal_background)
    extra = f" Удалено дубликатов: {removed}." if removed else ""
    return {
        "success": True,
        "message": f"Запущено: очистка слотов и создание недостающих хешей (1–5 мин).{extra}",
    }


@router.post("/vk/agent/disconnect")
async def vk_agent_disconnect(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.vk_agent_auth import set_agent_enabled
    await set_agent_enabled(db, False)
    return {"success": True, "message": "AI-агент отключён", "agent_connected": False}


@router.get("/vk/hashes")
async def get_vk_hashes(
    user_id: Optional[str] = None,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    q = select(VkHash).where(VkHash.is_active == True).order_by(VkHash.slot_index)
    if user_id:
        import uuid
        q = q.where(VkHash.user_id == uuid.UUID(user_id))
    else:
        q = q.where(VkHash.user_id.is_(None))
    result = await db.execute(q)
    hashes = result.scalars().all()
    if user_id:
        from ai.vk_manager import MAX_HASHES
        best: dict[int, VkHash] = {}
        for h in hashes:
            slot = h.slot_index
            if slot < 0 or slot >= MAX_HASHES:
                continue
            prev = best.get(slot)
            if prev is None:
                best[slot] = h
                continue
            h_score = (int(h.fail_count or 0), -(h.updated_at.timestamp() if h.updated_at else 0))
            p_score = (int(prev.fail_count or 0), -(prev.updated_at.timestamp() if prev.updated_at else 0))
            if h_score < p_score:
                best[slot] = h
        hashes = [best[s] for s in sorted(best)]

    return [
        {
            "id": str(h.id),
            "slot": h.slot_index,
            "hash": h.hash_value,
            "user_id": str(h.user_id) if h.user_id else None,
            "call_link": h.call_link,
            "is_active": h.is_active,
            "fail_count": h.fail_count,
            "last_error_code": int(getattr(h, "last_error_code", 0) or 0),
            "last_checked": h.last_checked,
            "created_at": h.created_at,
        }
        for h in hashes
    ]


@router.post("/vk/hashes/manual")
async def add_vk_hash_manual(
    req: VkHashManualRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Add hash manually (from VK call link)."""
    from ai.vk_manager import VkManager, MAX_HASHES
    if req.slot < 0 or req.slot >= MAX_HASHES:
        raise HTTPException(status_code=400, detail=f"Слот 0–{MAX_HASHES - 1}")

    manager = VkManager(db)
    hash_val = manager._extract_hash(req.hash.strip())
    if not hash_val:
        raise HTTPException(status_code=400, detail="Неверный формат хеша или ссылки vk.com/call/join/…")

    link = req.hash.strip() if req.hash.startswith("http") else f"https://vk.com/call/join/{hash_val}"
    uid = None
    if req.user_id:
        import uuid
        uid = uuid.UUID(req.user_id)
    await manager.upsert_hash_slot(req.slot, hash_val, link, user_id=uid)

    try:
        from app.services.vk_config_publisher import publish_all_configs
        await publish_all_configs(db)
    except Exception:
        pass

    return {"success": True, "slot": req.slot, "hash": hash_val, "message": f"Хеш добавлен в слот {req.slot}"}


@router.post("/maintenance/cleanup-bootstrap")
async def cleanup_bootstrap_user(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Удалить синтетического пользователя bootstrap, его устройства и legacy-хеши без user_id."""
    from app.services.vpn_service import BOOTSTRAP_USER_EMAIL
    from app.models import Device

    await db.execute(delete(VkHash).where(VkHash.user_id.is_(None)))

    result = await db.execute(select(User).where(User.email == BOOTSTRAP_USER_EMAIL))
    boot = result.scalar_one_or_none()
    if boot:
        await db.execute(delete(Device).where(Device.user_id == boot.id))
        await db.delete(boot)
    await db.commit()
    return {"ok": True, "message": "Bootstrap-пользователь и устаревшие хеши удалены"}


@router.delete("/vk/hashes/{slot}")
async def delete_vk_hash_slot(
    slot: int,
    user_id: Optional[str] = None,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from ai.vk_manager import MAX_HASHES
    if slot < 0 or slot >= MAX_HASHES:
        raise HTTPException(status_code=400, detail=f"Слот 0–{MAX_HASHES - 1}")
    q = select(VkHash).where(VkHash.slot_index == slot, VkHash.is_active == True)
    if user_id:
        import uuid
        q = q.where(VkHash.user_id == uuid.UUID(user_id))
    else:
        q = q.where(VkHash.user_id.is_(None))
    result = await db.execute(q)
    h = result.scalar_one_or_none()
    if h:
        await db.delete(h)
        await db.commit()
    return {"success": True, "message": f"Слот {slot} удалён"}


@router.post("/vk/publish-configs")
async def publish_vk_configs(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Push encrypted VPN configs to all linked VK users."""
    from app.services.vk_config_publisher import publish_all_configs
    sent = await publish_all_configs(db)
    return {"sent": sent, "message": f"Отправлено {sent} конфигов в VK"}


# Theme management
@router.get("/theme")
async def get_theme_admin(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    theme = await load_theme(db, persist_migration=True)
    return theme.model_dump()


@router.post("/theme")
async def set_theme(
    theme: ThemeResponse,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AppSetting).where(AppSetting.key == "theme"))
    setting = result.scalar_one_or_none()
    data = json.dumps(theme.model_dump())
    if setting:
        setting.value = data
        setting.updated_at = datetime.utcnow()
    else:
        db.add(AppSetting(key="theme", value=data))
    await db.commit()
    return {"message": "Theme updated"}


@router.post("/theme/upload-home-bg")
async def upload_home_bg(
    file: UploadFile = File(...),
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Upload main-screen background image → /static/theme/home_bg.*"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        raise HTTPException(status_code=400, detail="Allowed: .jpg .jpeg .png .webp .gif")
    static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static", "theme")
    os.makedirs(static_dir, exist_ok=True)
    # One canonical name so URL stays stable after replace
    out_ext = ".jpg" if ext == ".jpeg" else ext
    out_name = f"home_bg{out_ext}"
    out_path = os.path.join(static_dir, out_name)
    # Remove previous home_bg.* so only one file remains
    for name in os.listdir(static_dir):
        if name.startswith("home_bg."):
            try:
                os.remove(os.path.join(static_dir, name))
            except OSError:
                pass
    content = await file.read()
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Max size 8 MB")
    with open(out_path, "wb") as f:
        f.write(content)
    url = f"/static/theme/{out_name}"
    # Persist URL into theme so clients pick it up via ConfigSync
    theme = await load_theme(db)
    theme.home_bg_image_url = url
    result = await db.execute(select(AppSetting).where(AppSetting.key == "theme"))
    setting = result.scalar_one_or_none()
    data = json.dumps(theme.model_dump())
    if setting:
        setting.value = data
        setting.updated_at = datetime.utcnow()
    else:
        db.add(AppSetting(key="theme", value=data))
    await db.commit()
    return {"url": url, "message": "Home background uploaded"}


@router.post("/theme/upload-logo")
async def upload_logo(
    file: UploadFile = File(...),
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Upload client logo → /static/logo.* and update theme.logo_url."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".svg"):
        raise HTTPException(status_code=400, detail="Allowed: .jpg .png .webp .svg")
    static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static")
    os.makedirs(static_dir, exist_ok=True)
    out_ext = ".jpg" if ext == ".jpeg" else ext
    out_name = f"logo{out_ext}"
    out_path = os.path.join(static_dir, out_name)
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Max size 2 MB")
    with open(out_path, "wb") as f:
        f.write(content)
    url = f"/static/{out_name}"
    theme = await load_theme(db)
    theme.logo_url = url
    result = await db.execute(select(AppSetting).where(AppSetting.key == "theme"))
    setting = result.scalar_one_or_none()
    data = json.dumps(theme.model_dump())
    if setting:
        setting.value = data
        setting.updated_at = datetime.utcnow()
    else:
        db.add(AppSetting(key="theme", value=data))
    await db.commit()
    return {"url": url, "message": "Logo uploaded"}


# Promo codes
class PromoCreateRequest(BaseModel):
    code: str
    discount_percent: int = 0
    extra_days: int = 0
    max_uses: int = 1
    expires_at: Optional[datetime] = None


class BuildConfigRequest(BaseModel):
    pc_enabled: Optional[bool] = None
    android_enabled: Optional[bool] = None


@router.post("/promo")
async def create_promo(
    req: PromoCreateRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    promo = PromoCode(
        code=req.code.upper(),
        discount_percent=req.discount_percent,
        extra_days=req.extra_days,
        max_uses=req.max_uses,
        expires_at=req.expires_at,
    )
    db.add(promo)
    await db.commit()
    return {"message": f"Промокод {promo.code} создан"}


@router.get("/promo")
async def list_promos(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PromoCode).order_by(PromoCode.created_at.desc()))
    promos = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "code": p.code,
            "discount_percent": p.discount_percent,
            "extra_days": p.extra_days,
            "max_uses": p.max_uses,
            "use_count": p.use_count,
            "is_active": p.is_active,
            "expires_at": p.expires_at,
        }
        for p in promos
    ]


@router.get("/bonuses/stats")
async def bonuses_stats(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Summary + recent referral/promo acquisition for admin Bonuses page."""
    from app.config import settings as app_settings

    total_rewards = (await db.execute(select(func.count()).select_from(ReferralReward))).scalar_one()
    pending = (await db.execute(
        select(func.count()).select_from(ReferralReward).where(ReferralReward.status == "pending")
    )).scalar_one()
    rewarded = (await db.execute(
        select(func.count()).select_from(ReferralReward).where(ReferralReward.status == "rewarded")
    )).scalar_one()
    referred_users = (await db.execute(
        select(func.count()).select_from(User).where(User.referred_by_user_id.is_not(None))
    )).scalar_one()
    promo_pending_users = (await db.execute(
        select(func.count()).select_from(User).where(User.pending_promo_code.is_not(None))
    )).scalar_one()

    # Top inviters by rewarded count
    top_q = await db.execute(
        select(
            ReferralReward.inviter_id,
            func.count().label("cnt"),
        )
        .where(ReferralReward.status == "rewarded")
        .group_by(ReferralReward.inviter_id)
        .order_by(func.count().desc())
        .limit(20)
    )
    top_rows = top_q.all()
    top_inviters = []
    for inviter_id, cnt in top_rows:
        u = (await db.execute(select(User).where(User.id == inviter_id))).scalar_one_or_none()
        if not u:
            continue
        pending_cnt = (await db.execute(
            select(func.count()).select_from(ReferralReward).where(
                ReferralReward.inviter_id == inviter_id,
                ReferralReward.status == "pending",
            )
        )).scalar_one()
        invited_cnt = (await db.execute(
            select(func.count()).select_from(ReferralReward).where(
                ReferralReward.inviter_id == inviter_id,
            )
        )).scalar_one()
        top_inviters.append({
            "user_id": str(u.id),
            "email": u.email,
            "display_id": u.display_id,
            "referral_code": u.referral_code,
            "invited_count": int(invited_cnt or 0),
            "rewarded_count": int(cnt or 0),
            "pending_count": int(pending_cnt or 0),
        })

    # Recent referral pairs
    recent_q = await db.execute(
        select(ReferralReward).order_by(ReferralReward.created_at.desc()).limit(50)
    )
    recent = []
    for r in recent_q.scalars().all():
        inv = (await db.execute(select(User).where(User.id == r.inviter_id))).scalar_one_or_none()
        tee = (await db.execute(select(User).where(User.id == r.invitee_id))).scalar_one_or_none()
        recent.append({
            "id": str(r.id),
            "status": r.status,
            "created_at": r.created_at,
            "rewarded_at": r.rewarded_at,
            "inviter_email": inv.email if inv else None,
            "inviter_display_id": inv.display_id if inv else None,
            "inviter_code": inv.referral_code if inv else None,
            "invitee_email": tee.email if tee else None,
            "invitee_display_id": tee.display_id if tee else None,
            "source": "referral",
        })

    # Users who registered with pending promo (not yet consumed / still attached)
    promo_users_q = await db.execute(
        select(User)
        .where(User.pending_promo_code.is_not(None))
        .order_by(User.created_at.desc())
        .limit(50)
    )
    promo_regs = [
        {
            "user_id": str(u.id),
            "email": u.email,
            "display_id": u.display_id,
            "pending_promo_code": u.pending_promo_code,
            "created_at": u.created_at,
            "source": "promo",
        }
        for u in promo_users_q.scalars().all()
    ]

    return {
        "summary": {
            "referral_pairs_total": int(total_rewards or 0),
            "referral_pending": int(pending or 0),
            "referral_rewarded": int(rewarded or 0),
            "users_from_referral": int(referred_users or 0),
            "users_with_pending_promo": int(promo_pending_users or 0),
            "bonus_days": app_settings.REFERRAL_BONUS_DAYS,
            "monthly_reward_limit": app_settings.REFERRAL_MONTHLY_REWARD_LIMIT,
        },
        "top_inviters": top_inviters,
        "recent_referrals": recent,
        "pending_promo_registrations": promo_regs,
    }


# App updates (PC / Android)
@router.get("/updates")
async def list_updates(_: bool = Depends(get_admin_credentials)):
    return update_service.list_all()


@router.post("/updates/upload")
async def upload_update(
    platform: str = Form(..., pattern="^(pc|android|linux)$"),
    version: Optional[str] = Form(None),
    file: UploadFile = File(...),
    _: bool = Depends(get_admin_credentials),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")
    ext = os.path.splitext(file.filename)[1].lower()
    if platform == "pc" and ext not in (".exe", ".msi"):
        raise HTTPException(status_code=400, detail="PC update must be .exe or .msi")
    if platform == "linux" and ext not in (".appimage", ".deb"):
        raise HTTPException(status_code=400, detail="Linux update must be .AppImage or .deb")
    if platform == "android" and ext != ".apk":
        raise HTTPException(status_code=400, detail="Android update must be .apk")

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    try:
        info = update_service.publish_file(platform, file.filename, tmp_path, version=version)
        return {"message": "Update published", **info}
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@router.delete("/updates/{platform}")
async def delete_update(
    platform: str,
    _: bool = Depends(get_admin_credentials),
):
    if platform not in update_service.PLATFORMS:
        raise HTTPException(status_code=400, detail="Invalid platform")
    update_service.delete_platform_update(platform)
    return {"message": f"Update for {platform} removed"}


@router.get("/updates/build-status")
async def updates_build_status(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.build_agent_service import get_build_status
    return await get_build_status(db)


@router.post("/updates/build-stop")
async def updates_build_stop(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.build_agent_service import request_stop_build
    return await request_stop_build(db)


@router.get("/updates/build-config")
async def updates_build_config(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.build_agent_service import set_nightly_build_flags
    return await set_nightly_build_flags(db)


@router.post("/updates/build-config")
async def updates_set_build_config(
    req: BuildConfigRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.build_agent_service import set_nightly_build_flags
    return await set_nightly_build_flags(
        db,
        pc_enabled=req.pc_enabled,
        android_enabled=req.android_enabled,
    )


@router.post("/updates/build/{platform}")
async def updates_build_release(
    platform: str,
    background_tasks: BackgroundTasks,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    if platform not in update_service.PLATFORMS:
        raise HTTPException(status_code=400, detail="Invalid platform")
    from app.services.vk_agent_auth import is_agent_enabled
    from app.services.build_agent_service import get_build_status, build_platform_background

    if not await is_agent_enabled(db):
        raise HTTPException(
            status_code=400,
            detail="Подключите AI-агент VK (нужен для создания bootstrap-хеша)",
        )
    status = await get_build_status(db)
    if status.get("running"):
        raise HTTPException(status_code=409, detail="Сборка уже выполняется")
    background_tasks.add_task(build_platform_background, platform)
    return {"message": f"Сборка {platform} запущена", "platform": platform}


@router.get("/updates/github-status")
async def updates_github_status(_: bool = Depends(get_admin_credentials)):
    from app.services.github_release_service import GITHUB_OWNER, GITHUB_REPO, is_configured
    return {
        "configured": is_configured(),
        "repo": f"{GITHUB_OWNER}/{GITHUB_REPO}",
        "landing_url": "https://silentvpn3.github.io",
    }


@router.post("/updates/publish-github/{platform}")
async def publish_update_to_github(
    platform: str,
    _: bool = Depends(get_admin_credentials),
):
    if platform not in update_service.PLATFORMS:
        raise HTTPException(status_code=400, detail="Invalid platform")
    from app.services.github_release_service import GitHubReleaseError, publish_platform
    try:
        info = await publish_platform(platform)
        return {"message": f"Опубликовано на GitHub: {_platform_label(platform)} v{info['version']}", **info}
    except GitHubReleaseError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/updates/publish-github")
async def publish_all_updates_to_github(_: bool = Depends(get_admin_credentials)):
    from app.services.github_release_service import GitHubReleaseError, publish_all_available
    try:
        items = await publish_all_available()
        return {
            "message": f"Опубликовано на GitHub: {len(items)} платформ(ы)",
            "items": items,
        }
    except GitHubReleaseError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _platform_label(platform: str) -> str:
    if platform == "pc":
        return "PC (Windows)"
    if platform == "linux":
        return "PC (Linux)"
    return "Android"


# ─── Варианты обхода / olcrtc (вариант 2) ───────────────────────────────────


class OlcrtcRoomBody(BaseModel):
    id: str = ""
    url: str = ""
    max_clients: int = 4
    device_types: list[str] = []


class OlcrtcProviderBody(BaseModel):
    enabled: bool = False
    room: str = ""
    transport: str = "datachannel"
    rooms: list[OlcrtcRoomBody] = []


class OlcrtcSettingsBody(BaseModel):
    enabled: bool = False
    crypto_key: str = ""
    providers: dict[str, OlcrtcProviderBody] = {}
    srv_status: Optional[str] = None
    srv_message: Optional[str] = None


@router.get("/bypass/olcrtc")
async def get_olcrtc_bypass(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.olcrtc_settings import load_olcrtc_settings

    s = await load_olcrtc_settings(db)
    return s.to_dict()


@router.put("/bypass/olcrtc")
async def put_olcrtc_bypass(
    body: OlcrtcSettingsBody,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.olcrtc_settings import (
        OlcrtcProviderConfig,
        OlcrtcRoomSlot,
        OlcrtcSettings,
        PROVIDERS,
        DEFAULT_TRANSPORTS,
        load_olcrtc_settings,
        save_olcrtc_settings,
    )

    prev = await load_olcrtc_settings(db)
    providers = {}
    for name in PROVIDERS:
        src = (body.providers or {}).get(name)
        if src is None:
            providers[name] = prev.providers.get(name) or OlcrtcProviderConfig(
                transport=DEFAULT_TRANSPORTS[name]
            )
        else:
            rooms = []
            for i, r in enumerate(src.rooms or []):
                url = (r.url or "").strip()
                if not url:
                    continue
                rooms.append(
                    OlcrtcRoomSlot(
                        id=(r.id or f"r{i}").strip() or f"r{i}",
                        url=url,
                        max_clients=max(1, int(r.max_clients or 4)),
                        device_types=[
                            str(x).strip().lower()
                            for x in (r.device_types or [])
                            if str(x).strip()
                        ],
                    )
                )
            legacy = (src.room or "").strip()
            if not rooms and legacy:
                rooms = [
                    OlcrtcRoomSlot(id="default", url=legacy, max_clients=8, device_types=[])
                ]
            providers[name] = OlcrtcProviderConfig(
                enabled=bool(src.enabled),
                room=legacy or (rooms[0].url if rooms else ""),
                transport=(src.transport or DEFAULT_TRANSPORTS[name]).strip()
                or DEFAULT_TRANSPORTS[name],
                rooms=rooms,
            )
    key = (body.crypto_key or "").strip() or prev.crypto_key
    if key and len(key) != 64:
        raise HTTPException(status_code=400, detail="crypto_key must be 64 hex characters")
    settings = OlcrtcSettings(
        enabled=bool(body.enabled),
        crypto_key=key,
        providers=providers,
        srv_status=body.srv_status if body.srv_status is not None else prev.srv_status,
        srv_message=body.srv_message if body.srv_message is not None else prev.srv_message,
    )
    saved = await save_olcrtc_settings(db, settings)
    # JSON rooms[] → БД OlcrtcRoom (иначе /olcrtc-config отдаёт старый канал)
    from app.services.olcrtc_rooms_db import (
        reconcile_rooms_from_settings,
        write_all_unit_yaml_from_db,
    )

    recon = await reconcile_rooms_from_settings(db, saved)
    if recon.get("updated") or recon.get("created"):
        try:
            files = await write_all_unit_yaml_from_db(db)
            saved.srv_status = "pending_apply"
            changed = ", ".join(recon.get("changed_units") or []) or "—"
            saved.srv_message = (
                f"Пул обновлён: изменено {recon.get('updated') or 0}, "
                f"создано {recon.get('created') or 0}; YAML для {len(files)} unit’ов записан. "
                f"На сервере выполните: python scripts/apply_olcrtc_units_from_db.py "
                f"(иначе srv останется на старом канале). Затронуты: {changed}"
            )
            await save_olcrtc_settings(db, saved)
        except Exception as e:
            saved.srv_status = "pending_apply"
            saved.srv_message = (
                f"Пул обновлён, но запись YAML не удалась: {e}. "
                f"Проверьте права на /opt/silent-vpn/olcrtc/"
            )
            await save_olcrtc_settings(db, saved)
    out = saved.to_dict()
    out["reconcile"] = recon
    return out


@router.post("/bypass/olcrtc/generate-key")
async def generate_olcrtc_key(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.olcrtc_settings import (
        generate_crypto_key,
        load_olcrtc_settings,
        save_olcrtc_settings,
    )

    s = await load_olcrtc_settings(db)
    s.crypto_key = generate_crypto_key()
    saved = await save_olcrtc_settings(db, s)
    return {"crypto_key": saved.crypto_key, "settings": saved.to_dict()}


@router.get("/bypass/olcrtc/server-yaml")
async def get_olcrtc_server_yaml(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.olcrtc_rooms_db import (
        ensure_rooms_synced,
        list_rooms,
        render_unit_yaml,
        sync_rooms_from_settings_json,
    )
    from app.services.olcrtc_settings import load_olcrtc_settings

    s = await load_olcrtc_settings(db)
    await sync_rooms_from_settings_json(db, s)
    await ensure_rooms_synced(db)
    files: dict[str, str] = {}
    try:
        for r in await list_rooms(db):
            if r.status not in ("active", "provisioning"):
                continue
            files[r.unit_name] = render_unit_yaml(s, r)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    default = files.get("pc-telemost") or files.get("pc-wbstream") or next(iter(files.values()), "")
    return {"yaml": default, "files": files}


@router.post("/bypass/olcrtc/apply")
async def apply_olcrtc_server_yaml(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Пишет server-*.yaml из БД-пула OlcrtcRoom (+ legacy aliases)."""
    from app.services.olcrtc_settings import load_olcrtc_settings, save_olcrtc_settings
    from app.services.olcrtc_rooms_db import (
        ensure_rooms_synced,
        sync_rooms_from_settings_json,
        write_all_unit_yaml_from_db,
    )

    from app.services.olcrtc_rooms_db import reconcile_rooms_from_settings

    s = await load_olcrtc_settings(db)
    recon = await reconcile_rooms_from_settings(db, s)
    await sync_rooms_from_settings_json(db, s)
    await ensure_rooms_synced(db)
    try:
        files = await write_all_unit_yaml_from_db(db)
        paths = list(files.keys())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    s.srv_message = (
        f"YAML записан ({len(paths)} unit’ов). "
        f"Пул: изменено {recon.get('updated') or 0}, создано {recon.get('created') or 0}, "
        f"sticky сброшено {recon.get('sticky_cleared') or 0}. "
        f"Чтобы поднять srv, на VPS: python scripts/apply_olcrtc_units_from_db.py "
        f"(без этого клиенты получат новые room id, а процесс — старые)."
    )
    s.srv_status = "pending_apply"
    await save_olcrtc_settings(db, s)
    return {
        "ok": True,
        "paths": paths,
        "units": paths,
        "reconcile": recon,
        "message": s.srv_message,
        "settings": s.to_dict(),
    }


@router.get("/bypass/olcrtc/rooms")
async def list_olcrtc_rooms_admin(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.olcrtc_rooms_db import (
        ensure_rooms_synced,
        list_rooms,
        pool_metrics,
        room_to_dict,
        sync_rooms_from_settings_json,
    )

    await sync_rooms_from_settings_json(db)
    await ensure_rooms_synced(db)
    rooms = await list_rooms(db)
    return {
        "rooms": [room_to_dict(r) for r in rooms],
        "metrics": await pool_metrics(db),
    }


class OlcrtcRoomStatusBody(BaseModel):
    status: str


@router.post("/bypass/olcrtc/rooms/{room_id}/status")
async def set_olcrtc_room_status(
    room_id: str,
    body: OlcrtcRoomStatusBody,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    import uuid as _uuid

    from ai.olcrtc_host_provision_client import apply_units_via_host
    from app.services.olcrtc_rooms_db import (
        render_unit_yaml,
        room_to_dict,
        set_room_status,
        write_server_yaml_file,
    )
    from app.services.olcrtc_settings import load_olcrtc_settings

    status = (body.status or "").strip().lower()
    if status not in ("active", "draining", "offline", "provisioning", "error"):
        raise HTTPException(status_code=400, detail="bad status")
    try:
        rid = _uuid.UUID(room_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad room_id")
    room = await set_room_status(db, rid, status)
    if not room:
        raise HTTPException(status_code=404, detail="room not found")
    unit_msg = ""
    unit = (room.unit_name or "").strip()
    if unit and status in ("offline", "active"):
        try:
            if status == "offline":
                host = await apply_units_via_host({}, [unit])
                unit_msg = "srv остановлен" if host.get("ok") else str(host.get("message") or "")
            else:
                settings = await load_olcrtc_settings(db)
                yaml_text = render_unit_yaml(settings, room)
                write_server_yaml_file(yaml_text, filename=f"server-{unit}.yaml")
                host = await apply_units_via_host({unit: yaml_text}, [])
                unit_msg = "srv поднят" if host.get("ok") else str(host.get("message") or "")
        except Exception as e:
            unit_msg = str(e)[:160]
    return {
        "ok": True,
        "room": room_to_dict(room),
        "unit": unit,
        "unit_message": unit_msg,
    }


@router.delete("/bypass/olcrtc/rooms/{room_id}")
async def delete_olcrtc_room_admin(
    room_id: str,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Убрать комнату из пула и погасить её srv на Улье."""
    import uuid as _uuid

    from ai.olcrtc_host_provision_client import apply_units_via_host
    from app.services.olcrtc_rooms_db import delete_room_row, get_room

    try:
        rid = _uuid.UUID(room_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad room_id")
    room = await get_room(db, rid)
    if not room:
        raise HTTPException(status_code=404, detail="room not found")
    unit = room.unit_name
    await delete_room_row(db, rid, reason="удалено из админки")
    host = await apply_units_via_host({}, [unit])
    return {
        "ok": True,
        "unit": unit,
        "unit_stopped": bool(host.get("ok")),
        "message": f"Комната {unit} удалена"
        + ("" if host.get("ok") else f"; srv не погашен: {host.get('message')}"),
    }


@router.post("/bypass/olcrtc/rooms/{room_id}/release")
async def release_olcrtc_room_admin(
    room_id: str,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Снять закрепления с комнаты — места сразу освобождаются."""
    import uuid as _uuid

    from app.models.olcrtc_room import OlcrtcRoomSticky
    from app.services.olcrtc_rooms_db import get_room, room_to_dict

    try:
        rid = _uuid.UUID(room_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad room_id")
    room = await get_room(db, rid)
    if not room:
        raise HTTPException(status_code=404, detail="room not found")
    result = await db.execute(
        delete(OlcrtcRoomSticky).where(OlcrtcRoomSticky.room_id == rid)
    )
    room.online_count = 0
    await db.commit()
    await db.refresh(room)
    return {
        "ok": True,
        "released": int(result.rowcount or 0),
        "room": room_to_dict(room),
    }


class OlcrtcRoomCreateBody(BaseModel):
    provider: str
    room_url: str
    slot_label: str = "pc"
    device_types: list[str] = []
    max_clients: int = 12
    cell_id: Optional[str] = None


@router.post("/bypass/olcrtc/rooms")
async def create_olcrtc_room_admin(
    body: OlcrtcRoomCreateBody,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    import uuid as _uuid

    from app.services.olcrtc_assign import pick_cell_for_new_room
    from app.services.olcrtc_rooms_db import create_room_row, room_to_dict

    cell_id = None
    if body.cell_id:
        try:
            cell_id = _uuid.UUID(body.cell_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="bad cell_id")
    else:
        cell = await pick_cell_for_new_room(db)
        cell_id = None if getattr(cell, "is_queen", True) else cell.id
    try:
        row = await create_room_row(
            db,
            provider=(body.provider or "").strip(),
            room_url=(body.room_url or "").strip(),
            slot_label=(body.slot_label or "pc").strip() or "pc",
            device_types=body.device_types or [(body.slot_label or "pc")],
            max_clients=max(1, int(body.max_clients or 12)),
            cell_id=cell_id,
            status="active",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "room": room_to_dict(row)}


@router.get("/bypass/olcrtc/pool-metrics")
async def get_olcrtc_pool_metrics(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.olcrtc_rooms_db import ensure_rooms_synced, pool_metrics

    await ensure_rooms_synced(db)
    return await pool_metrics(db)


@router.post("/bypass/olcrtc/rooms/{room_id}/push-cell")
async def push_olcrtc_room_to_cell(
    room_id: str,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.olcrtc_cell_push import push_room_to_cell

    result = await push_room_to_cell(db, room_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("detail") or "push failed")
    return result


@router.post("/bypass/olcrtc/push-all-cells")
async def push_all_olcrtc_cell_rooms(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.olcrtc_cell_push import push_all_cell_rooms

    return await push_all_cell_rooms(db)


class OlcrtcRoomAccountBody(BaseModel):
    label: str = ""
    storage_state: Optional[dict] = None
    storage_state_path: str = ""
    notes: str = ""


class OlcrtcRoomAccountsBody(BaseModel):
    telemost: list[OlcrtcRoomAccountBody] = []
    wbstream: list[OlcrtcRoomAccountBody] = []


class OlcrtcRoomAgentBody(BaseModel):
    enabled: Optional[bool] = None
    auto_apply_yaml: Optional[bool] = None
    target_capacity: Optional[int] = None
    target_free_ratio: Optional[float] = None
    target_rooms_telemost: Optional[int] = None
    target_rooms_wbstream: Optional[int] = None
    max_clients: Optional[int] = None
    liveness_prune: Optional[bool] = None
    min_free_per_slot: Optional[int] = None
    min_rooms_per_slot: Optional[int] = None
    max_rooms_per_slot: Optional[int] = None
    idle_room_ttl_min: Optional[int] = None
    auto_units: Optional[bool] = None
    session_mode: Optional[bool] = None
    bootstrap_warm: Optional[int] = None


@router.get("/bypass/olcrtc/room-agent")
async def get_olcrtc_room_agent(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from ai.olcrtc_host_provision_client import host_provision_status
    from app.services.olcrtc_room_accounts import load_room_accounts

    accounts = await load_room_accounts(db)
    host = await host_provision_status()
    return {
        "agent": {
            "enabled": False,
            "session_mode": True,
            "disabled_reason": "VK/WDTT only",
        },
        "accounts": accounts.public_dict(),
        "host_provision": host,
    }


@router.put("/bypass/olcrtc/room-agent")
async def put_olcrtc_room_agent(
    body: OlcrtcRoomAgentBody,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    raise HTTPException(
        status_code=410,
        detail="olcrtc room agent removed (WDTT only)",
    )


@router.post("/bypass/olcrtc/room-agent/run")
async def run_olcrtc_room_agent(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    raise HTTPException(
        status_code=410,
        detail="olcrtc room agent removed (WDTT only)",
    )


@router.put("/bypass/olcrtc/room-accounts")
async def put_olcrtc_room_accounts(
    body: OlcrtcRoomAccountsBody,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from ai.olcrtc_host_provision_client import push_storage_to_host
    from app.services.olcrtc_room_accounts import (
        OlcrtcRoomAccounts,
        ProviderAccount,
        load_room_accounts,
        save_room_accounts,
    )

    prev = await load_room_accounts(db)

    def _map(
        items: list[OlcrtcRoomAccountBody],
        prev_list: list,
    ) -> list[ProviderAccount]:
        out: list[ProviderAccount] = []
        for i, it in enumerate(items):
            state = it.storage_state if isinstance(it.storage_state, dict) else {}
            # пустой JSON не затирает уже сохранённые cookies
            if not state and i < len(prev_list) and prev_list[i].storage_state:
                state = prev_list[i].storage_state
            out.append(
                ProviderAccount(
                    label=(it.label or "").strip() or (prev_list[i].label if i < len(prev_list) else ""),
                    storage_state=state,
                    storage_state_path=(it.storage_state_path or "").strip(),
                    notes=(it.notes or "").strip(),
                )
            )
        return out

    accounts = OlcrtcRoomAccounts(
        telemost=_map(body.telemost or [], prev.telemost),
        wbstream=_map(body.wbstream or [], prev.wbstream),
    )
    saved = await save_room_accounts(db, accounts)
    host_pushed = {"telemost": False, "wbstream": False}
    for provider, lst in (("telemost", saved.telemost), ("wbstream", saved.wbstream)):
        for acc in lst:
            if acc.storage_state:
                host_pushed[provider] = await push_storage_to_host(provider, acc.storage_state)
                if host_pushed[provider]:
                    break
    # WB JWT → settings + переписать srv YAML (guest 403 без auth.token)
    wb_token_synced = False
    try:
        from app.services.olcrtc_room_accounts import sync_wbstream_auth_token_to_settings
        from app.services.olcrtc_rooms_db import write_all_unit_yaml_from_db

        tok = await sync_wbstream_auth_token_to_settings(db, saved)
        wb_token_synced = bool(tok)
        if tok:
            await write_all_unit_yaml_from_db(db)
    except Exception:
        pass
    return {
        "accounts": saved.public_dict(),
        "host_pushed": host_pushed,
        "wb_auth_token_synced": wb_token_synced,
    }
