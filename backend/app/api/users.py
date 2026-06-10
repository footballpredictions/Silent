from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, Subscription, Device
from app.schemas.user import UserProfileResponse, SubscriptionInfo, DeviceInfo, ChangePasswordRequest, DeviceRenameRequest
from app.schemas.vpn import DisconnectRequest
from app.core.deps import get_current_user
from app.core.security import verify_password, hash_password
from app.config import settings
from app.services.subscription_service import is_user_admin, ensure_admin_flag, ensure_trial_subscription, user_in_test_mode
from app.services.vpn_service import (
    end_device_session,
    count_active_sessions,
    count_connected_sessions,
    clear_stale_online_status,
    prune_idle_sessions,
    collapse_duplicate_devices,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserProfileResponse)
async def get_profile(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await ensure_admin_flag(user, db)
    await clear_stale_online_status(db)
    await prune_idle_sessions(db, user.id)
    await collapse_duplicate_devices(db, user.id)
    if not await user_in_test_mode(user, db):
        await ensure_trial_subscription(db, user)
    admin = is_user_admin(user)
    test = await user_in_test_mode(user, db)

    subscription_info = SubscriptionInfo(is_active=False)
    if admin:
        subscription_info = SubscriptionInfo(
            is_active=True,
            plan_type="unlimited",
            expires_at=None,
            days_left=9999,
        )
    elif test:
        subscription_info = SubscriptionInfo(
            is_active=True,
            plan_type="test",
            expires_at=None,
            days_left=9999,
        )
    else:
        result = await db.execute(
            select(Subscription)
            .where(Subscription.user_id == user.id, Subscription.status == "active")
            .order_by(Subscription.expires_at.desc())
        )
        sub = result.scalars().first()
        if sub and sub.is_active:
            subscription_info = SubscriptionInfo(
                is_active=True,
                plan_type=sub.plan_type,
                expires_at=sub.expires_at,
                days_left=sub.days_left,
            )

    result = await db.execute(
        select(Device).where(
            Device.user_id == user.id,
            Device.is_active == True,
        ).order_by(Device.last_connected.desc().nullslast(), Device.created_at.desc())
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

    active_sessions = await count_active_sessions(db, user.id)
    connected = await count_connected_sessions(db, user.id)

    return UserProfileResponse(
        id=user.id,
        email=user.email,
        display_id=user.display_id,
        is_admin=admin,
        subscription=subscription_info,
        devices=device_infos,
        devices_count=active_sessions,
        connected_count=connected,
        max_devices=settings.MAX_DEVICES_PER_USER,
        vk_linked=user.vk_user_id is not None,
        vk_user_id=user.vk_user_id,
    )


@router.post("/logout")
async def logout_session(
    req: DisconnectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Exit account: delete device session and free slot."""
    await end_device_session(db, user.id, req.device_fingerprint)
    return {"status": "logged_out"}


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


@router.patch("/devices/{device_id}")
async def rename_device(
    device_id: str,
    req: DeviceRenameRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import uuid

    name = req.device_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Имя не может быть пустым")
    if len(name) > 64:
        raise HTTPException(status_code=400, detail="Имя слишком длинное (макс. 64 символа)")

    result = await db.execute(
        select(Device).where(Device.id == uuid.UUID(device_id), Device.user_id == user.id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Устройство не найдено")
    device.device_name = name
    await db.commit()
    return {"message": "Имя обновлено", "device_name": name}


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
    await db.delete(device)
    await db.commit()
    return {"message": "Сессия удалена"}
