"""WB Stream room create/delete через HTTP API (без Playwright).

С IP Улья браузерный stream.wb.ru часто даёт HTTP 498 (antibot), но
``POST /api-room/api/v1/room`` с Bearer JWT из storage_state проходит.

Enums (protobuf): roomType=1, roomPrivacy=1.
title → roomId (``-`` → ``_``); для уникальности — случайный title.
"""
from __future__ import annotations

import base64
import json
import logging
import uuid
from typing import Any

import httpx

from ai.olcrtc_room_provision import ProvisionResult

logger = logging.getLogger(__name__)

WB_API_BASE = "https://stream.wb.ru/api-room/api/v1"
WB_ORIGIN = "https://stream.wb.ru"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _owner_id_from_jwt(token: str) -> str:
    try:
        part = token.split(".")[1]
        pad = "=" * (-len(part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(part + pad))
        return str(payload.get("user") or "").strip()
    except Exception:
        return ""


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": WB_ORIGIN,
        "Referer": f"{WB_ORIGIN}/",
        "User-Agent": UA,
    }


async def create_wbstream_room_api(
    access_token: str,
    *,
    title: str | None = None,
) -> ProvisionResult:
    """Создать комнату WB через API. title опционален — иначе svpn-<hex>."""
    tok = (access_token or "").strip()
    if not tok.startswith("eyJ"):
        return ProvisionResult(
            ok=False, provider="wbstream", message="wb api: нет access_token"
        )
    owner = _owner_id_from_jwt(tok)
    if not owner:
        return ProvisionResult(
            ok=False, provider="wbstream", message="wb api: нет ownerId в JWT"
        )
    room_title = (title or "").strip() or f"svpn-{uuid.uuid4().hex[:12]}"
    body: dict[str, Any] = {
        "roomInfo": {
            "title": room_title,
            "isPublic": False,
            "ownerId": owner,
            "roomType": 1,
            "roomPrivacy": 1,
        }
    }
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            r = await client.post(
                f"{WB_API_BASE}/room",
                headers=_headers(tok),
                json=body,
            )
        text = (r.text or "")[:240]
        if r.status_code not in (200, 201):
            return ProvisionResult(
                ok=False,
                provider="wbstream",
                message=f"wb api create {r.status_code}: {text}",
            )
        data = r.json() if r.content else {}
        room_id = str((data or {}).get("roomId") or "").strip()
        if not room_id:
            return ProvisionResult(
                ok=False,
                provider="wbstream",
                message=f"wb api create: no roomId in {text}",
            )
        return ProvisionResult(
            ok=True,
            provider="wbstream",
            room_id=room_id,
            message="api",
        )
    except Exception as e:
        logger.warning("wb api create failed: %s", e)
        return ProvisionResult(
            ok=False, provider="wbstream", message=f"wb api create: {e}"[:300]
        )


async def delete_wbstream_room_api(access_token: str, room_id: str) -> bool:
    """Удалить комнату на стороне WB (DELETE /room/{id})."""
    tok = (access_token or "").strip()
    rid = (room_id or "").strip().rstrip("/").split("/")[-1]
    if not tok.startswith("eyJ") or not rid:
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            r = await client.delete(
                f"{WB_API_BASE}/room/{rid}",
                headers=_headers(tok),
            )
        if r.status_code < 300:
            return True
        logger.info("wb api delete %s -> %s %s", rid, r.status_code, (r.text or "")[:120])
        return False
    except Exception as e:
        logger.warning("wb api delete %s failed: %s", rid[:24], e)
        return False
