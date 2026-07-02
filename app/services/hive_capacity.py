"""Адаптивная ёмкость Улья: сэмплы нагрузки и расчёт max_online по p95."""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import HiveCell, HiveLoadSample
from app.services.hive_load import queen_accepting_new_vpn

logger = logging.getLogger(__name__)


@dataclass
class CapacityProfile:
    max_online: int
    bottleneck: str
    mode: str
    samples_count: int
    per_user_cpu_p95: float | None
    per_user_mem_p95: float | None
    per_user_mbps_p95: float | None
    link_capacity_mbps: float

    def to_dict(self) -> dict:
        return {
            "max_online": self.max_online,
            "bottleneck": self.bottleneck,
            "mode": self.mode,
            "samples_count": self.samples_count,
            "per_user_cpu_p95": self.per_user_cpu_p95,
            "per_user_mem_p95": self.per_user_mem_p95,
            "per_user_mbps_p95": self.per_user_mbps_p95,
            "link_capacity_mbps": self.link_capacity_mbps,
        }


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (p / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def _network_mbps(load: dict) -> float:
    rx = float(load.get("network_mbps_rx") or 0)
    tx = float(load.get("network_mbps_tx") or 0)
    return max(rx, tx)


def _link_capacity_mbps(load: dict | None) -> float:
    if load:
        cap = float(load.get("network_link_capacity_mbps") or 0)
        if cap > 0:
            return cap
    return float(settings.HIVE_LINK_CAPACITY_MBPS)


def fallback_max_online(link_capacity_mbps: float) -> int:
    util = max(0.01, float(settings.HIVE_LINK_TARGET_UTILIZATION_PERCENT) / 100.0)
    per_user_mbps = max(0.01, float(settings.HIVE_TARGET_ACTIVE_USER_MBPS))
    per_user_cpu = max(0.5, float(settings.HIVE_CAPACITY_FALLBACK_CPU_PER_USER))
    by_net = int((link_capacity_mbps * util) // per_user_mbps)
    by_cpu = int(settings.HIVE_CPU_PERCENT_THRESHOLD // per_user_cpu)
    by_mem = int(settings.HIVE_MEM_PERCENT_THRESHOLD // max(1.0, settings.HIVE_CAPACITY_FALLBACK_MEM_PER_USER))
    return max(1, min(by_net, by_cpu, by_mem))


def compute_max_online_from_samples(
    samples: list[HiveLoadSample],
    *,
    link_capacity_mbps: float,
) -> CapacityProfile:
    min_samples = max(1, int(settings.HIVE_CAPACITY_MIN_SAMPLES))
    min_online = max(1, int(settings.HIVE_CAPACITY_MIN_ONLINE_FOR_LEARN))
    p = float(settings.HIVE_CAPACITY_P95_PERCENTILE)

    usable = [s for s in samples if s.online_count >= min_online]
    if len(usable) < min_samples:
        cap = fallback_max_online(link_capacity_mbps)
        return CapacityProfile(
            max_online=cap,
            bottleneck="fallback",
            mode="fallback",
            samples_count=len(samples),
            per_user_cpu_p95=None,
            per_user_mem_p95=None,
            per_user_mbps_p95=None,
            link_capacity_mbps=link_capacity_mbps,
        )

    cpu_per = [s.cpu_percent / s.online_count for s in usable]
    mem_per = [s.memory_percent / s.online_count for s in usable]
    mbps_per = [s.network_mbps / s.online_count for s in usable]

    p95_cpu = _percentile(cpu_per, p) or float(settings.HIVE_CAPACITY_FALLBACK_CPU_PER_USER)
    p95_mem = _percentile(mem_per, p) or float(settings.HIVE_CAPACITY_FALLBACK_MEM_PER_USER)
    p95_mbps = _percentile(mbps_per, p) or max(0.001, float(settings.HIVE_TARGET_ACTIVE_USER_MBPS))

    by_cpu = int(settings.HIVE_CPU_PERCENT_THRESHOLD / max(0.5, p95_cpu))
    by_mem = int(settings.HIVE_MEM_PERCENT_THRESHOLD / max(0.5, p95_mem))
    target_mbps = link_capacity_mbps * (settings.HIVE_BANDWIDTH_PERCENT_THRESHOLD / 100.0)
    by_net = int(target_mbps / max(0.001, p95_mbps))

    limits = {
        "cpu": max(1, by_cpu),
        "memory": max(1, by_mem),
        "network": max(1, by_net),
    }
    bottleneck = min(limits, key=limits.get)
    max_online = limits[bottleneck]

    return CapacityProfile(
        max_online=max_online,
        bottleneck=bottleneck,
        mode="adaptive",
        samples_count=len(usable),
        per_user_cpu_p95=round(p95_cpu, 2),
        per_user_mem_p95=round(p95_mem, 2),
        per_user_mbps_p95=round(p95_mbps, 4),
        link_capacity_mbps=link_capacity_mbps,
    )


async def fetch_recent_samples(db: AsyncSession, cell_id: uuid.UUID) -> list[HiveLoadSample]:
    hours = max(1, int(settings.HIVE_CAPACITY_SAMPLE_RETENTION_HOURS))
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(HiveLoadSample)
        .where(HiveLoadSample.cell_id == cell_id, HiveLoadSample.sampled_at >= cutoff)
        .order_by(HiveLoadSample.sampled_at.desc())
        .limit(int(settings.HIVE_CAPACITY_MAX_SAMPLES_PER_CELL))
    )
    return list(result.scalars().all())


async def get_capacity_profile(
    db: AsyncSession,
    cell: HiveCell,
    *,
    load: dict | None = None,
) -> CapacityProfile:
    samples = await fetch_recent_samples(db, cell.id)
    link_cap = _link_capacity_mbps(load)
    profile = compute_max_online_from_samples(samples, link_capacity_mbps=link_cap)
    configured = int(cell.max_clients or 0)
    if configured > 0:
        capped = min(configured, profile.max_online)
        return CapacityProfile(
            max_online=max(1, capped),
            bottleneck=profile.bottleneck if profile.mode == "adaptive" else "manual_cap",
            mode="manual_cap" if capped < profile.max_online else profile.mode,
            samples_count=profile.samples_count,
            per_user_cpu_p95=profile.per_user_cpu_p95,
            per_user_mem_p95=profile.per_user_mem_p95,
            per_user_mbps_p95=profile.per_user_mbps_p95,
            link_capacity_mbps=profile.link_capacity_mbps,
        )
    return profile


async def max_online_for_cell(
    db: AsyncSession,
    cell: HiveCell,
    *,
    load: dict | None = None,
) -> int:
    profile = await get_capacity_profile(db, cell, load=load)
    return profile.max_online


async def record_sample(
    db: AsyncSession,
    cell_id: uuid.UUID,
    online_count: int,
    load: dict,
) -> None:
    sample = HiveLoadSample(
        cell_id=cell_id,
        sampled_at=datetime.utcnow(),
        online_count=max(0, int(online_count)),
        cpu_percent=round(float(load.get("cpu_percent") or 0), 2),
        memory_percent=round(float(load.get("memory_percent") or 0), 2),
        network_mbps=round(_network_mbps(load), 4),
        network_util_percent=round(float(load.get("network_util_percent") or 0), 2),
        link_capacity_mbps=round(_link_capacity_mbps(load), 1),
    )
    db.add(sample)
    await db.commit()
    await _prune_old_samples(db, cell_id)


async def _prune_old_samples(db: AsyncSession, cell_id: uuid.UUID) -> None:
    hours = max(1, int(settings.HIVE_CAPACITY_SAMPLE_RETENTION_HOURS))
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    await db.execute(
        delete(HiveLoadSample).where(
            HiveLoadSample.cell_id == cell_id,
            HiveLoadSample.sampled_at < cutoff,
        )
    )
    await db.commit()


async def sample_all_cells(db: AsyncSession) -> None:
    from app.services.hive_service import (
        count_online_on_cell,
        ensure_queen_cell,
        fetch_worker_cell_load,
    )

    result = await db.execute(
        select(HiveCell).where(HiveCell.status.in_(("active", "draining")))
    )
    cells = list(result.scalars().all())
    if not cells:
        await ensure_queen_cell(db)
        result = await db.execute(
            select(HiveCell).where(HiveCell.status.in_(("active", "draining")))
        )
        cells = list(result.scalars().all())

    _, queen_load = queen_accepting_new_vpn()
    for cell in cells:
        online = await count_online_on_cell(db, cell.id)
        if cell.is_queen:
            load = queen_load
        else:
            load = await fetch_worker_cell_load(cell)
            if not load:
                continue
        await record_sample(db, cell.id, online, load)


async def capacity_sampler_loop() -> None:
    interval = max(10, int(settings.HIVE_CAPACITY_SAMPLE_INTERVAL_SEC))
    await asyncio.sleep(15)
    logger.info("Hive capacity sampler started (every %ss)", interval)
    while True:
        try:
            from app.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                await sample_all_cells(db)
        except Exception as e:
            logger.warning("Hive capacity sample cycle failed: %s", e)
        await asyncio.sleep(interval)


def start_hive_capacity_sampler() -> asyncio.Task:
    return asyncio.create_task(capacity_sampler_loop())
