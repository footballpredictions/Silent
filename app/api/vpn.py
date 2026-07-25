"""VPN configuration and connection API."""
import json
import secrets
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.database import get_db
from app.models import User, Device, AppSetting
from app.schemas.vpn import (
    DeviceRegisterRequest,
    BootstrapConfigRequest,
    VpnConfigResponse,
    ConnectRequest,
    DisconnectRequest,
    AppExclusionRequest,
    ThemeResponse,
    SyncStateResponse,
    HashRefreshRequest,
    HashFailureReportRequest,
    InternalOnlineRequest,
    InternalOnlineResponse,
    ThreatFilterMetaRequest,
    VpsCleanupMetaRequest,
)
from app.core.deps import get_verified_user
from app.services.vpn_service import (
    register_device,
    register_bootstrap_device,
    build_vpn_config_for_user,
    get_active_vk_hashes,
    get_bootstrap_hashes_for_user,
    count_connected_sessions,
    clear_stale_online_status,
    set_device_online,
    mark_client_disconnect_latch,
    touch_user_last_seen,
)
from app.services.subscription_service import (
    user_has_active_subscription,
    ensure_trial_subscription,
    require_active_subscription,
    require_device_trial_not_reused,
    is_user_admin,
)
from app.services.theme_settings import load_theme
from app.config import settings

router = APIRouter(prefix="/vpn", tags=["vpn"])


@router.post("/bootstrap-config", response_model=VpnConfigResponse)
async def bootstrap_config(req: BootstrapConfigRequest, db: AsyncSession = Depends(get_db)):
    """Pre-login VPN — reach backend through VK TURN with bootstrap hash only."""
    await clear_stale_online_status(db)
    try:
        return await register_bootstrap_device(
            db,
            bootstrap_hash=req.bootstrap_hash,
            device_fingerprint=req.device_fingerprint,
            device_type=req.device_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/device/register", response_model=VpnConfigResponse)
async def device_register(
    req: DeviceRegisterRequest,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    await clear_stale_online_status(db)
    await require_device_trial_not_reused(db, user, req.device_fingerprint)
    await ensure_trial_subscription(db, user)
    await require_active_subscription(user, db)
    has_sub = await user_has_active_subscription(user, db)
    try:
        if req.bootstrap_hash:
            from app.services.user_hash_service import (
                set_user_bootstrap_hash,
                cleanup_bootstrap_devices,
                ensure_user_server_hashes,
            )

            await set_user_bootstrap_hash(db, user, req.bootstrap_hash)
            await cleanup_bootstrap_devices(db, req.device_fingerprint)
            await ensure_user_server_hashes(db, user.id)

        await register_device(
            db,
            user,
            device_name=req.device_name,
            device_type=req.device_type,
            device_fingerprint=req.device_fingerprint,
            wg_public_key=req.wg_public_key,
        )
        result = await db.execute(
            select(Device).where(
                Device.user_id == user.id,
                Device.device_fingerprint == req.device_fingerprint,
                Device.is_active == True,
            )
        )
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=500, detail="Не удалось создать устройство")
        return await build_vpn_config_for_user(db, device, user, has_sub)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/config", response_model=VpnConfigResponse)
async def get_config(
    fingerprint: str,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_fingerprint == fingerprint,
            Device.is_active == True,
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Сессия устройства не найдена. Войдите снова.")
    await require_device_trial_not_reused(db, user, fingerprint)
    await ensure_trial_subscription(db, user)
    await require_active_subscription(user, db)
    has_sub = await user_has_active_subscription(user, db)
    from app.services.user_hash_service import ensure_user_server_hashes

    await ensure_user_server_hashes(db, user.id)
    return await build_vpn_config_for_user(db, device, user, has_sub)


@router.get("/hashes")
async def get_vk_hashes(
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    """VK TURN hashes for user: bootstrap + up to 4 server slots."""
    from app.services.user_hash_service import get_vpn_hashes_for_user, get_hash_items_for_user

    hashes = await get_vpn_hashes_for_user(db, user)
    if not hashes:
        raise HTTPException(
            status_code=503,
            detail="Хеш не задан. Введите хеш звонка VK на экране входа.",
        )
    boot = (user.bootstrap_hash or hashes[0]).strip()
    return {
        "hashes": hashes,
        "bootstrap_hash": boot,
        "mode": "full" if len(hashes) > 1 else "bootstrap",
        "items": await get_hash_items_for_user(db, user),
    }


@router.post("/hashes/request-refresh")
async def request_hash_refresh(
    req: HashRefreshRequest,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    """Client requests new server hashes when only bootstrap remains."""
    from app.services.user_hash_service import request_hash_refresh as do_refresh

    ok, message = await do_refresh(db, user)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    from app.services.user_hash_service import get_vpn_hashes_for_user

    hashes = await get_vpn_hashes_for_user(db, user)
    return {"ok": True, "message": message, "hashes": hashes}


@router.post("/hashes/report-failure")
async def report_hash_failure(
    req: HashFailureReportRequest,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    """Client reports hash/tunnel failure from libclient (until AI agent monitor runs)."""
    from app.services.user_hash_service import report_hash_failure as do_report

    ok, detail = await do_report(
        db,
        user,
        hash_hint=req.hash,
        error_type=(req.error_type or "unknown").strip()[:64],
        message=(req.message or "")[:500],
    )
    if not ok:
        raise HTTPException(status_code=404, detail=detail)
    return {"ok": True, "detail": detail}


@router.post("/connect")
async def connect(
    req: ConnectRequest,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_fingerprint == req.device_fingerprint,
            Device.is_active == True,
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Сессия устройства не найдена. Войдите снова.")

    await ensure_trial_subscription(db, user)
    await require_active_subscription(user, db)

    from app.services.user_hash_service import ensure_user_server_hashes

    await ensure_user_server_hashes(db, user.id)

    if not device.is_connected:
        connected = await count_connected_sessions(db, user.id)
        if not is_user_admin(user) and connected >= settings.MAX_DEVICES_PER_USER:
            raise HTTPException(
                status_code=403,
                detail=f"Достигнут лимит {settings.MAX_DEVICES_PER_USER} одновременных подключений VPN.",
            )

    device.is_connected = True
    device.last_connected = datetime.utcnow()
    device.last_ip = req.last_ip
    await touch_user_last_seen(db, user, commit=False)
    await db.commit()
    from app.services.peak_online import record_online_peak

    await record_online_peak(db)
    return {"status": "connected", "mode": "full" if await user_has_active_subscription(user, db) else "bootstrap"}


@router.post("/disconnect")
async def disconnect(
    req: DisconnectRequest,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    """VPN off — session stays active until logout."""
    result = await db.execute(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_fingerprint == req.device_fingerprint,
            Device.is_active == True,
        )
    )
    device = result.scalar_one_or_none()
    if device:
        device.is_connected = False
        await db.commit()
        mark_client_disconnect_latch(str(device.id), device.device_fingerprint or "")
    return {"status": "disconnected"}


@router.post("/internal/online", response_model=InternalOnlineResponse)
async def internal_online(
    req: InternalOnlineRequest,
    x_internal_secret: str = Header(default="", alias="X-Internal-Secret"),
    x_hive_cell_id: str = Header(default="", alias="X-Hive-Cell-Id"),
    db: AsyncSession = Depends(get_db),
):
    """Server-to-server online report from wdtt-server (no client JWT).

    wdtt-server pushes online=true on connect / keepalive and online=false on drop.
    Response includes subscription_active / vpn_allowed — wdtt-server may drop the
    session when vpn_allowed=false (same channel as online status, no client HTTP).
    """
    secret = (settings.INTERNAL_API_SECRET or "").strip()
    if not secret or not secrets.compare_digest(x_internal_secret, secret):
        raise HTTPException(status_code=403, detail="forbidden")
    await clear_stale_online_status(db)
    result = await set_device_online(db, req.device_id.strip(), bool(req.online))
    if x_hive_cell_id.strip():
        from app.services import hive_service
        import uuid as _uuid

        try:
            cid = _uuid.UUID(x_hive_cell_id.strip())
            cell = await hive_service.get_cell_by_id(db, cid)
            if cell:
                await hive_service.refresh_cell_load(db, cell)
                await db.commit()
        except (ValueError, TypeError):
            pass
    return InternalOnlineResponse(**result)


def _require_internal_secret(x_internal_secret: str) -> None:
    secret = (settings.INTERNAL_API_SECRET or "").strip()
    if not secret or not secrets.compare_digest(x_internal_secret, secret):
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/internal/threat-filter")
async def internal_threat_filter_status(
    x_internal_secret: str = Header(default="", alias="X-Internal-Secret"),
    db: AsyncSession = Depends(get_db),
):
    """Host sync: is threat DNS filter enabled (for iptables DNAT)."""
    _require_internal_secret(x_internal_secret)
    from app.services.threat_filter_settings import is_threat_filter_enabled

    return {"enabled": await is_threat_filter_enabled(db)}


@router.post("/internal/threat-filter/meta")
async def internal_threat_filter_meta(
    req: ThreatFilterMetaRequest,
    x_internal_secret: str = Header(default="", alias="X-Internal-Secret"),
    db: AsyncSession = Depends(get_db),
):
    """Host updater reports HaGeZi list size / timestamp after download."""
    _require_internal_secret(x_internal_secret)
    from app.services.threat_filter_settings import update_threat_filter_meta

    return await update_threat_filter_meta(
        db,
        domains_count=req.domains_count,
        list_updated_at=req.list_updated_at or "",
    )


@router.get("/internal/vps-cleanup")
async def internal_vps_cleanup_config(
    x_internal_secret: str = Header(default="", alias="X-Internal-Secret"),
    db: AsyncSession = Depends(get_db),
):
    """Host cleaner polls schedule/enabled/run_now."""
    _require_internal_secret(x_internal_secret)
    from app.services.vps_cleanup_settings import get_vps_cleanup_host_payload

    return await get_vps_cleanup_host_payload(db)


@router.post("/internal/vps-cleanup/meta")
async def internal_vps_cleanup_meta(
    req: VpsCleanupMetaRequest,
    x_internal_secret: str = Header(default="", alias="X-Internal-Secret"),
    db: AsyncSession = Depends(get_db),
):
    """Host cleaner reports last run; clears run_now."""
    _require_internal_secret(x_internal_secret)
    from app.services.vps_cleanup_settings import update_vps_cleanup_meta

    return await update_vps_cleanup_meta(db, summary=req.summary or "", clear_run_now=True)


@router.post("/exclusions")
async def set_exclusions(
    req: AppExclusionRequest,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Device).where(Device.id == req.device_id, Device.user_id == user.id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Устройство не найдено")

    key = f"exclusions_{device.id}"
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = result.scalar_one_or_none()
    data = json.dumps({"mode": req.mode, "packages": req.packages})
    if setting:
        setting.value = data
    else:
        db.add(AppSetting(key=key, value=data))
    await db.commit()
    return {"message": "Исключения сохранены"}


@router.get("/exclusions/{device_id}")
async def get_exclusions(
    device_id: str,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == f"exclusions_{device_id}")
    )
    setting = result.scalar_one_or_none()
    if not setting:
        return {"mode": "blacklist", "packages": []}
    return json.loads(setting.value)


@router.get("/sync-state", response_model=SyncStateResponse)
async def get_sync_state(
    hashes_since: int = 0,
    theme_since: int = 0,
    profile_since: int = 0,
    since: int = 0,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    """Revision check for hashes, theme, profile — per-section since."""
    from app.services.config_sync_service import build_sync_state

    hs = max(0, hashes_since)
    ts = max(0, theme_since)
    ps = max(0, profile_since)
    if since > 0 and hs == 0 and ts == 0 and ps == 0:
        hs = ts = ps = since
    return await build_sync_state(
        db,
        user,
        hashes_since=hs,
        theme_since=ts,
        profile_since=ps,
    )


@router.get("/theme", response_model=ThemeResponse)
async def get_theme(db: AsyncSession = Depends(get_db)):
    """Public endpoint — clients fetch UI theme from backend."""
    return await load_theme(db, persist_migration=True)


@router.get("/hive-meta")
async def get_hive_meta(db: AsyncSession = Depends(get_db)):
    """Публично: Улей + standby-соты для failover клиентов."""
    from app.services.hive_standby import hive_meta

    return await hive_meta(db)


@router.get("/olcrtc-config")
async def get_olcrtc_config(
    device_type: str = "",
    fingerprint: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Публичный конфиг варианта 2 (olcrtc). room из пула по device_type/fingerprint."""
    from app.services.olcrtc_settings import load_olcrtc_settings, public_client_config

    s = await load_olcrtc_settings(db)
    return public_client_config(
        s,
        device_type=device_type or "",
        fingerprint=fingerprint or "",
    )
