"""Метрики нагрузки Улья / сот для балансировки VPN."""
from __future__ import annotations

import logging

from app.config import settings
from app.services.build_agent_service import is_build_running
from app.services.proc_stats import read_host_load

logger = logging.getLogger(__name__)


def is_vpn_overloaded(load: dict) -> bool:
    """Перегрузка для VPN: CPU или RAM или канал выше порога."""
    cpu = float(load.get("cpu_percent") or 0)
    mem = float(load.get("memory_percent") or 0)
    net = float(load.get("network_util_percent") or 0)
    return (
        cpu >= settings.HIVE_CPU_PERCENT_THRESHOLD
        or mem >= settings.HIVE_MEM_PERCENT_THRESHOLD
        or net >= settings.HIVE_BANDWIDTH_PERCENT_THRESHOLD
    )


def queen_accepting_new_vpn(*, load: dict | None = None) -> tuple[bool, dict]:
    """
    Улей принимает новые VPN-сессии?
    False → направлять новых на соты (если есть).
    Сборка build-agent в полночь не считается VPN-перегрузкой.
    """
    if is_build_running():
        snap = load or read_host_load(cpu_interval=0.1)
        return True, {**snap, "build_running": True, "vpn_overloaded": False}

    snap = load or read_host_load()
    overloaded = is_vpn_overloaded(snap)
    return not overloaded, {
        **snap,
        "build_running": False,
        "vpn_overloaded": overloaded,
    }
