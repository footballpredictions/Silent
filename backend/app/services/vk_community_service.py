"""VK Community API — send messages from the Silent group."""
import logging
import random
import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)
VK_API = "https://api.vk.com/method"
API_VERSION = "5.199"


class VkCommunityService:
    def __init__(self):
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def send_message(self, user_id: int, text: str) -> bool:
        if not settings.VK_COMMUNITY_TOKEN:
            logger.warning("VK_COMMUNITY_TOKEN not configured, skip send")
            return False

        session = await self._get_session()
        params = {
            "user_id": user_id,
            "random_id": random.randint(1, 2_000_000_000),
            "message": text,
            "access_token": settings.VK_COMMUNITY_TOKEN,
            "v": API_VERSION,
        }
        try:
            async with session.post(f"{VK_API}/messages.send", data=params) as resp:
                data = await resp.json()
                if "error" in data:
                    logger.error("VK messages.send error: %s", data["error"])
                    return False
                logger.info("VK message sent to user %s, msg_id=%s", user_id, data.get("response"))
                return True
        except Exception as e:
            logger.error("VK messages.send failed: %s", e)
            return False

    async def get_dialog_messages(self, user_id: int, count: int = 30) -> list[dict]:
        if not settings.VK_COMMUNITY_TOKEN:
            return []

        session = await self._get_session()
        params = {
            "peer_id": user_id,
            "count": count,
            "rev": 0,
            "access_token": settings.VK_COMMUNITY_TOKEN,
            "v": API_VERSION,
        }
        try:
            async with session.get(f"{VK_API}/messages.getHistory", params=params) as resp:
                data = await resp.json()
                if "error" in data:
                    logger.error("VK messages.getHistory error: %s", data["error"])
                    return []
                return data.get("response", {}).get("items", [])
        except Exception as e:
            logger.error("VK messages.getHistory failed: %s", e)
            return []


vk_community = VkCommunityService()
