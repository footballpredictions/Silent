"""Push encrypted VPN configs to linked VK users via community messages."""
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import User, Device, Subscription
from app.services.vpn_service import _build_vpn_config
from app.services.vk_config_crypto import encrypt_config_payload, BOOTSTRAP_PREFIX
from app.services.vk_community_service import vk_community
from app.config import settings

logger = logging.getLogger(__name__)


async def _user_has_active_subscription(db: AsyncSession, user_id) -> bool:
    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id, Subscription.status == "active")
        .order_by(Subscription.expires_at.desc())
    )
    sub = result.scalars().first()
    return bool(sub and sub.is_active)


async def _get_latest_device(db: AsyncSession, user_id) -> Device | None:
    result = await db.execute(
        select(Device)
        .where(Device.user_id == user_id, Device.is_active == True)
        .order_by(Device.last_connected.desc().nullslast(), Device.created_at.desc())
    )
    return result.scalars().first()


async def publish_config_for_user(db: AsyncSession, user: User) -> bool:
    if not user.vk_user_id:
        return False
    if not settings.VK_COMMUNITY_TOKEN:
        return False
    if not await _user_has_active_subscription(db, user.id):
        return False

    device = await _get_latest_device(db, user.id)
    if not device:
        logger.debug("No device for user %s, skip VK publish", user.id)
        return False

    config = await _build_vpn_config(db, device)
    payload = {
        "v": 1,
        "ts": int(datetime.utcnow().timestamp()),
        "fingerprint": device.device_fingerprint,
        "device_id": str(device.id),
        "wg_private_key": config.wg_private_key,
        "wg_address": config.wg_address,
        "wg_dns": config.wg_dns,
        "server_ip": config.server_ip,
        "server_port": config.server_port,
        "server_public_key": config.server_public_key,
        "wdtt_password": config.wdtt_password,
        "vk_hashes": config.vk_hashes,
        "stream_count": config.stream_count,
    }
    message = encrypt_config_payload(user.vk_user_id, payload)
    primary_hash = config.vk_hashes[0] if config.vk_hashes else ""
    boot_line = f"{BOOTSTRAP_PREFIX}{primary_hash}" if primary_hash else ""
    text = (
        "Silent VPN — первый хеш для подключения к серверу:\n"
        f"{boot_line}\n\n"
        "Полный конфиг (офлайн):\n"
        f"{message}"
    )
    ok = await vk_community.send_message(user.vk_user_id, text)
    if ok:
        user.vk_config_published_at = datetime.utcnow()
        await db.commit()
    return ok


async def publish_all_configs(db: AsyncSession) -> int:
    if not settings.VK_COMMUNITY_TOKEN:
        logger.warning("VK community token missing, skip bulk publish")
        return 0

    result = await db.execute(
        select(User).where(User.vk_user_id.isnot(None), User.is_active == True)
    )
    users = result.scalars().all()
    sent = 0
    for user in users:
        try:
            if await publish_config_for_user(db, user):
                sent += 1
        except Exception as e:
            logger.error("VK publish failed for user %s: %s", user.id, e)
    logger.info("VK config published to %s/%s linked users", sent, len(users))
    return sent
