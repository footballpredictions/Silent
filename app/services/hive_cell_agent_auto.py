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


def should_attempt_agent_upgrade(
    *,
    load: dict | None,
    target_id: str,
) -> bool:
    """Не лезть в SSH, если /v1/status недоступен — иначе remote_id=? → ложные апгрейды.

    reachable + пустой build_id = старый агент без поля → один апгрейд ок.
    """
    if load is None:
        return False
    remote_id = (load.get("agent_build_id") or "").strip()
    if remote_id == (target_id or "").strip():
        return False
    return True


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
    skipped_unreachable = 0
    now = time.monotonic()
    # Было 120с — при ночном флапе SSH это сыпало инциденты каждые ~2 мин.
    cooldown = max(600, int(settings.HIVE_CELL_AGENT_UPGRADE_FAIL_COOLDOWN_SEC))

    for cell in cells:
        if cell.id in _upgrading:
            continue
        if now < _fail_until.get(cell.id, 0):
            continue
        pwd = resolve_ssh_password(cell)
        if not pwd:
            continue

        load = await fetch_worker_cell_load(cell)
        if not should_attempt_agent_upgrade(load=load, target_id=target_id):
            if load is None:
                skipped_unreachable += 1
                logger.debug(
                    "Hive: cell-agent auto-upgrade skip %s — /v1/status unreachable",
                    cell.name,
                )
            continue

        remote_id = (load or {}).get("agent_build_id") if load else None
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
            err = f"{type(e).__name__}: {e}".strip()
            if not str(e).strip():
                err = f"{type(e).__name__} (no message)"
            logger.warning("Hive: cell-agent auto-upgrade %s failed: %s", cell.name, err)
            push_incident(
                source="hive.agent-upgrade",
                severity="error",
                cell_name=cell.name,
                cell_ip=cell.public_ip,
                message=f"Auto-upgrade cell-agent failed: {err}",
                details=f"remote_id={remote_id or '?'} target_id={target_id}",
            )
        finally:
            _upgrading.discard(cell.id)

    return {
        "checked": len(cells),
        "upgraded": upgraded,
        "skipped_unreachable": skipped_unreachable,
        "target_build_id": target_id,
    }
