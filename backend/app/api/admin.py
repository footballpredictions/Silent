"""Admin API — dashboard, user management, VK credentials, system stats."""
import json
import os
import psutil
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, case
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models import User, Subscription, Device, VkHash, AppSetting, PromoCode, Payment, VkLinkSession
from app.core.deps import get_admin_credentials
from app.config import settings
from app.schemas.vpn import ThemeResponse
from app.services.theme_settings import load_theme

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

    # VK hashes — only active per-user slots (no legacy global / dead slots)
    hashes_result = await db.execute(
        select(VkHash)
        .where(VkHash.is_active == True, VkHash.user_id.isnot(None))
        .order_by(VkHash.user_id, VkHash.slot_index)
    )
    hashes = hashes_result.scalars().all()
    user_emails: dict = {}
    user_online: dict = {}
    for h in hashes:
        if h.user_id and h.user_id not in user_emails:
            u = await db.get(User, h.user_id)
            user_emails[h.user_id] = u.email if u else "?"
            dev_online = (await db.execute(
                select(func.count(Device.id))
                .where(Device.user_id == h.user_id, Device.is_connected == True)
            )).scalar_one()
            user_online[h.user_id] = dev_online > 0

    real_users = (await db.execute(
        select(func.count(User.id)).where(User.email != "__bootstrap__@silent.local")
    )).scalar_one()

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
            "total": real_users,
            "active_subscriptions": active_subs,
            "connected_devices": connected_devices,
        },
        "vk_hashes": [
            {
                "slot": h.slot_index,
                "hash": h.hash_value,
                "user_id": str(h.user_id) if h.user_id else None,
                "user_email": user_emails.get(h.user_id, "?"),
                "user_connected": user_online.get(h.user_id, False),
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
    admin_email = settings.ADMIN_LOGIN.lower()
    result = await db.execute(
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
        .limit(limit)
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
        hash_count = (await db.execute(
            select(func.count(VkHash.id)).where(VkHash.user_id == user.id, VkHash.is_active == True)
        )).scalar_one()

        from app.services.subscription_service import is_user_admin
        admin = is_user_admin(user)

        out.append({
            "id": str(user.id),
            "display_id": user.display_id,
            "email": user.email,
            "is_verified": user.is_verified,
            "is_active": user.is_active,
            "is_admin": admin,
            "created_at": user.created_at,
            "bootstrap_hash": (user.bootstrap_hash[:12] + "...") if user.bootstrap_hash else None,
            "server_hashes": hash_count,
            "subscription": {
                "active": True if admin else (sub.is_active if sub else False),
                "plan": "unlimited" if admin else (sub.plan_type if sub else None),
                "expires_at": None if admin else (sub.expires_at if sub else None),
            },
            "devices_count": dev_count,
        })
    return out


class GrantSubscriptionRequest(BaseModel):
    plan_type: str


@router.post("/users/{user_id}/grant-subscription")
async def grant_user_subscription(
    user_id: str,
    req: GrantSubscriptionRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Ручная выдача подписки (three_days / monthly / quarterly / yearly / unlimited)."""
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
    from app.services.subscription_service import ensure_trial_subscription
    await ensure_trial_subscription(db, user)
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
    status["max_hashes"] = MAX_HASHES
    return status


@router.post("/vk/bot-auth/start")
async def vk_bot_auth_start(
    request: Request,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.config import settings
    from app.services.vk_agent_auth import build_agent_auth_url
    from app.models import VkLinkSession
    import secrets
    from datetime import timedelta

    base = str(request.base_url).rstrip("/")
    if "nip.io" in base and base.startswith("http://"):
        base = base.replace("http://", "https://", 1)

    code_verifier = secrets.token_urlsafe(32)
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
        "auth_url": build_agent_auth_url(state, base),
        "state": state,
        "bot_url": bot_url,
        "paste_hint": (
            "После входа VK откроется blank.html?code=... — скопируйте весь URL "
            "и вставьте ниже. Токен получит сервер (не вставляйте vk1.a с ПК — другой IP)."
        ),
    }


@router.post("/vk/bot-auth/paste")
async def vk_bot_auth_paste(
    req: VkOAuthPasteRequest,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить токен: code из URL → обмен на сервере (IP VPS)."""
    from app.services.vk_agent_auth import (
        parse_vk_oauth_paste,
        complete_agent_auth,
        save_agent_token_direct,
        paste_to_server_token,
    )

    token, expires_in, err = await paste_to_server_token(req.paste)
    if err:
        raise HTTPException(status_code=400, detail=err)
    if not token:
        raise HTTPException(status_code=400, detail="Не удалось получить token")

    _, _, state_from_url, _ = parse_vk_oauth_paste(req.paste)
    state = (state_from_url or req.state or "").strip()
    if state:
        ok, message, uid = await complete_agent_auth(db, state, token, expires_in)
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
        validate_token,
        test_calls_permission,
        set_calls_verified,
    )
    token, msg = await password_login(req.login.strip(), req.password)
    if not token:
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
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    from app.services.vk_agent_auth import get_auth_status, set_agent_enabled, set_calls_verified
    from ai.vk_manager import VkManager

    status = await get_auth_status(db)
    if not status.get("vk_linked"):
        raise HTTPException(status_code=400, detail=status.get("auth_error") or "Сначала войдите через VK")

    manager = VkManager(db)
    ok, err = await manager.ensure_authenticated()
    if not ok:
        raise HTTPException(status_code=400, detail=err or "VK не может создавать звонки")
    await set_calls_verified(db, True)

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
    return [
        {
            "id": str(h.id),
            "slot": h.slot_index,
            "hash": h.hash_value,
            "user_id": str(h.user_id) if h.user_id else None,
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
    await db.execute(delete(VkHash).where(VkHash.is_active == False))

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
