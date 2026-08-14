"""Адаптивная ёмкость Улья: CPU + RAM + канал с учётом железа каждой ноды."""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.hive_incidents import push_incident
from app.models import HiveCell, HiveLoadSample
from app.services.hive_load import queen_accepting_new_vpn

logger = logging.getLogger(__name__)


@dataclass
class NodeHardware:
    cpu_cores: float = 0.0
    memory_total_gb: float = 0.0
    link_capacity_mbps: float = 1000.0


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
    baseline_cpu: float | None = None
    baseline_mem: float | None = None
    cpu_cores: int | None = None
    memory_total_gb: float | None = None
    limit_cpu: int | None = None
    limit_mem: int | None = None
    limit_network: int | None = None
    cpu_power_ratio: float | None = None
    mem_power_ratio: float | None = None

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
            "baseline_cpu": self.baseline_cpu,
            "baseline_mem": self.baseline_mem,
            "cpu_cores": self.cpu_cores,
            "memory_total_gb": self.memory_total_gb,
            "limit_cpu": self.limit_cpu,
            "limit_mem": self.limit_mem,
            "limit_network": self.limit_network,
            "peak_active_share": float(settings.HIVE_CAPACITY_PEAK_ACTIVE_SHARE),
            "cpu_power_ratio": self.cpu_power_ratio,
            "mem_power_ratio": self.mem_power_ratio,
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


def _resolve_link_capacity_mbps(load: dict | None, cell: HiveCell | None) -> float:
    queen_default = float(settings.HIVE_LINK_CAPACITY_MBPS)
    agent = float((load or {}).get("network_link_capacity_mbps") or 0)
    if cell is not None and cell.link_capacity_mbps and float(cell.link_capacity_mbps) > 0:
        return float(cell.link_capacity_mbps)
    if cell is not None and cell.is_queen:
        return agent if agent > 0 else queen_default
    if cell is not None and not cell.is_queen:
        if agent > queen_default:
            return agent
        return float(settings.HIVE_CELL_DEFAULT_LINK_CAPACITY_MBPS)  # 1 Гбит по умолчанию
    return agent if agent > 0 else queen_default


def _resolve_link_capacity_for_capacity(load: dict | None, cell: HiveCell | None) -> float:
    """Канал для расчёта ёмкости: БД соты → sysfs → env."""
    if cell is not None and not cell.is_queen:
        db_link = float(cell.link_capacity_mbps or 0)
        if db_link > 0:
            return db_link
        m = re.search(r"(\d+)", cell.name or "", re.I)
        if m and int(m.group(1)) == 1:
            return float(settings.HIVE_CELL_FIRST_LINK_CAPACITY_MBPS)
        return float(settings.HIVE_CELL_DEFAULT_LINK_CAPACITY_MBPS)
    load = load or {}
    sysfs = float(load.get("network_link_sysfs_mbps") or 0)
    if sysfs > 0:
        return sysfs
    return _resolve_link_capacity_mbps(load, cell)


def _worker_link_online_scale(cell_hw: NodeHardware) -> float:
    """1 Гбит ≈ 10% от эталона 10 Гбит — лимит онлайн масштабируется."""
    premium = float(settings.HIVE_CELL_FIRST_LINK_CAPACITY_MBPS)
    link = cell_hw.link_capacity_mbps
    if link <= 0 or premium <= 0:
        return 1.0
    return max(0.1, min(10.0, link / premium))


def _scale_worker_profile(profile: CapacityProfile, cell_hw: NodeHardware) -> CapacityProfile:
    scale = _worker_link_online_scale(cell_hw)
    if abs(scale - 1.0) < 0.01:
        return profile
    new_max = max(1, int(round(profile.max_online * scale)))
    limits = dict(
        cpu=profile.limit_cpu,
        memory=profile.limit_mem,
        network=profile.limit_network,
    )
    if limits.get("network"):
        limits["network"] = max(1, int(round(limits["network"] * scale)))
    bottleneck = profile.bottleneck
    if limits.get("network") and limits["network"] <= new_max:
        bottleneck = "network"
    return CapacityProfile(
        max_online=new_max,
        bottleneck=bottleneck,
        mode=profile.mode,
        samples_count=profile.samples_count,
        per_user_cpu_p95=profile.per_user_cpu_p95,
        per_user_mem_p95=profile.per_user_mem_p95,
        per_user_mbps_p95=profile.per_user_mbps_p95,
        link_capacity_mbps=profile.link_capacity_mbps,
        baseline_cpu=profile.baseline_cpu,
        baseline_mem=profile.baseline_mem,
        cpu_cores=profile.cpu_cores,
        memory_total_gb=profile.memory_total_gb,
        limit_cpu=limits.get("cpu"),
        limit_mem=limits.get("memory"),
        limit_network=limits.get("network"),
        cpu_power_ratio=profile.cpu_power_ratio,
        mem_power_ratio=profile.mem_power_ratio,
    )


def _hardware_from_load(load: dict | None, cell: HiveCell | None = None) -> NodeHardware:
    load = load or {}
    cores = float(load.get("cpu_cores") or 0)
    ram_gb = float(load.get("memory_total_gb") or 0)
    link = _resolve_link_capacity_for_capacity(load, cell)
    return NodeHardware(
        cpu_cores=cores if cores > 0 else 0.0,
        memory_total_gb=ram_gb if ram_gb > 0 else 0.0,
        link_capacity_mbps=link,
    )


def _hardware_ratios(cell: NodeHardware, queen: NodeHardware) -> tuple[float, float, float]:
    default_cpu = float(settings.HIVE_CELL_CPU_POWER_RATIO_DEFAULT)
    default_mem = float(settings.HIVE_CELL_MEM_POWER_RATIO_DEFAULT)

    if cell.cpu_cores > 0 and queen.cpu_cores > 0:
        cpu_r = max(0.05, min(1.0, cell.cpu_cores / queen.cpu_cores))
    else:
        cpu_r = default_cpu

    if cell.memory_total_gb > 0 and queen.memory_total_gb > 0:
        mem_r = max(0.05, min(1.0, cell.memory_total_gb / queen.memory_total_gb))
    else:
        mem_r = default_mem

    if queen.link_capacity_mbps > 0:
        net_r = max(0.05, cell.link_capacity_mbps / queen.link_capacity_mbps)
    else:
        net_r = 1.0

    return cpu_r, mem_r, net_r


def _samples_for_current_hardware(
    samples: list[HiveLoadSample],
    hardware: NodeHardware,
) -> list[HiveLoadSample]:
    """Замеры с другого железа не участвуют в лимите — при смене VPS пересчёт сразу."""
    if not samples:
        return []
    link = hardware.link_capacity_mbps
    cores = int(hardware.cpu_cores) if hardware.cpu_cores > 0 else 0
    ram = float(hardware.memory_total_gb) if hardware.memory_total_gb > 0 else 0.0

    def _matches(s: HiveLoadSample) -> bool:
        if link > 0:
            sl = float(s.link_capacity_mbps or 0)
            if sl > 0 and abs(sl - link) / max(link, 1) > 0.15:
                return False
        if cores > 0 and s.cpu_cores is not None and int(s.cpu_cores) > 0:
            if int(s.cpu_cores) != cores:
                return False
        if ram > 0 and s.memory_total_gb is not None and float(s.memory_total_gb) > 0:
            if abs(float(s.memory_total_gb) - ram) > 0.6:
                return False
        return True

    return [s for s in samples if _matches(s)]


def _baseline_metric(samples: list[HiveLoadSample], attr: str) -> float:
    idle = [float(getattr(s, attr) or 0) for s in samples if s.online_count <= 1]
    if len(idle) >= 3:
        return float(_percentile(idle, 25) or 0)
    all_vals = [float(getattr(s, attr) or 0) for s in samples]
    if not all_vals:
        return 0.0
    return float(_percentile(all_vals, 10) or 0)


def _limits_from_typicals(
    typ_cpu: float,
    typ_mem: float,
    typ_mbps: float,
    *,
    baseline_cpu: float,
    baseline_mem: float,
    baseline_net: float,
    link_capacity_mbps: float,
) -> tuple[int, str, dict[str, int]]:
    share = max(0.05, min(1.0, float(settings.HIVE_CAPACITY_PEAK_ACTIVE_SHARE)))
    budget_cpu = max(0.15, typ_cpu * share)
    budget_mem = max(0.05, typ_mem * share)
    budget_mbps = max(0.0005, typ_mbps * share)

    headroom_cpu = max(1.0, float(settings.HIVE_CPU_PERCENT_THRESHOLD) - baseline_cpu)
    headroom_mem = max(1.0, float(settings.HIVE_MEM_PERCENT_THRESHOLD) - baseline_mem)
    target_mbps = link_capacity_mbps * (settings.HIVE_BANDWIDTH_PERCENT_THRESHOLD / 100.0)
    headroom_net = max(0.001, target_mbps - baseline_net)

    limits = {
        "cpu": max(1, int(headroom_cpu / budget_cpu)),
        "memory": max(1, int(headroom_mem / budget_mem)),
        "network": max(1, int(headroom_net / budget_mbps)),
    }
    bottleneck = min(limits, key=limits.get)
    return limits[bottleneck], bottleneck, limits


def _profile_from_limits(
    *,
    max_online: int,
    bottleneck: str,
    mode: str,
    samples_count: int,
    typ_cpu: float | None,
    typ_mem: float | None,
    typ_mbps: float | None,
    link_capacity_mbps: float,
    baseline_cpu: float,
    baseline_mem: float,
    limits: dict[str, int],
    hardware: NodeHardware,
    cpu_power_ratio: float | None = None,
    mem_power_ratio: float | None = None,
) -> CapacityProfile:
    return CapacityProfile(
        max_online=max_online,
        bottleneck=bottleneck,
        mode=mode,
        samples_count=samples_count,
        per_user_cpu_p95=round(typ_cpu, 2) if typ_cpu is not None else None,
        per_user_mem_p95=round(typ_mem, 2) if typ_mem is not None else None,
        per_user_mbps_p95=round(typ_mbps, 4) if typ_mbps is not None else None,
        link_capacity_mbps=link_capacity_mbps,
        baseline_cpu=round(baseline_cpu, 2),
        baseline_mem=round(baseline_mem, 2),
        cpu_cores=int(hardware.cpu_cores) if hardware.cpu_cores > 0 else None,
        memory_total_gb=round(hardware.memory_total_gb, 1) if hardware.memory_total_gb > 0 else None,
        limit_cpu=limits.get("cpu"),
        limit_mem=limits.get("memory"),
        limit_network=limits.get("network"),
        cpu_power_ratio=round(cpu_power_ratio, 2) if cpu_power_ratio is not None else None,
        mem_power_ratio=round(mem_power_ratio, 2) if mem_power_ratio is not None else None,
    )


def fallback_max_online(hardware: NodeHardware) -> int:
    util = max(0.01, float(settings.HIVE_LINK_TARGET_UTILIZATION_PERCENT) / 100.0)
    per_user_mbps = max(0.01, float(settings.HIVE_TARGET_ACTIVE_USER_MBPS))
    per_user_cpu = max(0.5, float(settings.HIVE_CAPACITY_FALLBACK_CPU_PER_USER))
    share = max(0.05, float(settings.HIVE_CAPACITY_PEAK_ACTIVE_SHARE))
    link = hardware.link_capacity_mbps
    by_net = int((link * util) // (per_user_mbps * share))
    cpu_scale = max(0.2, hardware.cpu_cores / 4.0) if hardware.cpu_cores > 0 else 1.0
    mem_scale = max(0.2, hardware.memory_total_gb / 8.0) if hardware.memory_total_gb > 0 else 1.0
    by_cpu = int((settings.HIVE_CPU_PERCENT_THRESHOLD * cpu_scale) // (per_user_cpu * share))
    by_mem = int(
        (settings.HIVE_MEM_PERCENT_THRESHOLD * mem_scale)
        // (max(0.1, settings.HIVE_CAPACITY_FALLBACK_MEM_PER_USER) * share)
    )
    return max(1, min(by_net, by_cpu, by_mem))


def _live_max_online_from_snapshot(
    online_count: int,
    load: dict,
    *,
    hardware: NodeHardware,
    baseline_cpu: float,
    baseline_mem: float,
    baseline_net: float,
) -> tuple[int, str, dict[str, int]]:
    """Лимит прямо сейчас: (нагрузка − фон) / онлайн → сколько ещё влезет в железо."""
    cpu = float(load.get("cpu_percent") or 0)
    mem = float(load.get("memory_percent") or 0)
    net_mbps = _network_mbps(load)
    per_cpu = max(0.15, (cpu - baseline_cpu) / online_count)
    per_mem = max(0.05, (mem - baseline_mem) / online_count)
    per_net = max(0.0005, (net_mbps - baseline_net) / online_count)
    return _limits_from_typicals(
        per_cpu,
        per_mem,
        per_net,
        baseline_cpu=baseline_cpu,
        baseline_mem=baseline_mem,
        baseline_net=baseline_net,
        link_capacity_mbps=hardware.link_capacity_mbps,
    )


def _blend_live_capacity(
    profile: CapacityProfile,
    *,
    online_count: int,
    load: dict | None,
    hardware: NodeHardware,
    samples: list[HiveLoadSample],
) -> CapacityProfile:
    """Смешивает историю (сэмплы) с текущим снимком нагрузки — лимит меняется каждые 10 с."""
    min_live = max(1, int(settings.HIVE_CAPACITY_MIN_ONLINE_FOR_LIVE))
    if online_count < min_live or not load:
        return profile

    if samples:
        b_cpu = _baseline_metric(samples, "cpu_percent")
        b_mem = _baseline_metric(samples, "memory_percent")
        b_net = _baseline_metric(samples, "network_mbps")
    else:
        b_cpu = min(float(load.get("cpu_percent") or 0), 12.0)
        b_mem = min(float(load.get("memory_percent") or 0), 20.0)
        b_net = 0.0

    live_max, live_bn, live_limits = _live_max_online_from_snapshot(
        online_count,
        load,
        hardware=hardware,
        baseline_cpu=b_cpu,
        baseline_mem=b_mem,
        baseline_net=b_net,
    )

    weight = max(0.0, min(1.0, float(settings.HIVE_CAPACITY_LIVE_WEIGHT)))
    if profile.mode in ("fallback", "estimated") or profile.samples_count < int(
        settings.HIVE_CAPACITY_MIN_SAMPLES
    ):
        blended = live_max
        mode = "live"
    elif weight >= 0.99:
        blended = live_max
        mode = "live"
    else:
        blended = max(1, int(round((1.0 - weight) * profile.max_online + weight * live_max)))
        mode = "adaptive+live"

    bottleneck = live_bn if live_max <= profile.max_online else profile.bottleneck
    limits = {
        "cpu": live_limits.get("cpu", profile.limit_cpu),
        "memory": live_limits.get("memory", profile.limit_mem),
        "network": live_limits.get("network", profile.limit_network),
    }
    if profile.limit_cpu is not None:
        limits["cpu"] = min(limits["cpu"], profile.limit_cpu) if mode != "live" else live_limits["cpu"]
    if profile.limit_mem is not None:
        limits["memory"] = (
            min(limits["memory"], profile.limit_mem) if mode != "live" else live_limits["memory"]
        )
    if profile.limit_network is not None:
        limits["network"] = (
            min(limits["network"], profile.limit_network) if mode != "live" else live_limits["network"]
        )

    return CapacityProfile(
        max_online=blended,
        bottleneck=bottleneck,
        mode=mode,
        samples_count=profile.samples_count,
        per_user_cpu_p95=profile.per_user_cpu_p95,
        per_user_mem_p95=profile.per_user_mem_p95,
        per_user_mbps_p95=profile.per_user_mbps_p95,
        link_capacity_mbps=profile.link_capacity_mbps,
        baseline_cpu=round(b_cpu, 2),
        baseline_mem=round(b_mem, 2),
        cpu_cores=profile.cpu_cores,
        memory_total_gb=profile.memory_total_gb,
        limit_cpu=limits.get("cpu"),
        limit_mem=limits.get("memory"),
        limit_network=limits.get("network"),
        cpu_power_ratio=profile.cpu_power_ratio,
        mem_power_ratio=profile.mem_power_ratio,
    )


def compute_max_online_from_samples(
    samples: list[HiveLoadSample],
    *,
    hardware: NodeHardware,
) -> CapacityProfile:
    min_samples = max(1, int(settings.HIVE_CAPACITY_MIN_SAMPLES))
    min_online = max(1, int(settings.HIVE_CAPACITY_MIN_ONLINE_FOR_LEARN))
    p = float(settings.HIVE_CAPACITY_PERCENTILE)
    link_cap = hardware.link_capacity_mbps

    samples = _samples_for_current_hardware(samples, hardware)
    usable = [s for s in samples if s.online_count >= min_online]
    if len(usable) < min_samples:
        cap = fallback_max_online(hardware)
        return CapacityProfile(
            max_online=cap,
            bottleneck="fallback",
            mode="fallback",
            samples_count=len(samples),
            per_user_cpu_p95=None,
            per_user_mem_p95=None,
            per_user_mbps_p95=None,
            link_capacity_mbps=link_cap,
            cpu_cores=int(hardware.cpu_cores) if hardware.cpu_cores > 0 else None,
            memory_total_gb=round(hardware.memory_total_gb, 1) if hardware.memory_total_gb > 0 else None,
        )

    baseline_cpu = _baseline_metric(samples, "cpu_percent")
    baseline_mem = _baseline_metric(samples, "memory_percent")
    baseline_net = _baseline_metric(samples, "network_mbps")

    cpu_marginal: list[float] = []
    mem_marginal: list[float] = []
    mbps_marginal: list[float] = []
    for s in usable:
        n = max(1, s.online_count)
        cpu_marginal.append(max(0.15, (float(s.cpu_percent) - baseline_cpu) / n))
        mem_marginal.append(max(0.05, (float(s.memory_percent) - baseline_mem) / n))
        mbps_marginal.append(max(0.0005, (float(s.network_mbps) - baseline_net) / n))

    typ_cpu = _percentile(cpu_marginal, p) or float(settings.HIVE_CAPACITY_FALLBACK_CPU_PER_USER)
    typ_mem = _percentile(mem_marginal, p) or float(settings.HIVE_CAPACITY_FALLBACK_MEM_PER_USER)
    typ_mbps = _percentile(mbps_marginal, p) or max(0.001, float(settings.HIVE_TARGET_ACTIVE_USER_MBPS))

    max_online, bottleneck, limits = _limits_from_typicals(
        typ_cpu,
        typ_mem,
        typ_mbps,
        baseline_cpu=baseline_cpu,
        baseline_mem=baseline_mem,
        baseline_net=baseline_net,
        link_capacity_mbps=link_cap,
    )

    return _profile_from_limits(
        max_online=max_online,
        bottleneck=bottleneck,
        mode="adaptive",
        samples_count=len(usable),
        typ_cpu=typ_cpu,
        typ_mem=typ_mem,
        typ_mbps=typ_mbps,
        link_capacity_mbps=link_cap,
        baseline_cpu=baseline_cpu,
        baseline_mem=baseline_mem,
        limits=limits,
        hardware=hardware,
        cpu_power_ratio=1.0,
        mem_power_ratio=1.0,
    )


def _estimate_worker_from_queen(
    cell_samples: list[HiveLoadSample],
    queen_profile: CapacityProfile,
    *,
    cell_hw: NodeHardware,
    queen_hw: NodeHardware,
) -> CapacityProfile:
    cpu_r, mem_r, _net_r = _hardware_ratios(cell_hw, queen_hw)
    baseline_cpu = _baseline_metric(cell_samples, "cpu_percent") if cell_samples else 0.0
    baseline_mem = _baseline_metric(cell_samples, "memory_percent") if cell_samples else 0.0
    baseline_net = _baseline_metric(cell_samples, "network_mbps") if cell_samples else 0.0

    typ_cpu = queen_profile.per_user_cpu_p95 or float(settings.HIVE_CAPACITY_FALLBACK_CPU_PER_USER)
    typ_mem = queen_profile.per_user_mem_p95 or float(settings.HIVE_CAPACITY_FALLBACK_MEM_PER_USER)
    typ_mbps = queen_profile.per_user_mbps_p95 or max(0.001, float(settings.HIVE_TARGET_ACTIVE_USER_MBPS))

    # Слабее CPU/RAM на соте → тот же юзер даёт больший % загрузки
    typ_cpu_cell = typ_cpu / cpu_r
    typ_mem_cell = typ_mem / mem_r

    max_online, bottleneck, limits = _limits_from_typicals(
        typ_cpu_cell,
        typ_mem_cell,
        typ_mbps,
        baseline_cpu=baseline_cpu,
        baseline_mem=baseline_mem,
        baseline_net=baseline_net,
        link_capacity_mbps=cell_hw.link_capacity_mbps,
    )

    # CPU/RAM: сота не может вместить больше пропорционально железу, чем Улей
    if queen_profile.limit_cpu:
        limits["cpu"] = min(limits["cpu"], max(1, int(queen_profile.limit_cpu * cpu_r)))
    if queen_profile.limit_mem:
        limits["memory"] = min(limits["memory"], max(1, int(queen_profile.limit_mem * mem_r)))
    # Канал: своя ширина (10 Гбит на соте vs 1 Гбит на Улье) — не режем по Улью
    bottleneck = min(limits, key=limits.get)
    max_online = limits[bottleneck]

    usable = [s for s in cell_samples if s.online_count >= 1]
    return _profile_from_limits(
        max_online=max_online,
        bottleneck=bottleneck,
        mode="estimated",
        samples_count=len(usable) or len(cell_samples),
        typ_cpu=typ_cpu_cell,
        typ_mem=typ_mem_cell,
        typ_mbps=typ_mbps,
        link_capacity_mbps=cell_hw.link_capacity_mbps,
        baseline_cpu=baseline_cpu,
        baseline_mem=baseline_mem,
        limits=limits,
        hardware=cell_hw,
        cpu_power_ratio=cpu_r,
        mem_power_ratio=mem_r,
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
    online_count: int | None = None,
) -> CapacityProfile:
    if online_count is None:
        from app.services.hive_service import count_online_on_cell

        online_count = await count_online_on_cell(db, cell.id)

    samples = await fetch_recent_samples(db, cell.id)
    hardware = _hardware_from_load(load, cell)
    profile = compute_max_online_from_samples(samples, hardware=hardware)

    if profile.mode == "fallback" and not cell.is_queen:
        from app.services.hive_service import get_queen_cell

        queen = await get_queen_cell(db)
        if queen and queen.id != cell.id:
            _, queen_load = queen_accepting_new_vpn()
            queen_hw = _hardware_from_load(queen_load, queen)
            queen_samples = await fetch_recent_samples(db, queen.id)
            queen_profile = compute_max_online_from_samples(queen_samples, hardware=queen_hw)
            if queen_profile.mode == "adaptive":
                profile = _estimate_worker_from_queen(
                    samples,
                    queen_profile,
                    cell_hw=hardware,
                    queen_hw=queen_hw,
                )

    if not cell.is_queen:
        profile = _scale_worker_profile(profile, hardware)

    profile = _blend_live_capacity(
        profile,
        online_count=online_count,
        load=load,
        hardware=hardware,
        samples=samples,
    )

    configured = int(cell.max_clients or 0)
    if configured > 0:
        capped = min(configured, profile.max_online)
        return CapacityProfile(
            max_online=max(1, capped),
            bottleneck=profile.bottleneck if profile.mode in ("adaptive", "estimated") else "manual_cap",
            mode="manual_cap" if capped < profile.max_online else profile.mode,
            samples_count=profile.samples_count,
            per_user_cpu_p95=profile.per_user_cpu_p95,
            per_user_mem_p95=profile.per_user_mem_p95,
            per_user_mbps_p95=profile.per_user_mbps_p95,
            link_capacity_mbps=profile.link_capacity_mbps,
            baseline_cpu=profile.baseline_cpu,
            baseline_mem=profile.baseline_mem,
            cpu_cores=profile.cpu_cores,
            memory_total_gb=profile.memory_total_gb,
            limit_cpu=profile.limit_cpu,
            limit_mem=profile.limit_mem,
            limit_network=profile.limit_network,
            cpu_power_ratio=profile.cpu_power_ratio,
            mem_power_ratio=profile.mem_power_ratio,
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
    *,
    cell: HiveCell | None = None,
) -> None:
    hw = _hardware_from_load(load, cell)
    sample = HiveLoadSample(
        cell_id=cell_id,
        sampled_at=datetime.utcnow(),
        online_count=max(0, int(online_count)),
        cpu_percent=round(float(load.get("cpu_percent") or 0), 2),
        memory_percent=round(float(load.get("memory_percent") or 0), 2),
        network_mbps=round(_network_mbps(load), 4),
        network_util_percent=round(float(load.get("network_util_percent") or 0), 2),
        link_capacity_mbps=round(hw.link_capacity_mbps, 1),
        cpu_cores=int(hw.cpu_cores) if hw.cpu_cores > 0 else None,
        memory_total_gb=round(hw.memory_total_gb, 1) if hw.memory_total_gb > 0 else None,
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
    queen = await ensure_queen_cell(db)
    queen_load = {
        **queen_load,
        "network_link_capacity_mbps": _resolve_link_capacity_mbps(queen_load, queen),
    }
    for cell in cells:
        online = await count_online_on_cell(db, cell.id)
        if cell.is_queen:
            load = queen_load
        else:
            load = await fetch_worker_cell_load(cell)
            if not load:
                continue
        await record_sample(db, cell.id, online, load, cell=cell)


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
            push_incident(
                source="hive.capacity-sampler",
                severity="warning",
                message=f"Hive capacity sample cycle failed: {e}",
            )
        await asyncio.sleep(interval)


def start_hive_capacity_sampler() -> asyncio.Task:
    return asyncio.create_task(capacity_sampler_loop())
