"""Host CPU model and frequency for admin dashboard."""
from __future__ import annotations

import glob
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


def _read_sysfs_current_mhz() -> list[float]:
    """Live per-core frequency from cpufreq (kHz -> MHz). Fresh read every call."""
    values: list[float] = []
    for path in sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")):
        try:
            with open(path, encoding="utf-8") as f:
                values.append(int(f.read().strip()) / 1000.0)
        except (OSError, ValueError):
            continue
    return values


def _read_proc_current_mhz() -> list[float]:
    """Per-core MHz from /proc/cpuinfo — kernel updates under load (no psutil cache)."""
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


def _live_current_mhz() -> float | None:
    """
    Current operating frequency: prefer sysfs, then /proc/cpuinfo.
    Use max across cores (turbo / busiest core), not average with nominal.
    """
    samples = _read_sysfs_current_mhz() or _read_proc_current_mhz()
    if samples:
        return max(samples)

    # Last resort only — never use .max (nominal cap), only .current
    try:
        per = psutil.cpu_freq(percpu=True)
        if per:
            currents = [float(p.current) for p in per if p and p.current and p.current > 0]
            if currents:
                return max(currents)
    except Exception:
        pass
    return None


def get_cpu_info() -> dict:
    model = _read_cpu_model()
    base_mhz = _parse_base_mhz_from_model(model)
    current_mhz = _live_current_mhz()

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
