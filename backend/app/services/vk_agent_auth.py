"""VK agent auth — Android client OAuth (same as proxy-turn-vk-android)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import VkCredentials
from app.core.security import encrypt_value, decrypt_value

logger = logging.getLogger(__name__)

VK_API_VERSION = "5.199"
VK_USER_AGENT = (
    "VKAndroidApp/8.10-17765 (Android 14; SDK 34; arm64-v8a; Google Pixel 8; ru; 2560x1080)"
)

# Official / widely used Android client IDs with secrets (for password grant)
VK_ANDROID_CLIENTS = [
    {"id": 6287487, "secret": "VeWdmVclDCtn6ihuP1nt"},
    {"id": 2274003, "secret": "hHbZxrka2uZ6jB1inYsH"},
    {"id": 2685278, "secret": "lxhD8OD7dMsqtXIm5IUY"},
    {"id": 8202606, "secret": ""},
]

# Browser token capture URL (Android client, offline scope for long-lived token)
def build_token_capture_url() -> str:
    return (
        "https://oauth.vk.com/authorize?client_id=6287487"
        "&display=page&redirect_uri=https://oauth.vk.com/blank.html"
        "&scope=offline,photos,audio,video,docs,notes,pages,status,wall,groups,messages"
        "&response_type=token&v=5.199"
    )


async def _api_get(method: str, token: str, extra: dict | None = None) -> dict:
    params = {"access_token": token, "v": VK_API_VERSION}
    if extra:
        params.update(extra)
    async with aiohttp.ClientSession(
        headers={"User-Agent": VK_USER_AGENT},
        timeout=aiohttp.ClientTimeout(total=20),
    ) as session:
        async with session.get(f"https://api.vk.com/method/{method}", params=params) as resp:
            return await resp.json(content_type=None)


async def validate_token(token: str) -> tuple[bool, str, int | None]:
    """Returns (ok, message, vk_user_id)."""
    if not token or len(token) < 20:
        return False, "Токен пустой или слишком короткий", None
    try:
        data = await _api_get("users.get", token)
        if "error" in data:
            err = data["error"]
            return False, err.get("error_msg", "VK API error"), None
        users = data.get("response", [])
        if not users:
            return False, "users.get вернул пустой ответ", None
        uid = users[0].get("id")
        return True, f"OK, user_id={uid}", uid
    except Exception as e:
        return False, str(e), None


async def password_login(login: str, password: str) -> tuple[str | None, str]:
    """Password grant via Android client_id + secret."""
    async with aiohttp.ClientSession(
        headers={"User-Agent": VK_USER_AGENT},
        timeout=aiohttp.ClientTimeout(total=30),
    ) as session:
        last_err = "Не удалось авторизоваться"
        for client in VK_ANDROID_CLIENTS:
            try:
                payload = {
                    "grant_type": "password",
                    "client_id": str(client["id"]),
                    "username": login,
                    "password": password,
                    "scope": "offline",
                    "v": VK_API_VERSION,
                }
                if client["secret"]:
                    payload["client_secret"] = client["secret"]
                async with session.post("https://oauth.vk.com/token", data=payload) as resp:
                    data = await resp.json(content_type=None)
                if "access_token" in data:
                    logger.info("VK password auth OK with client_id=%s", client["id"])
                    return data["access_token"], f"Авторизация через client_id {client['id']}"
                last_err = data.get("error_description") or data.get("error", last_err)
                logger.warning("VK auth client_id=%s: %s", client["id"], last_err)
            except Exception as e:
                last_err = str(e)
                logger.error("VK auth client_id=%s exception: %s", client["id"], e)
    return None, last_err


async def load_stored_token(db: AsyncSession) -> str | None:
    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()
    if not creds or not creds.access_token:
        return None
    try:
        token = decrypt_value(creds.access_token)
        if creds.token_expires and creds.token_expires < datetime.utcnow():
            logger.warning("Stored VK token expired at %s", creds.token_expires)
            return None
        return token
    except Exception as e:
        logger.error("Failed to decrypt VK token: %s", e)
        return None


async def save_stored_token(db: AsyncSession, token: str, expires_in: int | None = None) -> None:
    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()
    enc = encrypt_value(token)
    expires = None
    if expires_in:
        expires = datetime.utcnow() + timedelta(seconds=int(expires_in))
    if creds:
        creds.access_token = enc
        creds.token_expires = expires
        creds.is_configured = True
    else:
        db.add(VkCredentials(
            id=1,
            access_token=enc,
            token_expires=expires,
            is_configured=True,
        ))
    await db.commit()


async def resolve_agent_token(db: AsyncSession) -> tuple[str | None, str]:
    """
    Token for AI agent: stored token → password login → error.
    Saves token on successful password login.
    """
    stored = await load_stored_token(db)
    if stored:
        ok, msg, _ = await validate_token(stored)
        if ok:
            return stored, msg
        logger.warning("Stored VK token invalid: %s", msg)

    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()
    if creds and creds.login_enc and creds.password_enc:
        try:
            login = decrypt_value(creds.login_enc)
            password = decrypt_value(creds.password_enc)
            token, msg = await password_login(login, password)
            if token:
                await save_stored_token(db, token)
                return token, msg
            return None, msg
        except Exception as e:
            return None, str(e)

    from app.config import settings
    if settings.VK_LOGIN and settings.VK_PASSWORD:
        token, msg = await password_login(settings.VK_LOGIN, settings.VK_PASSWORD)
        if token:
            await save_stored_token(db, token)
            return token, msg

    return None, "Сначала нажмите «Войти через VK» в панели админа."


async def test_calls_permission(token: str) -> tuple[bool, str]:
    """Check if token can create VK calls (creates one test call)."""
    try:
        async with aiohttp.ClientSession(
            headers={"User-Agent": VK_USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as session:
            async with session.post(
                "https://api.vk.com/method/calls.create",
                data={"access_token": token, "v": VK_API_VERSION},
            ) as resp:
                data = await resp.json(content_type=None)
        if "error" in data:
            err = data["error"]
            return False, err.get("error_msg", "calls.create denied")
        join = data.get("response", {}).get("join_link", "")
        if join:
            return True, "OK"
        return False, "calls.create без join_link"
    except Exception as e:
        return False, str(e)


async def _setting(db: AsyncSession, key: str) -> str | None:
    from app.models import AppSetting
    r = await db.execute(select(AppSetting).where(AppSetting.key == key))
    s = r.scalar_one_or_none()
    return s.value if s else None


async def _set_setting(db: AsyncSession, key: str, value: str) -> None:
    from app.models import AppSetting
    r = await db.execute(select(AppSetting).where(AppSetting.key == key))
    s = r.scalar_one_or_none()
    if s:
        s.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    await db.commit()


async def set_calls_verified(db: AsyncSession, ok: bool) -> None:
    await _set_setting(db, "vk_agent_calls_ok", "true" if ok else "false")


async def get_calls_verified(db: AsyncSession) -> bool:
    return (await _setting(db, "vk_agent_calls_ok")) == "true"


async def is_agent_enabled(db: AsyncSession) -> bool:
    from app.models import AppSetting
    result = await db.execute(select(AppSetting).where(AppSetting.key == "vk_agent_enabled"))
    s = result.scalar_one_or_none()
    return s is not None and s.value == "true"


async def set_agent_enabled(db: AsyncSession, enabled: bool) -> None:
    from app.models import AppSetting
    key = "vk_agent_enabled"
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    s = result.scalar_one_or_none()
    if s:
        s.value = "true" if enabled else "false"
    else:
        db.add(AppSetting(key=key, value="true" if enabled else "false"))
    await db.commit()


async def get_auth_status(db: AsyncSession) -> dict:
    from app.config import settings

    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()
    has_token = bool(creds and creds.access_token)

    auth_ok = False
    auth_error: str | None = None
    vk_user_id: int | None = None
    calls_ok = False

    token, msg = await resolve_agent_token(db)
    if token:
        ok, detail, uid = await validate_token(token)
        auth_ok = ok
        vk_user_id = uid
        if ok:
            calls_ok = await get_calls_verified(db)
            if not calls_ok:
                auth_error = "Аккаунт привязан, но звонки не проверены — войдите через VK снова"
        else:
            auth_error = detail
    else:
        auth_error = msg

    agent_on = await is_agent_enabled(db)

    return {
        "bot_url": settings.VK_BOT_WRITE_URL or f"https://vk.com/write-{settings.VK_GROUP_ID}",
        "group_id": settings.VK_GROUP_ID,
        "vk_linked": auth_ok,
        "calls_ok": calls_ok,
        "auth_error": auth_error,
        "vk_user_id": vk_user_id,
        "agent_connected": agent_on and auth_ok and calls_ok,
        "agent_enabled": agent_on,
        "has_token": has_token,
    }
