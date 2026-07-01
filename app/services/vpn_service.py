"""VPN configuration service — WireGuard key generation and WDTT password management."""
import base64
import ipaddress
import logging
import os
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Device, User, VkHash, AppSetting
from app.core.security import generate_wdtt_password, encrypt_value
from app.config import settings
from app.schemas.vpn import VpnConfigResponse
from app.services import hive_service

logger = logging.getLogger(__name__)

LAST_SEEN_TOUCH_MINUTES = 15
DEVICE_LIMIT_HINT = (
    "Удалите неиспользуемую сессию в меню → Сессии и войдите снова."
)


def device_limit_error() -> ValueError:
    return ValueError(
        f"Достигнут лимит {settings.MAX_DEVICES_PER_USER} устройств. {DEVICE_LIMIT_HINT}"
    )


async def touch_user_last_seen(
    db: AsyncSession,
    user: User | uuid.UUID,
    *,
    min_interval_minutes: int = 0,
    commit: bool = True,
) -> None:
    """Последняя активность пользователя — не влияет на ConfigSync profile revision."""
    user_id = user.id if isinstance(user, User) else user
    result = await db.execute(select(User).where(User.id == user_id))
    row = result.scalar_one_or_none()
    if not row:
        return
    now = datetime.utcnow()
    if min_interval_minutes > 0 and row.last_seen_at:
        if (now - row.last_seen_at).total_seconds() < min_interval_minutes * 60:
            return
    row.last_seen_at = now
    if commit:
        await db.commit()


# Клиент явно вызвал POST /disconnect — wdtt keepalive не должен снова ставить online=true.
_client_disconnect_until: Dict[str, float] = {}
CLIENT_DISCONNECT_LATCH_SEC = 90.0


def mark_client_disconnect_latch(*device_refs: str) -> None:
    until = time.monotonic() + CLIENT_DISCONNECT_LATCH_SEC
    for ref in device_refs:
        key = (ref or "").strip()
        if key:
            _client_disconnect_until[key] = until


def _disconnect_latch_active(*device_refs: str) -> bool:
    now = time.monotonic()
    for ref in device_refs:
        key = (ref or "").strip()
        if not key:
            continue
        until = _client_disconnect_until.get(key)
        if until is None:
            continue
        if now >= until:
            _client_disconnect_until.pop(key, None)
            continue
        return True
    return False


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
    result = await db.execute(
        select(Device.wg_address).where(Device.wg_address.isnot(None))
    )
    used = {row[0] for row in result.fetchall()}
    for host in hosts[1:]:
        addr = f"{host}/{subnet.prefixlen}"
        if str(host) not in used and addr not in used:
            return addr
    raise RuntimeError("No available WireGuard addresses")


async def get_active_vk_hashes(db: AsyncSession, user_id=None) -> list[str]:
    """Legacy global hashes (user_id IS NULL) — admin panel only."""
    q = select(VkHash.hash_value).where(VkHash.is_active == True)
    if user_id is not None:
        q = q.where(VkHash.user_id == user_id)
    else:
        q = q.where(VkHash.user_id.is_(None))
    q = q.order_by(VkHash.slot_index)
    result = await db.execute(q)
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


async def set_device_online(db: AsyncSession, device_ref: str, online: bool) -> dict:
    """Server-to-server: wdtt-server reports a device as connected/disconnected.

    device_ref is the value libclient receives as -device-id, which equals the
    backend Device.id (UUID string). Falls back to device_fingerprint for safety.

    Returns subscription status so wdtt-server can drop sessions when access revoked.
    """
    from app.services.subscription_service import user_has_active_subscription

    device = None
    try:
        device_uuid = uuid.UUID(device_ref)
    except (ValueError, AttributeError, TypeError):
        device_uuid = None

    if device_uuid is not None:
        result = await db.execute(
            select(Device).where(Device.id == device_uuid, Device.is_active == True)
        )
        device = result.scalar_one_or_none()

    if device is None:
        result = await db.execute(
            select(Device).where(
                Device.device_fingerprint == device_ref,
                Device.is_active == True,
            )
        )
        device = result.scalar_one_or_none()

    if device is None:
        return {"ok": False, "subscription_active": False, "vpn_allowed": False}

    user_result = await db.execute(select(User).where(User.id == device.user_id))
    user = user_result.scalar_one_or_none()
    sub_active = False
    vpn_allowed = False
    if user is not None:
        sub_active = await user_has_active_subscription(user, db)
        vpn_allowed = bool(user.is_admin or sub_active)

    if online and _disconnect_latch_active(
        device_ref,
        str(device.id),
        device.device_fingerprint or "",
    ):
        logger.debug("ignore wdtt online=true — client disconnect latch active for %s", device_ref)
        return {"ok": True, "subscription_active": sub_active, "vpn_allowed": vpn_allowed}

    device.is_connected = bool(online)
    if online:
        device.last_connected = datetime.utcnow()
        await touch_user_last_seen(db, device.user_id, commit=False)
    await db.commit()
    return {"ok": True, "subscription_active": sub_active, "vpn_allowed": vpn_allowed}


async def prune_idle_sessions(db: AsyncSession, user_id) -> int:
    """Удалить неактивные сессии (переустановка / закрыли приложение без logout)."""
    idle_cutoff = datetime.utcnow() - timedelta(hours=settings.SESSION_IDLE_HOURS)
    result = await db.execute(
        select(Device).where(
            Device.user_id == user_id,
            Device.is_active == True,
            Device.is_connected == False,
            or_(
                Device.last_connected < idle_cutoff,
                and_(Device.last_connected.is_(None), Device.created_at < idle_cutoff),
            ),
        )
    )
    idle = result.scalars().all()
    for d in idle:
        await db.delete(d)
    if idle:
        await db.commit()
    return len(idle)


async def collapse_duplicate_devices(db: AsyncSession, user_id) -> int:
    """Удалить только повторы одного fingerprint (разные телефоны/ПК — отдельные слоты)."""
    removed = 0
    result = await db.execute(
        select(Device)
        .where(Device.user_id == user_id)
        .order_by(
            Device.is_connected.desc(),
            Device.last_connected.desc().nullslast(),
            Device.created_at.desc(),
        )
    )
    seen: set[str] = set()
    for d in result.scalars().all():
        fp = (d.device_fingerprint or "").strip()
        if not fp:
            continue
        if fp in seen:
            await db.delete(d)
            removed += 1
        else:
            seen.add(fp)
    if removed:
        await db.commit()
    return removed


async def dedupe_duplicate_fingerprint(
    db: AsyncSession,
    user_id,
    device_fingerprint: str,
) -> int:
    """Одна запись на fingerprint (гонка register/login), не трогаем другие устройства."""
    fp = (device_fingerprint or "").strip()
    if not fp:
        return 0
    result = await db.execute(
        select(Device)
        .where(Device.user_id == user_id, Device.device_fingerprint == fp)
        .order_by(
            Device.is_connected.desc(),
            Device.last_connected.desc().nullslast(),
            Device.created_at.desc(),
        )
    )
    rows = result.scalars().all()
    if len(rows) <= 1:
        return 0
    for d in rows[1:]:
        await db.delete(d)
    await db.commit()
    logger.info(
        "dedupe fingerprint: removed %d duplicate(s) for user %s keep %s",
        len(rows) - 1,
        user_id,
        fp[:16],
    )
    return len(rows) - 1


async def dedupe_same_type_devices(
    db: AsyncSession,
    user_id,
    device_type: str,
    keep_fingerprint: str,
) -> int:
    """Deprecated alias — только dedupe по fingerprint."""
    return await dedupe_duplicate_fingerprint(db, user_id, keep_fingerprint)


async def replace_same_type_session(
    db: AsyncSession,
    user_id,
    device_type: str,
    device_fingerprint: str,
) -> int:
    """Deprecated: больше не удаляем другие устройства того же типа."""
    return await dedupe_duplicate_fingerprint(db, user_id, device_fingerprint)


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


async def ensure_device_session(
    db: AsyncSession,
    user: User,
    device_name: str,
    device_type: str,
    device_fingerprint: str,
) -> Device:
    """После login: сессия в списке устройств, offline до POST /vpn/connect."""
    device_type = (device_type or "android").strip().lower()[:32]
    device_name = (device_name or device_type or "Device").strip()[:64]
    fp = (device_fingerprint or "").strip()
    if not fp:
        raise ValueError("device_fingerprint required")

    await clear_stale_online_status(db)
    await replace_same_type_session(db, user.id, device_type, fp)

    result = await db.execute(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_fingerprint == fp,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.is_active = True
        existing.device_name = device_name
        existing.device_type = device_type
        existing.is_connected = False
        existing.last_connected = datetime.utcnow()
        await touch_user_last_seen(db, user, commit=False)
        await db.commit()
        await db.refresh(existing)
        await dedupe_same_type_devices(db, user.id, device_type, fp)
        return existing

    active_count = await count_active_sessions(db, user.id)
    if active_count >= settings.MAX_DEVICES_PER_USER:
        raise device_limit_error()

    priv_key, pub_key = _generate_wg_keypair()
    cell = await hive_service.pick_cell_for_new_device(db, user=user)
    wg_address = await _get_next_wg_address(db)
    wdtt_pass = (settings.WDTT_MASTER_PASSWORD or "").strip() or generate_wdtt_password()

    device = Device(
        user_id=user.id,
        device_name=device_name,
        device_type=device_type,
        device_fingerprint=fp,
        wg_public_key=pub_key,
        wg_private_key_enc=encrypt_value(priv_key),
        wg_address=wg_address,
        wdtt_password=wdtt_pass,
        cell_id=cell.id,
        is_connected=False,
        last_connected=datetime.utcnow(),
    )
    db.add(device)
    await touch_user_last_seen(db, user, commit=False)
    await db.commit()
    await db.refresh(device)
    await dedupe_same_type_devices(db, user.id, device_type, fp)
    return device


async def register_device(
    db: AsyncSession,
    user: User,
    device_name: str,
    device_type: str,
    device_fingerprint: str,
    wg_public_key: Optional[str] = None,
) -> VpnConfigResponse:
    await clear_stale_online_status(db)
    await replace_same_type_session(db, user.id, device_type, device_fingerprint)

    result = await db.execute(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_fingerprint == device_fingerprint,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.is_active = True
        if device_name:
            existing.device_name = device_name[:64]
        if device_type:
            existing.device_type = device_type[:32]
        existing.last_connected = datetime.utcnow()
        await touch_user_last_seen(db, user, commit=False)
        await db.commit()
        await db.refresh(existing)
        await dedupe_same_type_devices(db, user.id, device_type, device_fingerprint)
        return await _build_vpn_config(db, existing)

    active_count = await count_active_sessions(db, user.id)
    if active_count >= settings.MAX_DEVICES_PER_USER:
        raise device_limit_error()

    priv_key, pub_key = _generate_wg_keypair()
    if wg_public_key:
        pub_key = wg_public_key
        priv_key = ""

    cell = await hive_service.pick_cell_for_new_device(db, user=user)
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
        cell_id=cell.id,
        last_connected=datetime.utcnow(),
    )
    db.add(device)
    await touch_user_last_seen(db, user, commit=False)
    await db.commit()
    await db.refresh(device)
    await dedupe_same_type_devices(db, user.id, device_type, device_fingerprint)

    return await _build_vpn_config(db, device)


async def _build_vpn_config(db: AsyncSession, device: Device) -> VpnConfigResponse:
    from app.core.security import decrypt_value
    from app.services.user_hash_service import get_vpn_hashes_for_user

    result = await db.execute(select(User).where(User.id == device.user_id))
    user = result.scalar_one_or_none()
    is_bootstrap = user and user.email == BOOTSTRAP_USER_EMAIL
    if user and not is_bootstrap:
        hashes = await get_vpn_hashes_for_user(db, user)
    else:
        hashes = await get_active_vk_hashes(db)

    cell = await hive_service.resolve_cell_for_device(
        db, device, force_queen=is_bootstrap,
    )
    server_pub_key = (cell.wg_public_key or "").strip()
    if not server_pub_key:
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
        logger.warning("server_public_key missing for cell %s", cell.id)

    server_ip = cell.public_ip or settings.VPN_SERVER_IP
    server_port = cell.wdtt_port or settings.VPN_SERVER_PORT

    return VpnConfigResponse(
        device_id=str(device.id),
        wg_private_key=priv_key,
        wg_address=device.wg_address or "10.66.66.2/24",
        wg_dns="77.88.8.8,77.88.8.1",
        server_ip=server_ip,
        server_port=server_port,
        server_public_key=server_pub_key,
        wdtt_password=(settings.WDTT_MASTER_PASSWORD or "").strip() or (device.wdtt_password or ""),
        vk_hashes=hashes,
        stream_count=9,
    )


BOOTSTRAP_USER_EMAIL = "__bootstrap__@silent.local"


async def validate_bootstrap_hash(db: AsyncSession, bootstrap_hash: str) -> bool:
    from app.services.user_hash_service import extract_call_hash

    return extract_call_hash(bootstrap_hash) is not None


async def get_or_create_bootstrap_user(db: AsyncSession) -> User:
    from app.core.security import hash_password

    result = await db.execute(select(User).where(User.email == BOOTSTRAP_USER_EMAIL))
    user = result.scalar_one_or_none()
    if user:
        return user
    user = User(
        email=BOOTSTRAP_USER_EMAIL,
        password_hash=hash_password(str(uuid.uuid4())),
        is_verified=True,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_bootstrap_hashes_for_user(db: AsyncSession, user: User) -> list[str]:
    boot = (user.bootstrap_hash or "").strip()
    return [boot] if boot else []


async def build_vpn_config_for_user(
    db: AsyncSession,
    device: Device,
    user: User,
    has_subscription: bool,
) -> VpnConfigResponse:
    from app.services.user_hash_service import (
        get_server_hashes_for_user,
        recommended_stream_count,
    )

    config = await _build_vpn_config(db, device)
    if user.email == BOOTSTRAP_USER_EMAIL:
        return config
    server_hashes = await get_server_hashes_for_user(db, user)
    if server_hashes:
        return config.model_copy(
            update={
                "vk_hashes": server_hashes,
                "stream_count": recommended_stream_count(len(server_hashes)),
            }
        )
    boot = await get_bootstrap_hashes_for_user(db, user)
    if boot:
        return config.model_copy(update={"vk_hashes": boot, "stream_count": 9})
    return config


async def register_bootstrap_device(
    db: AsyncSession,
    bootstrap_hash: str,
    device_fingerprint: str,
    device_type: str,
) -> VpnConfigResponse:
    from app.services.user_hash_service import extract_call_hash

    h = extract_call_hash(bootstrap_hash)
    if not h:
        raise ValueError("Недействительный bootstrap-хеш")

    user = await get_or_create_bootstrap_user(db)
    fp = f"boot:{device_fingerprint.strip()}"
    result = await db.execute(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_fingerprint == fp,
            Device.is_active == True,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        config = await _build_vpn_config(db, existing)
        return config.model_copy(update={"vk_hashes": [h]})

    config = await register_device(
        db,
        user,
        device_name=f"Bootstrap-{device_type}",
        device_type=device_type,
        device_fingerprint=fp,
        wg_public_key=None,
    )
    return config.model_copy(update={"vk_hashes": [h]})
