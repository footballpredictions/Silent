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


# VK credentials & hash management
class VkCredentialsRequest(BaseModel):
    login: str = ""
    password: str = ""
    access_token: str = ""


class VkHashManualRequest(BaseModel):
    hash: str
    slot: int


class VkHashSlotRequest(BaseModel):
    slot: int


@router.get("/vk/status")
async def vk_auth_status(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.vk_agent_auth import get_auth_status
    return await get_auth_status(db)


@router.post("/vk/credentials")
async def set_vk_credentials(
    req: VkCredentialsRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.vk_agent_auth import save_stored_token, validate_token

    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()

    if req.access_token.strip():
        token = req.access_token.strip()
        ok, msg, uid = await validate_token(token)
        if not ok:
            raise HTTPException(status_code=400, detail=f"Токен не работает: {msg}")
        await save_stored_token(db, token)
        return {"message": f"VK токен сохранён (user_id={uid})", "auth_ok": True}

    if not req.login.strip() or not req.password:
        raise HTTPException(status_code=400, detail="Укажите логин/пароль или access_token")

    enc_login = encrypt_value(req.login.strip())
    enc_pass = encrypt_value(req.password)

    if creds:
        creds.login_enc = enc_login
        creds.password_enc = enc_pass
        creds.is_configured = True
    else:
        db.add(VkCredentials(id=1, login_enc=enc_login, password_enc=enc_pass, is_configured=True))
    await db.commit()

    from app.services.vk_agent_auth import resolve_agent_token
    token, msg = await resolve_agent_token(db)
    if token:
        return {"message": f"Credentials сохранены. {msg}", "auth_ok": True}
    return {"message": f"Credentials сохранены, но авторизация не удалась: {msg}", "auth_ok": False}


@router.post("/vk/auth/test")
async def test_vk_auth(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.vk_agent_auth import get_auth_status
    status = await get_auth_status(db)
    if not status["auth_ok"]:
        raise HTTPException(status_code=400, detail=status.get("auth_error") or "Auth failed")
    return status


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
    await manager.upsert_hash_slot(req.slot, hash_val, link)

    try:
        from app.services.vk_config_publisher import publish_all_configs
        await publish_all_configs(db)
    except Exception:
        pass

    return {"success": True, "slot": req.slot, "hash": hash_val, "message": f"Хеш добавлен в слот {req.slot}"}


@router.post("/vk/hashes/create")
async def create_vk_hash_slot(
    req: VkHashSlotRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Create hash via calls.create for a slot (uses VK Android auth)."""
    from ai.vk_manager import VkManager
    manager = VkManager(db)
    try:
        hash_val, msg = await manager.create_hash_for_slot(req.slot)
        if not hash_val:
            raise HTTPException(status_code=400, detail=msg)
        try:
            from app.services.vk_config_publisher import publish_all_configs
            await publish_all_configs(db)
        except Exception:
            pass
        return {"success": True, "slot": req.slot, "hash": hash_val, "message": msg}
    finally:
        await manager.close()


@router.post("/vk/recreate")
async def recreate_vk_hashes(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger VK hash recreation."""
    from ai.vk_manager import VkManager
    manager = VkManager(db)
    try:
        success, message = await manager.recreate_all_hashes()
        return {"success": success, "message": message}
    finally:
        await manager.close()


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
