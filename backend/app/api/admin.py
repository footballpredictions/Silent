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
from app.models import User, Subscription, Device, VkHash, AppSetting, PromoCode
from app.core.deps import get_admin_credentials
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


# ─── VK: bot auth → AI agent → manual hashes ─────────────────────────────────

class VkHashManualRequest(BaseModel):
    hash: str
    slot: int


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
    status["max_hashes"] = MAX_HASHES
    return status


@router.post("/vk/bot-auth/start")
async def vk_bot_auth_start(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.config import settings
    from app.services.vk_id_service import generate_pkce, build_authorize_url
    from app.models import VkLinkSession
    import secrets
    from datetime import timedelta

    if not settings.VK_ID_APP_ID:
        raise HTTPException(status_code=503, detail="VK ID не настроен на сервере")

    code_verifier, code_challenge = generate_pkce()
    state = secrets.token_urlsafe(32)
    db.add(VkLinkSession(
        state=state,
        user_id=None,
        code_verifier=code_verifier,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
        purpose="agent",
    ))
    await db.commit()
    bot_url = settings.VK_BOT_WRITE_URL or f"https://vk.com/write-{settings.VK_GROUP_ID}"
    return {
        "auth_url": build_authorize_url(state, code_challenge),
        "state": state,
        "bot_url": bot_url,
    }


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
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.vk_agent_auth import get_auth_status, set_agent_enabled, set_calls_verified
    from ai.vk_manager import VkManager

    status = await get_auth_status(db)
    if not status.get("vk_linked"):
        raise HTTPException(status_code=400, detail=status.get("auth_error") or "Сначала войдите через VK")
    if not status.get("calls_ok"):
        raise HTTPException(status_code=400, detail="VK не может создавать звонки — авторизуйтесь снова")

    manager = VkManager(db)
    try:
        active = (await db.execute(
            select(func.count(VkHash.id)).where(VkHash.is_active == True)
        )).scalar_one()
        if active < 3:
            success, message = await manager.recreate_all_hashes()
            if not success:
                raise HTTPException(status_code=400, detail=message)
        else:
            await manager.check_and_heal()
            message = "Агент подключён, хеши проверены"
        await set_agent_enabled(db, True)
        await set_calls_verified(db, True)
        return {"success": True, "message": message, "agent_connected": True}
    finally:
        await manager.close()


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


@router.delete("/vk/hashes/{slot}")
async def delete_vk_hash_slot(
    slot: int,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from ai.vk_manager import MAX_HASHES
    if slot < 0 or slot >= MAX_HASHES:
        raise HTTPException(status_code=400, detail=f"Слот 0–{MAX_HASHES - 1}")
    result = await db.execute(select(VkHash).where(VkHash.slot_index == slot))
    h = result.scalar_one_or_none()
    if h:
        h.is_active = False
        await db.commit()
    return {"success": True, "message": f"Слот {slot} очищен"}


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
