"""Standby / HA: под-улей на сотах при падении главного API."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Device, HiveCell, User
from app.services import hive_service
from app.services.hive_slots import slot_for_cell
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


def cell_public_api_base(cell: HiveCell) -> str:
    """Публичный API соты для клиента, если Улей не открывается (cell-agent :9100)."""
    ip = (cell.public_ip or "").strip()
    if not ip:
        return ""
    port = int(getattr(settings, "HIVE_CELL_AGENT_PORT", 9100) or 9100)
    return f"http://{ip}:{port}"


async def standby_api_urls(db: AsyncSession) -> list[str]:
    """Публичные URL standby API для клиентов (theme / login / config)."""
    urls: list[str] = []
    for cell in await get_standby_cells(db):
        base = cell_public_api_base(cell)
        if base:
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
    """Manifest для автономии соты: устройства этой ноды и слота Сервер N, не вся БД."""
    from app.services.hive_cell_sync import manifest_version

    version = await manifest_version(db)
    slot = slot_for_cell(cell)
    clauses = [Device.cell_id == cell.id]
    if slot:
        clauses.append(Device.preferred_server == slot)
    result = await db.execute(
        select(Device).where(
            Device.is_active == True,  # noqa: E712
            or_(*clauses),
        )
    )
    seen: set[str] = set()
    devices: list[Device] = []
    for d in result.scalars().all():
        key = str(d.id)
        if key in seen:
            continue
        seen.add(key)
        devices.append(d)
    user_ids = {d.user_id for d in devices}
    allowed_map: dict = {}
    for uid in user_ids:
        allowed_map[uid] = await device_vpn_allowed(db, uid)

    wg_pub = (cell.wg_public_key or "").strip()
    theme_blob = None
    try:
        from app.services.theme_settings import load_theme

        theme_blob = (await load_theme(db)).model_dump()
    except Exception:
        theme_blob = None
    meta = None
    try:
        meta = await hive_meta(db)
    except Exception:
        meta = None
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
        "server_slot": slot or None,
        "device_count": len(devices),
        "theme": theme_blob,
        "hive_meta": meta,
        "devices": [
            {
                "id": str(d.id),
                "user_id": str(d.user_id),
                "wg_public_key": (d.wg_public_key or "").strip(),
                "wg_address": (
                    f"{(d.wg_address or '10.66.66.2').split('/', 1)[0]}/32"
                ),
                "is_connected": bool(d.is_connected),
                "vpn_allowed": bool(allowed_map.get(d.user_id, False)),
            }
            for d in devices
        ],
    }
