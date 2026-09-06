"""Host CPU model and frequency for admin dashboard."""
from __future__ import annotations

import glob
import re
import time

import psutil


def _read_cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def _parse_base_mhz_from_model(model: str) -> float | None:
    if not model:
        return None
    m = re.search(r"@\s*([\d.]+)\s*GHz", model, re.I)
    if m:
        return float(m.group(1)) * 1000.0
    m = re.search(r"@\s*([\d.]+)\s*MHz", model, re.I)
    if m:
        return float(m.group(1))
    return None


def _has_cpufreq_sysfs() -> bool:
    return bool(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"))


def _read_sysfs_current_mhz() -> list[float]:
    values: list[float] = []
    for path in sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")):
        try:
            with open(path, encoding="utf-8") as f:
                values.append(int(f.read().strip()) / 1000.0)
        except (OSError, ValueError):
            continue
    return values


def _read_proc_current_mhz() -> list[float]:
    values: list[float] = []
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("cpu MHz"):
                    try:
                        values.append(float(line.split(":", 1)[1].strip()))
                    except ValueError:
                        continue
    except OSError:
        pass
    return values


def _hardware_mhz_live() -> tuple[float | None, bool]:
    """
    True if the host exposes changing CPU frequency (cpufreq sysfs or varying cpu MHz).
    QEMU/KVM often reports a fixed cpu MHz — then live=False.
    """
    if _has_cpufreq_sysfs():
        samples = _read_sysfs_current_mhz()
        return (max(samples) if samples else None), True

    first = _read_proc_current_mhz()
    time.sleep(0.15)
    second = _read_proc_current_mhz()
    combined = (first or []) + (second or [])
    if not combined:
        return None, False

    spread = max(combined) - min(combined)
    if spread >= 5.0:
        return max(combined), True

    return max(combined), False


def _estimate_mhz_from_load(base_mhz: float, cpu_percent: float) -> float:
    """When VM hides cpufreq, scale between idle floor and nominal by CPU load."""
    base = base_mhz or 2300.0
    load = max(0.0, min(100.0, float(cpu_percent))) / 100.0
    min_mhz = base * 0.48
    return min_mhz + (base - min_mhz) * load


def get_cpu_info(cpu_percent: float = 0.0) -> dict:
    model = _read_cpu_model()
    base_mhz = _parse_base_mhz_from_model(model)

    if base_mhz is None:
        try:
            with open(
                "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq",
                encoding="utf-8",
            ) as f:
                base_mhz = int(f.read().strip()) / 1000.0
        except OSError:
            pass

    hw_mhz, hw_live = _hardware_mhz_live()
    # На KVM/QEMU живой cpufreq часто нет — оценка «по загрузке» вводит в заблуждение.
    # В дашборд отдаём текущую частоту только если железо реально её меняет.
    if hw_live and hw_mhz is not None:
        current_mhz = hw_mhz
        estimated = False
    else:
        current_mhz = None
        estimated = True

    cores = psutil.cpu_count(logical=True) or 1

    return {
        "cpu_model": model or None,
        "cpu_cores": cores,
        "cpu_freq_base_mhz": round(base_mhz, 1) if base_mhz else None,
        "cpu_freq_current_mhz": round(current_mhz, 1) if current_mhz else None,
        "cpu_freq_estimated": estimated,
    }
