"""VPN configuration and connection API."""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.database import get_db
from app.models import User, Device, AppSetting
from app.schemas.vpn import (
    DeviceRegisterRequest, VpnConfigResponse,
    ConnectRequest, DisconnectRequest, AppExclusionRequest, ThemeResponse,
)
from app.core.deps import get_verified_user
from app.services.vpn_service import (
    register_device,
    _build_vpn_config,
    get_active_vk_hashes,
    count_connected_sessions,
)
from app.services.subscription_service import user_has_active_subscription
from app.config import settings

router = APIRouter(prefix="/vpn", tags=["vpn"])


async def _check_active_subscription(user: User, db: AsyncSession):
    if not await user_has_active_subscription(user, db):
        raise HTTPException(status_code=402, detail="Активная подписка не найдена")


@router.post("/device/register", response_model=VpnConfigResponse)
async def device_register(
    req: DeviceRegisterRequest,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    await _check_active_subscription(user, db)
    try:
        config = await register_device(
            db, user,
            device_name=req.device_name,
            device_type=req.device_type,
            device_fingerprint=req.device_fingerprint,
            wg_public_key=req.wg_public_key,
        )
        if user.vk_user_id:
            try:
                from app.services.vk_config_publisher import publish_config_for_user
                await publish_config_for_user(db, user)
            except Exception:
                pass
        return config
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/config", response_model=VpnConfigResponse)
async def get_config(
    fingerprint: str,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    await _check_active_subscription(user, db)
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
    return await _build_vpn_config(db, device)


@router.get("/hashes")
async def get_vk_hashes(
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    """All active VK TURN hashes — client merges with bootstrap from VK."""
    await _check_active_subscription(user, db)
    hashes = await get_active_vk_hashes(db)
    if not hashes:
        raise HTTPException(status_code=503, detail="VK-хеши ещё не созданы на сервере")
    return {"hashes": hashes, "bootstrap_hash": hashes[0]}


@router.post("/connect")
async def connect(
    req: ConnectRequest,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    await _check_active_subscription(user, db)
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
    return {"status": "connected"}


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
