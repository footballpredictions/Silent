"""Test VK API access with user token."""
import logging
import aiohttp

logger = logging.getLogger(__name__)
API = "https://api.vk.com/method"
VERSION = "5.199"


async def test_messages_access(access_token: str, group_id: int) -> tuple[bool, str]:
    peer_id = -abs(group_id)
    params = {
        "peer_id": peer_id,
        "count": 5,
        "access_token": access_token,
        "v": VERSION,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API}/messages.getHistory", params=params) as resp:
                data = await resp.json()
        if "error" in data:
            msg = data["error"].get("error_msg", "unknown")
            logger.info("messages.getHistory denied: %s", msg)
            return False, msg
        items = data.get("response", {}).get("items", [])
        return True, f"ok:{len(items)}"
    except Exception as e:
        return False, str(e)
