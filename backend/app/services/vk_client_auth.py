"""VK Android OAuth + calls.create helpers for client-side bootstrap."""
from __future__ import annotations

import logging
import re
from urllib.parse import urlencode

from app.services.vk_agent_auth import VK_ANDROID_CLIENT_ID, VK_API_VERSION, vk_api_call

logger = logging.getLogger(__name__)

VK_ANDROID_REDIRECT = "https://oauth.vk.com/blank.html"


def build_client_oauth_url(state: str) -> str:
    """Implicit token flow — token приходит на устройство пользователя (whitelist VK)."""
    params = {
        "client_id": str(VK_ANDROID_CLIENT_ID),
        "redirect_uri": VK_ANDROID_REDIRECT,
        "response_type": "code",
        "scope": "offline",
        "state": state,
        "display": "mobile",
        "revoke": "1",
    }
    return f"https://oauth.vk.ru/authorize?{urlencode(params)}"


def extract_call_hash(join_link: str) -> str | None:
    if not join_link:
        return None
    match = re.search(r"/join/([A-Za-z0-9_\-]+)", join_link)
    if match:
        return match.group(1)
    s = join_link.strip()
    if re.match(r"^[A-Za-z0-9_\-]{8,128}$", s):
        return s
    return None


def looks_like_vk_call_hash(h: str) -> bool:
    return bool(h and re.match(r"^[A-Za-z0-9_\-]{8,128}$", h.strip()))


async def vk_users_get_id(access_token: str) -> int | None:
    data = await vk_api_call("users.get", access_token)
    if "error" in data:
        logger.warning("users.get failed: %s", data.get("error"))
        return None
    resp = data.get("response") or []
    if not resp:
        return None
    try:
        return int(resp[0]["id"])
    except (KeyError, TypeError, ValueError):
        return None


async def vk_calls_start(access_token: str) -> tuple[str | None, str | None]:
    """Create group call, return (hash, join_link)."""
    data = await vk_api_call("calls.start", access_token)
    if "error" in data:
        err = data["error"]
        msg = err.get("error_msg", str(err))
        logger.warning("calls.start failed: %s", msg)
        return None, msg
    resp = data.get("response") or {}
    join_link = resp.get("join_link") or ""
    h = extract_call_hash(join_link)
    if not h:
        return None, "calls.start без join_link"
    return h, join_link


async def verify_token_matches_user(access_token: str, vk_user_id: int) -> bool:
    uid = await vk_users_get_id(access_token)
    return uid is not None and uid == vk_user_id
