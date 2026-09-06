"""Dashboard system metrics for Queen or a worker cell."""
from __future__ import annotations

import logging
import uuid

import psutil
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.hive_slots import node_title_for_slot, slot_for_cell
from app.services.proc_stats import read_host_load
from app.services.system_info import get_cpu_info

logger = logging.getLogger(__name__)

QUEEN_NODE_ID = "queen"


def _queen_system() -> dict:
    load = read_host_load(cpu_interval=0.1)
    cpu = float(load.get("cpu_percent") or 0.0)
    cpu_info = get_cpu_info(cpu)
    if load.get("cpu_cores"):
        cpu_info["cpu_cores"] = int(load["cpu_cores"])
    disk = psutil.disk_usage("/")
    return {
        "node_id": QUEEN_NODE_ID,
        "cpu_percent": cpu,
        **cpu_info,
        "memory_total_gb": float(load.get("memory_total_gb") or 0.0),
        "memory_used_gb": float(load.get("memory_used_gb") or 0.0),
        "memory_percent": float(load.get("memory_percent") or 0.0),
        "disk_total_gb": round(disk.total / (1024**3), 1),
        "disk_used_gb": round(disk.used / (1024**3), 1),
        "disk_percent": float(disk.percent),
        "network_interface": load.get("network_interface"),
        "network_mbps_rx": float(load.get("network_mbps_rx") or 0.0),
        "network_mbps_tx": float(load.get("network_mbps_tx") or 0.0),
        "network_util_percent": float(load.get("network_util_percent") or 0.0),
        "network_link_capacity_mbps": float(
            load.get("network_link_capacity_mbps") or settings.HIVE_LINK_CAPACITY_MBPS
        ),
        "reachable": True,
        # CPU% уже по всем ядрам (0–100), не «на одно ядро»
        "cpu_percent_scope": "all_cores",
    }


def _empty_system(*, node_id: str, reachable: bool = False) -> dict:
    return {
        "node_id": node_id,
        "cpu_percent": 0.0,
        "cpu_model": None,
        "cpu_cores": None,
        "cpu_freq_base_mhz": None,
        "cpu_freq_current_mhz": None,
        "cpu_freq_estimated": False,
        "memory_total_gb": 0.0,
        "memory_used_gb": 0.0,
        "memory_percent": 0.0,
        "disk_total_gb": None,
        "disk_used_gb": None,
        "disk_percent": None,
        "network_interface": None,
        "network_mbps_rx": 0.0,
        "network_mbps_tx": 0.0,
        "network_util_percent": 0.0,
        "network_link_capacity_mbps": float(settings.HIVE_LINK_CAPACITY_MBPS),
        "reachable": reachable,
        "cpu_percent_scope": "all_cores",
    }


def _system_from_cell_load(node_id: str, load: dict) -> dict:
    mem_total = float(load.get("memory_total_gb") or 0.0)
    mem_pct = float(load.get("memory_percent") or 0.0)
    mem_used = round(mem_total * mem_pct / 100.0, 1) if mem_total > 0 else 0.0
    cores = load.get("cpu_cores")
    base = load.get("cpu_freq_base_mhz")
    return {
        "node_id": node_id,
        "cpu_percent": float(load.get("cpu_percent") or 0.0),
        "cpu_model": (load.get("cpu_model") or None),
        "cpu_cores": int(cores) if cores else None,
        "cpu_freq_base_mhz": float(base) if base not in (None, "", 0, 0.0) else None,
        "cpu_freq_current_mhz": None,
        "cpu_freq_estimated": True,
        "memory_total_gb": mem_total,
        "memory_used_gb": mem_used,
        "memory_percent": mem_pct,
        "disk_total_gb": None,
        "disk_used_gb": None,
        "disk_percent": None,
        "network_interface": load.get("network_interface"),
        "network_mbps_rx": float(load.get("network_mbps_rx") or 0.0),
        "network_mbps_tx": float(load.get("network_mbps_tx") or 0.0),
        "network_util_percent": float(load.get("network_util_percent") or 0.0),
        "network_link_capacity_mbps": float(
            load.get("network_link_capacity_mbps") or settings.HIVE_LINK_CAPACITY_MBPS
        ),
        "reachable": True,
        "cpu_percent_scope": "all_cores",
    }


async def list_dashboard_resource_nodes(db: AsyncSession) -> list[dict]:
    """Улей + активные/draining соты (новые соты появляются сами)."""
    from app.models.hive_cell import HiveCell

    result = await db.execute(
        select(HiveCell).where(
            or_(
                HiveCell.is_queen.is_(True),
                HiveCell.status.in_(("active", "draining")),
            )
        )
    )
    cells = list(result.scalars().all())
    cells.sort(key=lambda c: (0 if c.is_queen else 1, c.priority or 100, str(c.created_at or "")))
    nodes: list[dict] = []
    for cell in cells:
        slot = slot_for_cell(cell)
        title = node_title_for_slot(slot) if slot else (cell.name or "Сота")
        if cell.is_queen:
            nodes.append(
                {
                    "id": QUEEN_NODE_ID,
                    "name": cell.name or "Улей",
                    "title": "Улей",
                    "is_queen": True,
                    "status": cell.status,
                }
            )
        else:
            nodes.append(
                {
                    "id": str(cell.id),
                    "name": cell.name or title,
                    "title": title,
                    "is_queen": False,
                    "status": cell.status,
                }
            )
    if not any(n["is_queen"] for n in nodes):
        nodes.insert(
            0,
            {
                "id": QUEEN_NODE_ID,
                "name": "Улей",
                "title": "Улей",
                "is_queen": True,
                "status": "active",
            },
        )
    return nodes


async def dashboard_system_for_node(db: AsyncSession, node_id: str | None) -> dict:
    """Метрики выбранной ноды. Дефолт — Улей. Недоступная сота → reachable=false."""
    nid = (node_id or QUEEN_NODE_ID).strip() or QUEEN_NODE_ID
    if nid == QUEEN_NODE_ID:
        return _queen_system()

    try:
        cell_uuid = uuid.UUID(nid)
    except ValueError:
        return _queen_system()

    from app.models.hive_cell import HiveCell
    from app.services.hive_service import fetch_worker_cell_load

    cell = await db.get(HiveCell, cell_uuid)
    if cell is None or cell.is_queen:
        return _queen_system()

    load = await fetch_worker_cell_load(cell, timeout=2.5)
    if not load:
        empty = _empty_system(node_id=nid, reachable=False)
        empty["cpu_cores"] = None
        return empty
    return _system_from_cell_load(nid, load)
