"""VPN configuration and connection API."""
import json
from fastapi import APIRouter, Depends, HTTPException
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
    HashRefreshRequest,
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
)
from app.services.subscription_service import user_has_active_subscription
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
    has_sub = await user_has_active_subscription(user, db)
    return await build_vpn_config_for_user(db, device, user, has_sub)


@router.get("/hashes")
async def get_vk_hashes(
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    """VK TURN hashes for user: bootstrap + up to 3 server slots."""
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

    if not device.is_connected:
        connected = await count_connected_sessions(db, user.id)
        if connected >= settings.MAX_DEVICES_PER_USER:
            raise HTTPException(
                status_code=403,
                detail=f"Достигнут лимит {settings.MAX_DEVICES_PER_USER} одновременных подключений VPN.",
            )

    device.is_connected = True
    device.last_connected = datetime.utcnow()
    device.last_ip = req.last_ip
    await db.commit()
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
    return {"status": "disconnected"}


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


@router.get("/theme", response_model=ThemeResponse)
async def get_theme(db: AsyncSession = Depends(get_db)):
    """Public endpoint — clients fetch UI theme from backend."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == "theme"))
    setting = result.scalar_one_or_none()
    if setting:
        try:
            data = json.loads(setting.value)
            return ThemeResponse(**data)
        except Exception:
            pass
    return ThemeResponse()
