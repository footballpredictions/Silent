"""VPN configuration service — WireGuard key generation and WDTT password management."""
import subprocess
import base64
import ipaddress
import uuid
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models import Device, User, VkHash, AppSetting
from app.core.security import generate_wdtt_password, encrypt_value
from app.config import settings
from app.schemas.vpn import VpnConfigResponse

logger = logging.getLogger(__name__)


def _generate_wg_keypair() -> tuple[str, str]:
    """Generate WireGuard private/public key pair using wg command or pure Python."""
    try:
        priv = subprocess.check_output(["wg", "genkey"], stderr=subprocess.DEVNULL).strip().decode()
        pub = subprocess.check_output(["wg", "pubkey"], input=priv.encode(), stderr=subprocess.DEVNULL).strip().decode()
        return priv, pub
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Fallback: generate random 32 bytes and base64-encode (for dev/testing)
        import secrets as _s
        priv_bytes = _s.token_bytes(32)
        priv_b64 = base64.b64encode(priv_bytes).decode()
        # Without wg binary we can't derive the real public key — return placeholder
        pub_b64 = base64.b64encode(b"\x00" * 32).decode()
        logger.warning("wg binary not found, using placeholder keys (dev mode)")
        return priv_b64, pub_b64


async def _get_next_wg_address(db: AsyncSession) -> str:
    """Assign next available IP from WireGuard subnet."""
    subnet = ipaddress.IPv4Network(settings.WG_SUBNET)
    hosts = list(subnet.hosts())
    # .1 is the server itself
    server_ip = str(hosts[0])

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
    result = await db.execute(select(AppSetting).where(AppSetting.key == "server_public_key"))
    setting = result.scalar_one_or_none()
    return setting.value if setting else ""


async def register_device(
    db: AsyncSession,
    user: User,
    device_name: str,
    device_type: str,
    device_fingerprint: str,
    wg_public_key: Optional[str] = None,
) -> VpnConfigResponse:
    """Register new device and generate VPN config. Max 3 devices per user."""

    # Check device limit (admin has unlimited devices)
    if not user.is_admin:
        result = await db.execute(
            select(func.count(Device.id))
            .where(Device.user_id == user.id, Device.is_active == True)
        )
        count = result.scalar_one()
        if count >= settings.MAX_DEVICES_PER_USER:
            raise ValueError(f"Достигнут максимум {settings.MAX_DEVICES_PER_USER} устройства. Подключите новый аккаунт.")

    # Check if device already registered by fingerprint
    result = await db.execute(
        select(Device).where(Device.user_id == user.id, Device.device_fingerprint == device_fingerprint)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return await _build_vpn_config(db, existing)

    # Generate WireGuard keys
    priv_key, pub_key = _generate_wg_keypair()
    if wg_public_key:
        pub_key = wg_public_key
        priv_key = ""  # Client provides own key

    wg_address = await _get_next_wg_address(db)
    # Use master WDTT password — devices authenticate with the server master password
    wdtt_pass = settings.WDTT_MASTER_PASSWORD

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

    return VpnConfigResponse(
        device_id=device.id,
        wg_private_key=priv_key,
        wg_address=device.wg_address or "10.66.66.2/24",
        wg_dns="77.88.8.8,77.88.8.1",
        server_ip=settings.VPN_SERVER_IP,
        server_port=settings.VPN_SERVER_PORT,
        server_public_key=server_pub_key,
        wdtt_password=device.wdtt_password or "",
        vk_hashes=hashes,
        stream_count=3,
    )
