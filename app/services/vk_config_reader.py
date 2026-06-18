"""Read encrypted VPN config from VK dialog via community token."""
import logging
import uuid
from datetime import datetime

from app.services.vk_community_service import vk_community
from app.services.vk_config_crypto import decrypt_config_payload, CONFIG_PREFIX, BOOTSTRAP_PREFIX
from app.schemas.vpn import VpnConfigResponse

logger = logging.getLogger(__name__)
CONFIG_MAX_AGE_SEC = 3600


def extract_bootstrap_hash(text: str) -> str | None:
    idx = text.find(BOOTSTRAP_PREFIX)
    if idx < 0:
        return None
    rest = text[idx + len(BOOTSTRAP_PREFIX):]
    end = next((i for i, c in enumerate(rest) if c.isspace()), len(rest))
    val = rest[:end].strip()
    return val or None


async def fetch_bootstrap_hash_from_vk_messages(vk_user_id: int) -> str | None:
    items = await vk_community.get_dialog_messages(vk_user_id, count=15)
    now = int(datetime.utcnow().timestamp())
    best_ts = 0
    best_hash: str | None = None
    for item in items:
        from_id = item.get("from_id", 0)
        if from_id > 0:
            continue
        ts = item.get("date", 0)
        if now - ts > CONFIG_MAX_AGE_SEC:
            continue
        h = extract_bootstrap_hash(item.get("text", ""))
        if h and ts >= best_ts:
            best_ts = ts
            best_hash = h
    return best_hash


async def fetch_config_from_vk_messages(vk_user_id: int) -> VpnConfigResponse | None:
    items = await vk_community.get_dialog_messages(vk_user_id, count=30)
    best_payload: dict | None = None
    best_ts = 0

    now = int(datetime.utcnow().timestamp())
    for item in items:
        from_id = item.get("from_id", 0)
        if from_id > 0:
            continue
        text = item.get("text", "")
        if not text.startswith(CONFIG_PREFIX):
            continue
        ts = item.get("date", 0)
        if now - ts > CONFIG_MAX_AGE_SEC:
            continue
        payload = decrypt_config_payload(vk_user_id, text)
        if not payload or not payload.get("vk_hashes"):
            continue
        if ts >= best_ts:
            best_ts = ts
            best_payload = payload

    if not best_payload:
        return None

    try:
        return VpnConfigResponse(
            device_id=uuid.UUID(best_payload["device_id"]),
            wg_private_key=best_payload["wg_private_key"],
            wg_address=best_payload["wg_address"],
            wg_dns=best_payload["wg_dns"],
            server_ip=best_payload["server_ip"],
            server_port=int(best_payload["server_port"]),
            server_public_key=best_payload["server_public_key"],
            wdtt_password=best_payload["wdtt_password"],
            vk_hashes=best_payload["vk_hashes"],
            stream_count=int(best_payload.get("stream_count", 3)),
        )
    except (KeyError, ValueError, TypeError) as e:
        logger.warning("Invalid VK config payload for vk_user_id=%s: %s", vk_user_id, e)
        return None
