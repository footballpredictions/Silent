"""Participant-only exit for newly created, unpublished VK calls."""
import asyncio
import json
import re
from urllib.parse import urlsplit
from uuid import uuid4

import aiohttp

from ai.vk_hash_liveness import JoinHashProber, KIND_ALIVE

CALLS_HOST = "https://calls.okcdn.ru"
CALLS_APP_KEY = "CGMMEJLGDIHBABABA"
PILOT_EMAIL_SETTING = "vk_issuer_leave_pilot_email"
LEAVE_NEW_CALLS_SETTING = "vk_issuer_leave_new_calls"


class VkRoomExitError(RuntimeError):
    pass


class VkRoomParticipant:
    def __init__(self, session, vk_request):
        self._session = session
        self._vk_request = vk_request
        self._session_key = None
        self._probe = JoinHashProber(session)

    async def _request(self, method: str, **fields):
        try:
            async with self._session.post(
                f"{CALLS_HOST}/fb.do",
                data={"method": method, "format": "JSON", "application_key": CALLS_APP_KEY, **fields},
                timeout=aiohttp.ClientTimeout(total=8),
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise VkRoomExitError(f"VK Calls {method}: HTTP {response.status}")
                text = await response.text()
                payload = json.loads(text) if text.strip() else {}
        except (aiohttp.ClientError, TimeoutError, ValueError):
            raise VkRoomExitError(f"VK Calls {method}: ошибка ответа") from None
        if isinstance(payload, dict) and payload.get("error_code"):
            raise VkRoomExitError(f"VK Calls {method}: отказ VK")
        return payload

    async def authorize(self):
        if self._session_key:
            return
        issued = await self._vk_request("messages.getCallToken", {"env": "production", "v": "5.203"})
        if (
            not isinstance(issued, dict)
            or str(issued.get("api_base_url", "")).rstrip("/") != CALLS_HOST
            or not issued.get("token")
        ):
            raise VkRoomExitError("VK не выдал токен звонков")
        authorized = await self._request("auth.anonymLogin", session_data=json.dumps({
            "version": 3,
            "device_id": str(uuid4()),
            "client_version": "2.8.12",
            "client_type": "SDK_JS",
            "auth_token": issued["token"],
        }))
        if not isinstance(authorized, dict) or not authorized.get("session_key"):
            raise VkRoomExitError("VK не выдал сессию участника")
        self._session_key = authorized["session_key"]

    async def leave(self, call_id: str, ok_link: str, vk_hash: str):
        ok_url = urlsplit(ok_link)
        join_code = ok_url.path.rstrip("/").rsplit("/", 1)[-1]
        if (
            not self._session_key
            or ok_url.query
            or ok_url.fragment
            or (bool(ok_url.netloc or ok_url.scheme) and (ok_url.scheme, ok_url.netloc) != ("https", "ok.ru"))
            or not re.fullmatch(r"[A-Za-z0-9_-]{6,128}", join_code)
        ):
            raise VkRoomExitError("VK не вернул данные для входа владельца")
        joined = await self._request(
            "vchat.joinConversationByLink",
            session_key=self._session_key,
            joinLink=join_code,
            isVideo="false",
            protocolVersion="5",
            capabilities="2F7F",
        )
        if not isinstance(joined, dict) or joined.get("id") != call_id:
            raise VkRoomExitError("VK вернул другой звонок при входе")
        await self._request(
            "vchat.hangupConversation",
            session_key=self._session_key,
            conversationId=call_id,
            reason="HUNGUP",
        )
        await asyncio.sleep(2)
        active = await self._vk_request("messages.getCurrentCalls", {"v": "5.203"})
        if not isinstance(active, dict) or not isinstance(active.get("items"), list):
            raise VkRoomExitError("VK не вернул список активных звонков")
        for item in active["items"]:
            call = item.get("active_call", item) if isinstance(item, dict) else {}
            if isinstance(call, dict) and call.get("call_id") == call_id:
                raise VkRoomExitError("Звонок остался в активных после выхода")
        if await self._probe.probe(vk_hash) != KIND_ALIVE:
            raise VkRoomExitError("VK не подтвердил ссылку после выхода")
