"""Admin API — dashboard, user management, VK credentials, system stats."""
import json
import os
import psutil
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models import User, Subscription, Device, VkCredentials, VkHash, AppSetting, PromoCode
from app.core.deps import get_admin_credentials
from app.core.security import encrypt_value, decrypt_value
from app.schemas.vpn import ThemeResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def get_stats(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard system stats."""
    # System resources
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    # DB stats
    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    active_subs = (await db.execute(
        select(func.count(Subscription.id))
        .where(Subscription.status == "active", Subscription.expires_at > datetime.utcnow())
    )).scalar_one()
    connected_devices = (await db.execute(
        select(func.count(Device.id)).where(Device.is_connected == True)
    )).scalar_one()

    # VK hashes status
    hashes_result = await db.execute(select(VkHash).order_by(VkHash.slot_index))
    hashes = hashes_result.scalars().all()

    return {
        "system": {
            "cpu_percent": cpu,
            "memory_total_gb": round(mem.total / 1e9, 1),
            "memory_used_gb": round(mem.used / 1e9, 1),
            "memory_percent": mem.percent,
            "disk_total_gb": round(disk.total / 1e9, 1),
            "disk_used_gb": round(disk.used / 1e9, 1),
            "disk_percent": disk.percent,
        },
        "users": {
            "total": total_users,
            "active_subscriptions": active_subs,
            "connected_devices": connected_devices,
        },
        "vk_hashes": [
            {
                "slot": h.slot_index,
                "hash": h.hash_value[:12] + "...",
                "is_active": h.is_active,
                "fail_count": h.fail_count,
                "last_checked": h.last_checked,
            }
            for h in hashes
        ],
    }


@router.get("/users")
async def list_users(
    skip: int = 0,
    limit: int = 50,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
    )
    users = result.scalars().all()

    out = []
    for user in users:
        sub_result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == user.id, Subscription.status == "active"
            ).order_by(Subscription.expires_at.desc())
        )
        sub = sub_result.scalars().first()
        dev_count = (await db.execute(
            select(func.count(Device.id)).where(Device.user_id == user.id, Device.is_active == True)
        )).scalar_one()

        out.append({
            "id": str(user.id),
            "display_id": user.display_id,
            "email": user.email,
            "is_verified": user.is_verified,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "subscription": {
                "active": sub.is_active if sub else False,
                "plan": sub.plan_type if sub else None,
                "expires_at": sub.expires_at if sub else None,
            },
            "devices_count": dev_count,
        })
    return out


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
    return {"status": "banned" if not user.is_active else "unbanned"}


# VK credentials management
class VkCredentialsRequest(BaseModel):
    login: str
    password: str


@router.post("/vk/credentials")
async def set_vk_credentials(
    req: VkCredentialsRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()
    enc_login = encrypt_value(req.login)
    enc_pass = encrypt_value(req.password)

    if creds:
        creds.login_enc = enc_login
        creds.password_enc = enc_pass
        creds.is_configured = True
    else:
        db.add(VkCredentials(id=1, login_enc=enc_login, password_enc=enc_pass, is_configured=True))
    await db.commit()
    return {"message": "VK credentials saved"}


@router.get("/vk/hashes")
async def get_vk_hashes(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(VkHash).order_by(VkHash.slot_index))
    hashes = result.scalars().all()
    return [
        {
            "id": str(h.id),
            "slot": h.slot_index,
            "hash": h.hash_value,
            "call_link": h.call_link,
            "is_active": h.is_active,
            "fail_count": h.fail_count,
            "last_checked": h.last_checked,
            "created_at": h.created_at,
        }
        for h in hashes
    ]


@router.post("/vk/recreate")
async def recreate_vk_hashes(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger VK hash recreation."""
    from ai.vk_manager import VkManager
    manager = VkManager(db)
    success = await manager.recreate_all_hashes()
    return {"success": success, "message": "Хеши пересозданы" if success else "Ошибка пересоздания"}


# Theme management
@router.get("/theme")
async def get_theme_admin(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AppSetting).where(AppSetting.key == "theme"))
    setting = result.scalar_one_or_none()
    if setting:
        return json.loads(setting.value)
    return ThemeResponse().model_dump()


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
    else:
        db.add(AppSetting(key="theme", value=data))
    await db.commit()
    return {"message": "Theme updated"}


# Promo codes
class PromoCreateRequest(BaseModel):
    code: str
    discount_percent: int = 0
    extra_days: int = 0
    max_uses: int = 1
    expires_at: Optional[datetime] = None


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
