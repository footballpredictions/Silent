"""VPN configuration service — WireGuard key generation and WDTT password management."""
import base64
import ipaddress
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Device, User, VkHash, AppSetting
from app.core.security import generate_wdtt_password, encrypt_value
from app.config import settings
from app.schemas.vpn import VpnConfigResponse

logger = logging.getLogger(__name__)


def _clamp_wg_private(raw: bytes) -> bytes:
    key = bytearray(raw)
    key[0] &= 248
    key[31] &= 127
    key[31] |= 64
    return bytes(key)


def _generate_wg_keypair() -> tuple[str, str]:
    """WireGuard Curve25519 keypair (без wg binary — для Docker API)."""
    try:
        priv_raw = _clamp_wg_private(os.urandom(32))
        priv = X25519PrivateKey.from_private_bytes(priv_raw)
        pub_raw = priv.public_key().public_bytes_raw()
        return base64.b64encode(priv_raw).decode(), base64.b64encode(pub_raw).decode()
    except Exception as e:
        logger.error("WG keygen failed: %s", e)
        raise RuntimeError("Не удалось сгенерировать ключи WireGuard") from e


def _is_valid_wg_key(key: str) -> bool:
    if not key or len(key) < 40:
        return False
    if key == base64.b64encode(b"\x00" * 32).decode():
        return False
    return True


async def _get_next_wg_address(db: AsyncSession) -> str:
    subnet = ipaddress.IPv4Network(settings.WG_SUBNET)
    hosts = list(subnet.hosts())
    result = await db.execute(select(Device.wg_address).where(Device.wg_address.isnot(None)))
    used = {row[0] for row in result.fetchall()}
    for host in hosts[1:]:
        addr = f"{host}/{subnet.prefixlen}"
        if str(host) not in used and addr not in used:
            return addr
    raise RuntimeError("No available WireGuard addresses")


async def get_active_vk_hashes(db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(VkHash.hash_value)
        .where(VkHash.is_active == True)
        .order_by(VkHash.slot_index)
    )
    return [row[0] for row in result.fetchall()]


async def get_server_public_key(db: AsyncSession) -> str:
    env_key = (settings.WG_SERVER_PUBLIC_KEY or "").strip()
    if env_key:
        return env_key
    result = await db.execute(select(AppSetting).where(AppSetting.key == "server_public_key"))
    setting = result.scalar_one_or_none()
    return (setting.value or "").strip() if setting else ""


async def ensure_server_public_key(db: AsyncSession, key: str) -> None:
    key = key.strip()
    if not key:
        return
    result = await db.execute(select(AppSetting).where(AppSetting.key == "server_public_key"))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = key
    else:
        db.add(AppSetting(key="server_public_key", value=key))
    await db.commit()


async def clear_stale_online_status(db: AsyncSession) -> int:
    """Сброс «онлайн», если VPN давно не обновлялся (удалили приложение без logout)."""
    cutoff = datetime.utcnow() - timedelta(minutes=settings.SESSION_ONLINE_TIMEOUT_MINUTES)
    result = await db.execute(
        select(Device).where(
            Device.is_connected == True,
            Device.last_connected.isnot(None),
            Device.last_connected < cutoff,
        )
    )
    devices = result.scalars().all()
    for d in devices:
        d.is_connected = False
    if devices:
        await db.commit()
    return len(devices)


async def prune_old_sessions(db: AsyncSession, user_id) -> int:
    """Удалить старые сессии (переустановка без logout)."""
    cutoff = datetime.utcnow() - timedelta(days=settings.SESSION_MAX_AGE_DAYS)
    result = await db.execute(
        select(Device).where(
            Device.user_id == user_id,
            Device.is_connected == False,
            Device.created_at < cutoff,
        )
    )
    old = result.scalars().all()
    for d in old:
        await db.delete(d)
    if old:
        await db.commit()
    return len(old)


async def prune_oldest_session_if_full(db: AsyncSession, user_id) -> bool:
    """Если лимит 3 — удалить самую старую неподключённую сессию."""
    active_count = await count_active_sessions(db, user_id)
    if active_count < settings.MAX_DEVICES_PER_USER:
        return False
    result = await db.execute(
        select(Device)
        .where(Device.user_id == user_id, Device.is_active == True, Device.is_connected == False)
        .order_by(Device.last_connected.asc().nullsfirst(), Device.created_at.asc())
        .limit(1)
    )
    victim = result.scalar_one_or_none()
    if not victim:
        return False
    await db.delete(victim)
    await db.commit()
    return True


async def count_active_sessions(db: AsyncSession, user_id) -> int:
    result = await db.execute(
        select(func.count(Device.id)).where(
            Device.user_id == user_id,
            Device.is_active == True,
        )
    )
    return result.scalar_one()


async def count_connected_sessions(db: AsyncSession, user_id) -> int:
    result = await db.execute(
        select(func.count(Device.id)).where(
            Device.user_id == user_id,
            Device.is_active == True,
            Device.is_connected == True,
        )
    )
    return result.scalar_one()


async def end_device_session(
    db: AsyncSession,
    user_id,
    device_fingerprint: str,
) -> bool:
    result = await db.execute(
        select(Device).where(
            Device.user_id == user_id,
            Device.device_fingerprint == device_fingerprint,
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        return False
    await db.delete(device)
    await db.commit()
    return True


async def register_device(
    db: AsyncSession,
    user: User,
    device_name: str,
    device_type: str,
    device_fingerprint: str,
    wg_public_key: Optional[str] = None,
) -> VpnConfigResponse:
    await clear_stale_online_status(db)
    await prune_old_sessions(db, user.id)

    result = await db.execute(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_fingerprint == device_fingerprint,
            Device.is_active == True,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return await _build_vpn_config(db, existing)

    active_count = await count_active_sessions(db, user.id)
    if active_count >= settings.MAX_DEVICES_PER_USER:
        freed = await prune_oldest_session_if_full(db, user.id)
        active_count = await count_active_sessions(db, user.id)
        if not freed and active_count >= settings.MAX_DEVICES_PER_USER:
            raise ValueError(
                f"Достигнут лимит {settings.MAX_DEVICES_PER_USER} устройств. "
                "Выйдите из аккаунта на одном из них."
            )

    priv_key, pub_key = _generate_wg_keypair()
    if wg_public_key:
        pub_key = wg_public_key
        priv_key = ""

    wg_address = await _get_next_wg_address(db)
    wdtt_pass = (settings.WDTT_MASTER_PASSWORD or "").strip() or generate_wdtt_password()

    device = Device(
        user_id=user.id,
        device_name=device_name,
        device_type=device_type,
        device_fingerprint=device_fingerprint,
        wg_public_key=pub_key,
        wg_private_key_enc=encrypt_value(priv_key) if priv_key else None,
        wg_address=wg_address,
        wdtt_password=wdtt_pass,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)

    return await _build_vpn_config(db, device)


async def _build_vpn_config(db: AsyncSession, device: Device) -> VpnConfigResponse:
    from app.core.security import decrypt_value

    hashes = await get_active_vk_hashes(db)
    server_pub_key = await get_server_public_key(db)

    priv_key = ""
    if device.wg_private_key_enc:
        try:
            priv_key = decrypt_value(device.wg_private_key_enc)
        except Exception:
            pass

    if not _is_valid_wg_key(priv_key):
        priv_key, pub_key = _generate_wg_keypair()
        device.wg_private_key_enc = encrypt_value(priv_key)
        device.wg_public_key = pub_key
        await db.commit()

    if not _is_valid_wg_key(server_pub_key):
        logger.warning("server_public_key missing — set WG_SERVER_PUBLIC_KEY in .env")

    return VpnConfigResponse(
        device_id=str(device.id),
        wg_private_key=priv_key,
        wg_address=device.wg_address or "10.66.66.2/24",
        wg_dns="77.88.8.8,77.88.8.1",
        server_ip=settings.VPN_SERVER_IP,
        server_port=settings.VPN_SERVER_PORT,
        server_public_key=server_pub_key,
        wdtt_password=(settings.WDTT_MASTER_PASSWORD or "").strip() or (device.wdtt_password or ""),
        vk_hashes=hashes,
        stream_count=3,
    )
