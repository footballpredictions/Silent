from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.database import get_db
from app.models import User, Subscription, Device
from app.schemas.user import UserProfileResponse, UserResponse, SubscriptionInfo, DeviceInfo, ChangePasswordRequest
from app.core.deps import get_current_user, get_verified_user
from app.core.security import verify_password, hash_password
from app.config import settings

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserProfileResponse)
async def get_profile(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Active subscription
    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == "active")
        .order_by(Subscription.expires_at.desc())
    )
    sub = result.scalars().first()
    subscription_info = SubscriptionInfo(is_active=False)
    if sub and sub.is_active:
        subscription_info = SubscriptionInfo(
            is_active=True,
            plan_type=sub.plan_type,
            expires_at=sub.expires_at,
            days_left=sub.days_left,
        )

    # Devices
    result = await db.execute(
        select(Device).where(Device.user_id == user.id, Device.is_active == True)
    )
    devices = result.scalars().all()
    device_infos = [
        DeviceInfo(
            id=d.id,
            device_name=d.device_name,
            device_type=d.device_type,
            is_connected=d.is_connected,
            last_connected=d.last_connected,
        )
        for d in devices
    ]

    return UserProfileResponse(
        id=user.id,
        email=user.email,
        display_id=user.display_id,
        subscription=subscription_info,
        devices=device_infos,
        devices_count=len(devices),
        max_devices=settings.MAX_DEVICES_PER_USER,
    )


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
    user.password_hash = hash_password(req.new_password)
    await db.commit()
    return {"message": "Пароль изменён"}


@router.delete("/devices/{device_id}")
async def remove_device(
    device_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import uuid
    result = await db.execute(
        select(Device).where(Device.id == uuid.UUID(device_id), Device.user_id == user.id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Устройство не найдено")
    device.is_active = False
    device.is_connected = False
    await db.commit()
    return {"message": "Устройство удалено"}
