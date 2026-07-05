"""Метрики нагрузки Улья / сот для балансировки VPN."""
from __future__ import annotations

import logging
import time

from app.config import settings
from app.services.build_agent_service import is_build_running
from app.services.proc_stats import read_host_load

logger = logging.getLogger(__name__)

_queen_cool_since: float | None = None
_queen_was_overloaded: bool = False


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


def is_vpn_cooled(load: dict) -> bool:
    """Нода остыла — ниже порогов с гистерезисом."""
    cpu = float(load.get("cpu_percent") or 0)
    mem = float(load.get("memory_percent") or 0)
    net = float(load.get("network_util_percent") or 0)
    return (
        cpu < settings.HIVE_COOLDOWN_CPU_PERCENT
        and mem < settings.HIVE_COOLDOWN_MEM_PERCENT
        and net < settings.HIVE_COOLDOWN_NET_PERCENT
    )


def load_stress_score(load: dict | None) -> float:
    """Сводный score нагрузки (выше = хуже) для выбора цели переноса."""
    if not load:
        return 0.0
    cpu = float(load.get("cpu_percent") or 0)
    mem = float(load.get("memory_percent") or 0)
    net = float(load.get("network_util_percent") or 0)
    return max(
        cpu / max(1.0, settings.HIVE_CPU_PERCENT_THRESHOLD),
        mem / max(1.0, settings.HIVE_MEM_PERCENT_THRESHOLD),
        net / max(1.0, settings.HIVE_BANDWIDTH_PERCENT_THRESHOLD),
    )


def queen_accepting_new_vpn(*, load: dict | None = None) -> tuple[bool, dict]:
    """
    Улей принимает новые VPN-сессии?
    False → направлять новых на соты (если есть).
    Сборка build-agent в полночь не считается VPN-перегрузкой.
    """
    global _queen_cool_since, _queen_was_overloaded

    if is_build_running():
        snap = load or read_host_load(cpu_interval=0.1)
        _queen_was_overloaded = False
        _queen_cool_since = None
        return True, {**snap, "build_running": True, "vpn_overloaded": False}

    snap = load or read_host_load()
    overloaded = is_vpn_overloaded(snap)
    if overloaded:
        _queen_was_overloaded = True
        _queen_cool_since = None
    elif is_vpn_cooled(snap):
        if _queen_cool_since is None:
            _queen_cool_since = time.monotonic()
    else:
        _queen_cool_since = None

    return not overloaded, {
        **snap,
        "build_running": False,
        "vpn_overloaded": overloaded,
    }


def queen_recovered_stable() -> bool:
    """Улей был перегружен и остыл достаточно долго — можно возвращать офлайн-устройства."""
    if not _queen_was_overloaded:
        return False
    if _queen_cool_since is None:
        return False
    stable = max(30, int(settings.HIVE_COOLDOWN_STABLE_SEC))
    return (time.monotonic() - _queen_cool_since) >= stable


def queen_vpn_spill_threshold(cap: int) -> int:
    """Порог онлайн на Улье: ниже — новых и офлайн не отправляем на соты (даже при всплеске CPU)."""
    if cap <= 0:
        return 1_000_000
    by_fraction = int(cap * float(settings.HIVE_SPILL_ONLINE_FRACTION))
    return max(int(settings.HIVE_SPILL_MIN_QUEEN_ONLINE), by_fraction, 1)


def queen_vpn_has_headroom(online: int, cap: int) -> bool:
    return int(online) < queen_vpn_spill_threshold(cap)


def reset_queen_cooldown_state() -> None:
    global _queen_cool_since, _queen_was_overloaded
    _queen_cool_since = None
    _queen_was_overloaded = False
