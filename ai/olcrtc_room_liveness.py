"""Проверка живости комнат Telemost / WB Stream (без Playwright).

WB: guest-register → join. 404 / «guests cannot create» → комната мертва.
Telemost: cloud-api connection. 404/410 или пустой room_id → мертва.
Сеть/5xx → unknown (не удаляем).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = httpx.Timeout(12.0, connect=6.0)


@dataclass
class RoomProbeResult:
    alive: bool | None  # True / False / None=unknown
    reason: str
    http_status: int = 0
    provider: str = ""
    room_id: str = ""

    @property
    def is_dead(self) -> bool:
        return self.alive is False

    @property
    def is_alive(self) -> bool:
        return self.alive is True


def _normalize_wb_id(room: str) -> str:
    r = (room or "").strip()
    for prefix in (
        "https://stream.wb.ru/room/",
        "http://stream.wb.ru/room/",
        "https://stream.wb.ru/",
    ):
        if r.startswith(prefix):
            r = r[len(prefix) :]
            break
    return r.strip("/")


def _normalize_tm_url(room: str) -> str:
    r = (room or "").strip()
    if r.startswith("https://") or r.startswith("http://"):
        return r
    return f"https://telemost.yandex.ru/j/{r}"


def _wb_body_means_dead(status: int, body: str) -> bool:
    low = (body or "").lower()
    if status in (404, 410, 422):
        return True
    if status == 403 and (
        "guests cannot create" in low
        or "cannot create rooms" in low
        or '"code":7' in low
        or '"code": 7' in low
    ):
        return True
    if "not found" in low and status >= 400:
        return True
    return False


async def probe_wbstream_room(room: str) -> RoomProbeResult:
    room_id = _normalize_wb_id(room)
    if not room_id:
        return RoomProbeResult(False, "empty room id", provider="wbstream")
    headers = {"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            reg = await client.post(
                "https://stream.wb.ru/auth/api/v1/auth/user/guest-register",
                headers=headers,
                json={
                    "displayName": "silent-liveness",
                    "device": {
                        "deviceName": "Linux",
                        "deviceType": "PARTICIPANT_DEVICE_TYPE_WEB_DESKTOP",
                    },
                },
            )
            if reg.status_code >= 400:
                return RoomProbeResult(
                    None,
                    f"guest-register {reg.status_code}",
                    reg.status_code,
                    "wbstream",
                    room_id,
                )
            token = ""
            try:
                token = str((reg.json() or {}).get("accessToken") or "")
            except Exception:
                token = ""
            if not token:
                return RoomProbeResult(
                    None, "guest-register: no accessToken", reg.status_code, "wbstream", room_id
                )

            join = await client.post(
                f"https://stream.wb.ru/api-room/api/v1/room/{room_id}/join",
                headers={**headers, "Authorization": f"Bearer {token}"},
                content=b"{}",
            )
            body = join.text or ""
            if join.status_code < 300:
                return RoomProbeResult(True, "join ok", join.status_code, "wbstream", room_id)
            if _wb_body_means_dead(join.status_code, body):
                return RoomProbeResult(
                    False,
                    f"join {join.status_code}: {body[:120]}",
                    join.status_code,
                    "wbstream",
                    room_id,
                )
            return RoomProbeResult(
                None,
                f"join {join.status_code}: {body[:120]}",
                join.status_code,
                "wbstream",
                room_id,
            )
    except Exception as e:
        logger.warning("wbstream probe %s failed: %s", room_id[:20], e)
        return RoomProbeResult(None, f"network: {e}"[:160], provider="wbstream", room_id=room_id)


async def probe_telemost_room(room: str) -> RoomProbeResult:
    room_url = _normalize_tm_url(room)
    room_id = room_url.rstrip("/").split("/")[-1]
    enc = quote(room_url, safe="")
    url = (
        f"https://cloud-api.yandex.ru/telemost_front/v2/telemost/conferences/{enc}/connection"
        f"?next_gen_media_platform_allowed=true"
        f"&display_name=silent-liveness"
        f"&waiting_room_supported=true"
    )
    headers = {
        "User-Agent": UA,
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Client-Instance-Id": str(uuid.uuid4()),
        "X-Telemost-Client-Version": "187.1.0",
        "Idempotency-Key": str(uuid.uuid4()),
        "Origin": "https://telemost.yandex.ru",
        "Referer": "https://telemost.yandex.ru/",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            body = resp.text or ""
            if resp.status_code in (404, 410, 422):
                return RoomProbeResult(
                    False,
                    f"connection {resp.status_code}",
                    resp.status_code,
                    "telemost",
                    room_id,
                )
            if resp.status_code >= 500:
                return RoomProbeResult(
                    None,
                    f"connection {resp.status_code}",
                    resp.status_code,
                    "telemost",
                    room_id,
                )
            if resp.status_code >= 400:
                low = body.lower()
                if "not found" in low or "не найден" in low or "expired" in low:
                    return RoomProbeResult(
                        False,
                        f"connection {resp.status_code}: {body[:100]}",
                        resp.status_code,
                        "telemost",
                        room_id,
                    )
                return RoomProbeResult(
                    None,
                    f"connection {resp.status_code}: {body[:100]}",
                    resp.status_code,
                    "telemost",
                    room_id,
                )
            try:
                data: dict[str, Any] = resp.json()
            except Exception:
                data = {}
            rid = str(data.get("room_id") or "")
            peer = str(data.get("peer_id") or "")
            media = ""
            cfg = data.get("client_configuration")
            if isinstance(cfg, dict):
                media = str(cfg.get("media_server_url") or "")
            if rid and peer and media:
                return RoomProbeResult(True, "connection ok", resp.status_code, "telemost", room_id)
            return RoomProbeResult(
                False,
                "connection: missing room_id/peer_id/media",
                resp.status_code,
                "telemost",
                room_id,
            )
    except Exception as e:
        logger.warning("telemost probe %s failed: %s", room_id[:20], e)
        return RoomProbeResult(None, f"network: {e}"[:160], provider="telemost", room_id=room_id)


async def probe_room(provider: str, room_url: str) -> RoomProbeResult:
    p = (provider or "").strip().lower()
    if p == "wbstream":
        return await probe_wbstream_room(room_url)
    if p == "telemost":
        return await probe_telemost_room(room_url)
    return RoomProbeResult(None, f"unsupported provider {p}", provider=p)
