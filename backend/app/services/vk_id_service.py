"""VK ID OAuth 2.1 — PKCE link flow."""
import base64
import hashlib
import json
import logging
import secrets
from urllib.parse import urlencode

import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)

VK_ID_AUTHORIZE = "https://id.vk.ru/authorize"
VK_ID_TOKEN = "https://id.vk.ru/oauth2/auth"


def generate_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)[:128]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_authorize_url(state: str, code_challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.VK_ID_APP_ID,
        "redirect_uri": settings.VK_ID_REDIRECT_URI,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "scope": "vkid.personal_info",
    }
    return f"{VK_ID_AUTHORIZE}?{urlencode(params)}"


async def exchange_code(
    code: str,
    code_verifier: str,
    device_id: str,
    state: str,
) -> dict | None:
    if not settings.VK_ID_APP_ID:
        logger.error("VK_ID_APP_ID not configured")
        return None

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "redirect_uri": settings.VK_ID_REDIRECT_URI,
        "client_id": str(settings.VK_ID_APP_ID),
        "device_id": device_id,
        "state": state,
    }
    if settings.VK_ID_CLIENT_SECRET:
        data["client_secret"] = settings.VK_ID_CLIENT_SECRET

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(VK_ID_TOKEN, data=data) as resp:
                text = await resp.text()
                if not text.strip():
                    logger.error("VK ID token empty response HTTP %s", resp.status)
                    return None
                try:
                    result = json.loads(text)
                except json.JSONDecodeError:
                    logger.error("VK ID token non-JSON HTTP %s: %s", resp.status, text[:200])
                    return None
                if "error" in result:
                    logger.error("VK ID token error: %s", result)
                    return None
                return result
    except Exception as e:
        logger.error("VK ID token exchange failed: %s", e)
        return None
