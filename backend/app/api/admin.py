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
from ai.vk_manager import VkManager
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


@router.get("/vk/credentials")
async def get_vk_credentials(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Return saved VK login (no password for security)."""
    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()
    if not creds or not creds.is_configured:
        return {"login": "", "configured": False}
    try:
        login = decrypt_value(creds.login_enc)
    except Exception:
        login = ""
    return {"login": login, "configured": True}


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
    return {"message": "VK credentials сохранены успешно"}


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


@router.post("/vk/hashes/add")
async def add_vk_hash(
    data: dict,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Manually add a VK call hash."""
    hash_val = data.get("hash", "").strip()
    if not hash_val or len(hash_val) < 4:
        return {"success": False, "message": "Хеш слишком короткий"}

    result = await db.execute(select(VkHash).order_by(VkHash.slot_index))
    existing = result.scalars().all()
    if len(existing) >= 3:
        return {"success": False, "message": "Максимум 3 хеша. Удали один перед добавлением."}

    # Find next free slot
    used_slots = {h.slot_index for h in existing}
    slot = next(i for i in range(3) if i not in used_slots)

    db.add(VkHash(hash_value=hash_val, slot_index=slot, is_active=True, fail_count=0))
    await db.commit()
    return {"success": True, "message": f"Хеш добавлен в слот {slot}"}


@router.delete("/vk/hashes/{hash_id}")
async def delete_vk_hash(
    hash_id: str,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Delete a VK call hash."""
    import uuid as _uuid
    try:
        uid = _uuid.UUID(hash_id)
        result = await db.execute(select(VkHash).where(VkHash.id == uid))
    except Exception:
        return {"success": False, "message": "Неверный ID"}

    h = result.scalar_one_or_none()
    if not h:
        return {"success": False, "message": "Хеш не найден"}
    await db.delete(h)
    await db.commit()
    return {"success": True}


@router.get("/vk/oauth-url")
async def vk_oauth_url(
    _: bool = Depends(get_admin_credentials),
):
    """Generate VK OAuth authorization URL. User opens it in browser, logs in, gets redirected back."""
    import urllib.parse
    from app.config import settings

    client_id = 54608093
    # blank.html is always allowed as redirect for any VK app
    redirect_uri = "https://oauth.vk.com/blank.html"
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "calls",
        "response_type": "token",
        "v": "5.131",
        "display": "page",
    })
    url = f"https://oauth.vk.com/authorize?{params}"
    return {"url": url}


@router.get("/vk/oauth-callback")
async def vk_oauth_callback(
    code: str = None,
    error: str = None,
    error_description: str = None,
    db: AsyncSession = Depends(get_db),
):
    """VK OAuth callback — exchanges code for token and saves it."""
    import aiohttp
    from app.config import settings

    if error:
        html = f"""<!DOCTYPE html><html><body style="background:#0a0a0a;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
        <div style="text-align:center"><h2 style="color:#ef4444">Ошибка авторизации</h2><p>{error_description or error}</p>
        <p style="color:#555">Закройте это окно и попробуйте снова.</p></div></body></html>"""
        from fastapi.responses import HTMLResponse
        return HTMLResponse(html)

    if not code:
        from fastapi.responses import HTMLResponse
        return HTMLResponse('<html><body style="background:#0a0a0a;color:#fff">Код не получен</body></html>')

    # Exchange code for token
    client_id = 54608093
    client_secret = "wxj4liNXn7nElGP5DDgz"
    redirect_uri = "https://132-243-234-162.nip.io/api/admin/vk/oauth-callback"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://oauth.vk.com/access_token",
                params={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json(content_type=None)

        if "access_token" in data:
            token = data["access_token"]
            # Save token to DB
            result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
            creds = result.scalar_one_or_none()
            if creds:
                creds.access_token = token
                creds.is_configured = True
            else:
                from app.core.security import encrypt_value
                db.add(VkCredentials(id=1, access_token=token, is_configured=True))
            await db.commit()

            from fastapi.responses import HTMLResponse
            html = """<!DOCTYPE html><html><body style="background:#0a0a0a;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
            <div style="text-align:center">
            <div style="font-size:48px;margin-bottom:16px">✅</div>
            <h2 style="color:#22c55e;margin:0 0 8px">Авторизация успешна!</h2>
            <p style="color:#888">Токен VK сохранён. Закройте это окно и нажмите «Пересоздать все».</p>
            <script>setTimeout(()=>window.close(),3000)</script>
            </div></body></html>"""
            return HTMLResponse(html)

        err = data.get("error_description", str(data))
        from fastapi.responses import HTMLResponse
        html = f"""<!DOCTYPE html><html><body style="background:#0a0a0a;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
        <div style="text-align:center"><h2 style="color:#ef4444">Ошибка получения токена</h2><p>{err}</p></div></body></html>"""
        return HTMLResponse(html)

    except Exception as e:
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f'<html><body style="background:#0a0a0a;color:#fff">Исключение: {e}</body></html>')


async def _save_vk_token_to_db(db: AsyncSession, login: str, token: str):
    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()
    if creds:
        creds.login = login
        creds.access_token = token
        creds.is_configured = True
    else:
        db.add(VkCredentials(id=1, login=login, access_token=token, is_configured=True))
    await db.commit()


@router.post("/vk/auth-server")
async def vk_auth_from_server(
    data: dict,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Start VK auth from server. Returns success, need_2fa, or error."""
    login = data.get("login", "").strip()
    password = data.get("password", "").strip()
    if not login or not password:
        return {"success": False, "message": "Введите логин и пароль VK"}

    res = await VkManager.direct_auth(login, password)

    if res.get("need_2fa"):
        return res  # {need_2fa: True, session_id: ..., message: ...}

    if res.get("success") and res.get("token"):
        await _save_vk_token_to_db(db, login, res["token"])
        return {"success": True, "message": "Авторизация прошла успешно! Токен привязан к серверу."}

    return {"success": False, "message": res.get("message", "Ошибка авторизации")}


@router.post("/vk/exchange-code")
async def vk_exchange_code(
    data: dict,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Exchange VK OAuth code for token server-side (token bound to server IP)."""
    import aiohttp as _aiohttp
    code = data.get("code", "").strip()
    if not code:
        return {"success": False, "message": "Не передан code"}

    client_id = 54608093
    client_secret = "wxj4liNXn7nElGP5DDgz"
    redirect_uri = f"https://vk.com/app{client_id}"

    async with _aiohttp.ClientSession() as session:
        async with session.get(
            "https://oauth.vk.com/access_token",
            params={"client_id": client_id, "client_secret": client_secret,
                    "redirect_uri": redirect_uri, "code": code},
            timeout=_aiohttp.ClientTimeout(total=15),
        ) as resp:
            result = await resp.json(content_type=None)

    if "access_token" in result:
        token = result["access_token"]
        await _save_vk_token_to_db(db, "", token)
        return {"success": True, "message": "Токен получен и привязан к серверу!"}

    err = result.get("error_description") or result.get("error") or str(result)
    return {"success": False, "message": f"Ошибка обмена кода: {err}"}


@router.post("/vk/auth-2fa")
async def vk_auth_2fa(
    data: dict,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Provide 2FA code for a pending auth session."""
    session_id = data.get("session_id", "").strip()
    code = data.get("code", "").strip()
    login = data.get("login", "").strip()
    if not session_id or not code:
        return {"success": False, "message": "Не указан session_id или код"}

    res = await VkManager.submit_2fa_code(session_id, code)

    if res.get("success") and res.get("token"):
        await _save_vk_token_to_db(db, login, res["token"])
        return {"success": True, "message": "Авторизация с 2FA прошла успешно!"}

    return {"success": False, "message": res.get("message", "Ошибка 2FA")}


@router.post("/vk/save-token")
async def save_vk_token(
    data: dict,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Save VK access token from browser (no server-side IP validation)."""
    token = data.get("token", "").strip()
    if not token or len(token) < 20:
        return {"success": False, "message": "Токен слишком короткий или пустой"}

    # Save directly — validation from server fails for browser tokens due to IP binding
    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()
    if creds:
        creds.access_token = token
        creds.is_configured = True
    else:
        db.add(VkCredentials(id=1, access_token=token, is_configured=True))
    await db.commit()
    return {"success": True, "message": "Токен сохранён! Нажмите «Пересоздать все» для проверки."}


@router.get("/vk/oauth-status")
async def vk_oauth_status(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Check if VK OAuth token is saved."""
    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()
    has_token = bool(creds and creds.access_token)
    return {"authorized": has_token, "configured": bool(creds and creds.is_configured)}


@router.post("/vk/test-auth")
async def test_vk_auth(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Test VK authentication with saved credentials."""
    from ai.vk_manager import VkManager
    manager = VkManager(db)
    try:
        ok = await manager.authenticate()
        await manager.close()
        if ok:
            return {"success": True, "message": "Авторизация VK прошла успешно"}
        return {"success": False, "message": f"Ошибка авторизации: {manager.last_error}"}
    except Exception as e:
        return {"success": False, "message": f"Исключение: {e}"}


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
        await manager.close()
        return {"success": success, "message": message}
    except Exception as e:
        return {"success": False, "message": f"Исключение при пересоздании: {e}"}


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


@router.get("/logs")
async def get_api_logs(_: bool = Depends(get_admin_credentials)):
    """Last 500 in-memory log entries."""
    from app.log_buffer import get_logs
    return {"logs": get_logs()}


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
