"""Автообновление cell-agent на сотах по сохранённому SSH."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import HiveCell
from app.services.hive_incidents import push_incident
from app.services import hive_provision_service
from app.services.hive_service import fetch_worker_cell_load, resolve_ssh_password

logger = logging.getLogger(__name__)

_upgrading: set[uuid.UUID] = set()
_fail_until: dict[uuid.UUID, float] = {}


async def auto_upgrade_cell_agents(db: AsyncSession) -> dict:
    if not settings.HIVE_CELL_AGENT_AUTO_UPGRADE_ENABLED:
        return {"checked": 0, "upgraded": 0, "skipped": True}

    try:
        target_id = hive_provision_service.cell_agent_build_id()
    except RuntimeError as e:
        logger.debug("Cell-agent auto-upgrade skipped: %s", e)
        return {"checked": 0, "upgraded": 0, "error": "no_agent_source"}

    result = await db.execute(
        select(HiveCell).where(
            HiveCell.is_queen == False,  # noqa: E712
            HiveCell.status.in_(("active", "draining")),
            HiveCell.api_url.isnot(None),
        )
    )
    cells = list(result.scalars().all())
    upgraded = 0
    now = time.monotonic()
    cooldown = max(60, int(settings.HIVE_CELL_AGENT_UPGRADE_FAIL_COOLDOWN_SEC))

    for cell in cells:
        if cell.id in _upgrading:
            continue
        if now < _fail_until.get(cell.id, 0):
            continue
        pwd = resolve_ssh_password(cell)
        if not pwd:
            continue

        load = await fetch_worker_cell_load(cell)
        remote_id = (load or {}).get("agent_build_id") if load else None
        if remote_id == target_id:
            continue

        host = (cell.public_ip or "").strip()
        if not host:
            continue

        _upgrading.add(cell.id)
        try:
            await asyncio.to_thread(
                hive_provision_service.upgrade_cell_agent_via_ssh,
                host,
                pwd,
                link_capacity_mbps=float(
                    cell.link_capacity_mbps or settings.HIVE_CELL_DEFAULT_LINK_CAPACITY_MBPS
                ),
            )
            upgraded += 1
            _fail_until.pop(cell.id, None)
            logger.info(
                "Hive: cell-agent auto-upgraded on %s (%s → %s)",
                cell.name,
                remote_id or "?",
                target_id,
            )
        except Exception as e:
            _fail_until[cell.id] = now + cooldown
            logger.warning("Hive: cell-agent auto-upgrade %s failed: %s", cell.name, e)
            push_incident(
                source="hive.agent-upgrade",
                severity="error",
                cell_name=cell.name,
                cell_ip=cell.public_ip,
                message=f"Auto-upgrade cell-agent failed: {e}",
                details=f"remote_id={remote_id or '?'} target_id={target_id}",
            )
        finally:
            _upgrading.discard(cell.id)

    return {"checked": len(cells), "upgraded": upgraded, "target_build_id": target_id}
