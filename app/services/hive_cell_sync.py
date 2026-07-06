"""Синхронизация VPN-manifest на worker-соты (без полного дампа БД)."""
from __future__ import annotations

import logging
from datetime import datetime

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import decrypt_value
from app.models import Device, HiveCell
from app.services.hive_service import _validate_outbound_url, get_cell_by_id

logger = logging.getLogger(__name__)

_last_manifest_version: int = 0
_last_sync_at: datetime | None = None


async def manifest_version(db: AsyncSession) -> int:
    """Версия manifest: число устройств + время последнего изменения (last_connected / created_at)."""
    result = await db.execute(
        select(
            func.count(Device.id),
            func.max(func.coalesce(Device.last_connected, Device.created_at)),
        ).where(Device.is_active == True)  # noqa: E712
    )
    row = result.one()
    count = int(row[0] or 0)
    updated = row[1]
    ts = int(updated.timestamp()) if updated else 0
    return count * 1_000_000 + (ts % 1_000_000)


async def build_cell_manifest(db: AsyncSession, cell: HiveCell) -> dict:
    from app.services.hive_standby import build_cell_manifest_enriched

    return await build_cell_manifest_enriched(db, cell)


async def push_manifest_to_cell(cell: HiveCell, manifest: dict) -> bool:
    if not cell.api_url or not cell.api_secret_enc:
        return False
    try:
        pwd = decrypt_value(cell.api_secret_enc)
    except Exception:
        return False
    try:
        base = _validate_outbound_url(cell.api_url)
    except ValueError:
        return False
    url = f"{base}/v1/sync-manifest"
    timeout = settings.HIVE_CELL_HTTP_TIMEOUT_SEC
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.post(
                url,
                headers={"X-Cell-Agent-Secret": pwd},
                json=manifest,
            )
        if resp.status_code >= 400:
            logger.debug("Hive manifest %s: HTTP %s", cell.name, resp.status_code)
            return False
        return True
    except Exception as e:
        logger.debug("Hive manifest %s failed: %s", cell.name, e)
        return False


async def sync_all_cell_manifests(db: AsyncSession) -> dict:
    """Пушит manifest на все активные соты (для автономии при падении Улья)."""
    global _last_manifest_version, _last_sync_at

    if not settings.HIVE_CELL_MANIFEST_SYNC_ENABLED:
        return {"synced": 0, "skipped": True}

    version = await manifest_version(db)
    if version == _last_manifest_version and _last_sync_at is not None:
        return {"synced": 0, "skipped": True, "version": version}

    result = await db.execute(
        select(HiveCell).where(
            HiveCell.is_queen == False,  # noqa: E712
            HiveCell.status.in_(("active", "draining")),
            HiveCell.api_url.isnot(None),
        )
    )
    workers = list(result.scalars().all())
    synced = 0
    for cell in workers:
        manifest = await build_cell_manifest(db, cell)
        if await push_manifest_to_cell(cell, manifest):
            synced += 1

    _last_manifest_version = version
    _last_sync_at = datetime.utcnow()
    if synced:
        logger.info("Hive manifest sync: %s/%s cells, version=%s", synced, len(workers), version)
    return {"synced": synced, "total": len(workers), "version": version}


async def sync_cell_manifest_by_id(db: AsyncSession, cell_id) -> bool:
    cell = await get_cell_by_id(db, cell_id)
    if not cell or cell.is_queen:
        return False
    manifest = await build_cell_manifest(db, cell)
    return await push_manifest_to_cell(cell, manifest)
