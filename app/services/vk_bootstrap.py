"""Send bootstrap VK hash to user via community bot (no Silent login required)."""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.vk_config_crypto import BOOTSTRAP_PREFIX
from app.services.vk_community_service import vk_community
from app.services.vpn_service import get_active_vk_hashes
from app.config import settings

logger = logging.getLogger(__name__)


async def publish_bootstrap_to_vk_user(db: AsyncSession, vk_user_id: int) -> tuple[bool, str | None]:
    """Auto-send first TURN hash to VK user after OAuth."""
    if not settings.VK_COMMUNITY_TOKEN:
        logger.warning("VK_COMMUNITY_TOKEN missing, skip bootstrap send")
        return False, None

    hashes = await get_active_vk_hashes(db)
    boot = hashes[0] if hashes else None
    if not boot:
        logger.warning("No VK hashes in DB for bootstrap message")
        return False, None

    text = (
        "Silent VPN — канал доставки конфигурации.\n"
        f"{BOOTSTRAP_PREFIX}{boot}"
    )
    ok = await vk_community.send_message(vk_user_id, text)
    if ok:
        logger.info("Bootstrap hash sent to vk_user_id=%s", vk_user_id)
    return ok, boot
