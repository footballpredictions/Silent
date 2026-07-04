"""Standby / HA: под-улей на сотах при падении главного API."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Device, HiveCell, User
from app.services import hive_service
from app.services.subscription_service import user_has_active_subscription

logger = logging.getLogger(__name__)


async def get_standby_cells(db: AsyncSession) -> list[HiveCell]:
    """Соты для failover: «Сота 1» первая, остальные active worker."""
    result = await db.execute(
        select(HiveCell).where(
            HiveCell.is_queen == False,  # noqa: E712
            HiveCell.status == "active",
            HiveCell.public_ip.isnot(None),
        )
    )
    cells = list(result.scalars().all())
    cells.sort(key=hive_service.cell_list_sort_key)
    return cells


async def standby_api_urls(db: AsyncSession) -> list[str]:
    """Публичные URL standby API для клиентов (theme / config sync)."""
    urls: list[str] = []
    for cell in await get_standby_cells(db):
        ip = (cell.public_ip or "").strip()
        if not ip:
            continue
        urls.append(f"https://{ip}")
        urls.append(f"http://{ip}:8000")
        if cell.api_url:
            base = cell.api_url.strip().rstrip("/")
            if base and base not in urls:
                urls.append(base)
    return urls


async def standby_vpn_hosts(db: AsyncSession) -> list[str]:
    """IP worker-сот для прямого VPN (уже в конфиге устройств на соте)."""
    return [
        (c.public_ip or "").strip()
        for c in await get_standby_cells(db)
        if (c.public_ip or "").strip()
    ]


async def hive_meta(db: AsyncSession) -> dict:
    queen = await hive_service.get_queen_cell(db)
    standby = await get_standby_cells(db)
    return {
        "queen_ip": (queen.public_ip if queen else settings.VPN_SERVER_IP) or "",
        "standby_cells": [
            {
                "id": str(c.id),
                "name": c.name,
                "public_ip": c.public_ip,
                "api_url": c.api_url,
                "wdtt_port": c.wdtt_port,
            }
            for c in standby
        ],
        "standby_api_urls": await standby_api_urls(db),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


async def device_vpn_allowed(db: AsyncSession, user_id) -> bool:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return False
    if user.is_admin:
        return True
    return await user_has_active_subscription(user, db)


async def build_cell_manifest_enriched(db: AsyncSession, cell: HiveCell) -> dict:
    """Manifest для автономии соты: peers + подписка + параметры VPN."""
    from app.services.hive_cell_sync import manifest_version

    version = await manifest_version(db)
    result = await db.execute(
        select(Device).where(
            Device.cell_id == cell.id,
            Device.is_active == True,  # noqa: E712
        )
    )
    devices = list(result.scalars().all())
    user_ids = {d.user_id for d in devices}
    allowed_map: dict = {}
    for uid in user_ids:
        allowed_map[uid] = await device_vpn_allowed(db, uid)

    wg_pub = (cell.wg_public_key or "").strip()
    return {
        "version": version,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "cell_id": str(cell.id),
        "cell_name": cell.name,
        "public_ip": cell.public_ip,
        "wdtt_port": int(cell.wdtt_port or settings.VPN_SERVER_PORT),
        "wg_port": int(cell.wg_port or settings.WG_PORT),
        "wg_server_public_key": wg_pub,
        "hive_api_url": (settings.FRONTEND_URL or "").strip().rstrip("/"),
        "device_count": len(devices),
        "devices": [
            {
                "id": str(d.id),
                "user_id": str(d.user_id),
                "wg_public_key": (d.wg_public_key or "").strip(),
                "wg_address": (d.wg_address or "10.66.66.2/24").strip(),
                "is_connected": bool(d.is_connected),
                "vpn_allowed": bool(allowed_map.get(d.user_id, False)),
            }
            for d in devices
        ],
    }
