"""Snapshot of account data delivered with VPN config (same moment as subscription).

LTE cannot HTTP after main VPN (app excluded). GETCONF/DTLS already carries
access flags; this bundle rides on /device/register and /vpn/config so the
client does not need an overlay sync for profile/theme/referral/hashes.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import User, Device
from app.schemas.user import UserProfileResponse, SubscriptionInfo, DeviceInfo
from app.schemas.vpn import ClientSyncBundle
from app.services.subscription_service import (
    is_user_admin,
    ensure_admin_flag,
    ensure_trial_subscription,
    user_in_test_mode,
    get_display_subscription,
    max_devices_for_user,
)
from app.services.referral_service import get_referral_stats
from app.services.theme_settings import load_theme
from app.services.config_sync_service import build_sync_state


async def _profile_for_user(db: AsyncSession, user: User) -> UserProfileResponse:
    from app.services.vpn_service import (
        count_active_sessions,
        count_connected_sessions,
        collapse_duplicate_devices,
        clear_stale_online_status,
    )
    await ensure_admin_flag(user, db)
    await clear_stale_online_status(db)
    await collapse_duplicate_devices(db, user.id)
    if not await user_in_test_mode(user, db):
        await ensure_trial_subscription(db, user)
    admin = is_user_admin(user)
    test = await user_in_test_mode(user, db)

    subscription_info = SubscriptionInfo(is_active=False)
    if admin:
        subscription_info = SubscriptionInfo(
            is_active=True,
            plan_type="unlimited",
            expires_at=None,
            days_left=9999,
        )
    elif test:
        subscription_info = SubscriptionInfo(
            is_active=True,
            plan_type="test",
            expires_at=None,
            days_left=9999,
        )
    else:
        sub = await get_display_subscription(db, user, in_test_mode=False)
        if sub:
            subscription_info = SubscriptionInfo(
                is_active=True,
                plan_type=sub.plan_type,
                expires_at=sub.expires_at,
                days_left=sub.days_left,
            )

    result = await db.execute(
        select(Device).where(
            Device.user_id == user.id,
            Device.is_active == True,  # noqa: E712
        ).order_by(Device.last_connected.desc().nullslast(), Device.created_at.desc())
    )
    devices = result.scalars().all()
    device_infos = [
        DeviceInfo(
            id=d.id,
            device_name=d.device_name,
            device_type=d.device_type,
            is_connected=d.is_connected,
            last_connected=d.last_connected,
        )
        for d in devices
    ]
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        display_id=user.display_id,
        is_admin=admin,
        subscription=subscription_info,
        devices=device_infos,
        devices_count=await count_active_sessions(db, user.id),
        connected_count=await count_connected_sessions(db, user.id),
        max_devices=max_devices_for_user(user),
        vk_linked=user.vk_user_id is not None,
        vk_user_id=user.vk_user_id,
    )


async def build_client_sync_bundle(db: AsyncSession, user: User) -> ClientSyncBundle:
    from app.services.user_hash_service import get_server_hashes_for_user

    profile = await _profile_for_user(db, user)
    theme = await load_theme(db, persist_migration=False)
    referral = await get_referral_stats(db, user)
    hashes = await get_server_hashes_for_user(db, user)
    state = await build_sync_state(db, user)
    return ClientSyncBundle(
        profile=profile.model_dump(mode="json"),
        theme=theme.model_dump(mode="json"),
        referral=referral,
        hashes=hashes or [],
        sync=state,
    )
