"""Host CPU model and frequency for admin dashboard."""
from __future__ import annotations

import re

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


def _current_mhz_from_proc() -> float | None:
    values: list[float] = []
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("cpu MHz"):
                    values.append(float(line.split(":", 1)[1].strip()))
    except OSError:
        return None
    if not values:
        return None
    return sum(values) / len(values)


def _current_mhz_from_psutil() -> float | None:
    try:
        per = psutil.cpu_freq(percpu=True)
        if per:
            currents = [p.current for p in per if p and p.current and p.current > 0]
            if currents:
                return sum(currents) / len(currents)
        agg = psutil.cpu_freq()
        if agg and agg.current and agg.current > 0:
            return float(agg.current)
        if agg and agg.max and agg.max > 0:
            return float(agg.max)
    except Exception:
        pass
    return None


def get_cpu_info() -> dict:
    model = _read_cpu_model()
    base_mhz = _parse_base_mhz_from_model(model)
    current_mhz = _current_mhz_from_psutil() or _current_mhz_from_proc()

    if base_mhz is None:
        try:
            with open(
                "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq",
                encoding="utf-8",
            ) as f:
                base_mhz = int(f.read().strip()) / 1000.0
        except OSError:
            pass

    cores = psutil.cpu_count(logical=True) or 1

    return {
        "cpu_model": model or None,
        "cpu_cores": cores,
        "cpu_freq_base_mhz": round(base_mhz, 1) if base_mhz else None,
        "cpu_freq_current_mhz": round(current_mhz, 1) if current_mhz else None,
    }
