"""CPU/RAM хоста — не контейнера API (через /host/proc или docker.sock)."""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)


def _proc_paths() -> tuple[str, str]:
    """Корень proc: сначала смонтированный хост, иначе локальный /proc."""
    for root in (os.environ.get("HOST_PROC_ROOT", "/host/proc"), "/proc"):
        if os.path.isfile(os.path.join(root, "stat")):
            return os.path.join(root, "stat"), os.path.join(root, "meminfo")
    return "/proc/stat", "/proc/meminfo"


def _memory_percent_from_meminfo(meminfo_path: str) -> float:
    total_kb = avail_kb = 0
    with open(meminfo_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                total_kb = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                avail_kb = int(line.split()[1])
    if total_kb <= 0:
        return 0.0
    used_pct = (1.0 - avail_kb / total_kb) * 100.0
    return round(max(0.0, min(100.0, used_pct)), 1)


def _cpu_times(stat_path: str) -> tuple[int, int]:
    with open(stat_path, encoding="utf-8", errors="replace") as f:
        parts = f.readline().split()
    vals = [int(x) for x in parts[1:]]
    idle = vals[3] + vals[4]
    return sum(vals), idle


def _cpu_percent_from_stat(stat_path: str, *, interval: float) -> float:
    t1, i1 = _cpu_times(stat_path)
    time.sleep(interval)
    t2, i2 = _cpu_times(stat_path)
    dt, di = t2 - t1, i2 - i1
    if dt <= 0:
        return 0.0
    pct = (1.0 - di / dt) * 100.0
    return round(max(0.0, min(100.0, pct)), 1)


def _load_via_proc_files(*, cpu_interval: float) -> dict | None:
    stat_path, mem_path = _proc_paths()
    # /proc внутри API-контейнера без mount — не подходит для Улья
    if stat_path == "/proc/stat" and not Path("/host/proc/stat").is_file():
        return None
    try:
        return {
            "cpu_percent": _cpu_percent_from_stat(stat_path, interval=cpu_interval),
            "memory_percent": _memory_percent_from_meminfo(mem_path),
        }
    except OSError as e:
        logger.debug("proc_stats files: %s", e)
        return None


def _load_via_docker_host(*, cpu_interval: float) -> dict | None:
    if not Path("/var/run/docker.sock").is_file():
        return None
    shell = f"""
read_cpu() {{
  set -- $(grep '^cpu ' /host/proc/stat)
  idle=$5
  iow=$6
  total=0
  for x in $2 $3 $4 $5 $6 $7 $8 $9; do total=$((total + x)); done
  echo "$total $((idle + iow))"
}}
set -- $(read_cpu); t1=$1; i1=$2
sleep {cpu_interval}
set -- $(read_cpu); t2=$1; i2=$2
dt=$((t2 - t1)); di=$((i2 - i1))
if [ "$dt" -gt 0 ]; then cpu=$(( (1000 * (dt - di) / dt + 5) / 10 )); else cpu=0; fi
mt=$(grep '^MemTotal:' /host/proc/meminfo | awk '{{print $2}}')
ma=$(grep '^MemAvailable:' /host/proc/meminfo | awk '{{print $2}}')
if [ -z "$mt" ] || [ "$mt" -le 0 ]; then mem=0
else mem=$(( (1000 * (mt - ma) / mt + 5) / 10 )); fi
echo "cpu=$cpu mem=$mem"
"""
    try:
        r = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", "/:/host:ro",
                "alpine:3.19",
                "sh", "-c", shell,
            ],
            capture_output=True,
            text=True,
            timeout=max(30.0, cpu_interval + 10.0),
        )
        if r.returncode != 0:
            return None
        cpu = mem = None
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("cpu="):
                cpu = float(line.split("=", 1)[1])
            elif line.startswith("mem="):
                mem = float(line.split("=", 1)[1])
        if cpu is None or mem is None:
            return None
        return {"cpu_percent": cpu, "memory_percent": mem}
    except Exception as e:
        logger.debug("proc_stats docker: %s", e)
        return None


logger = logging.getLogger(__name__)

_load_cache_at: float = 0.0
_load_cache_snap: dict | None = None
_LOAD_CACHE_TTL = 2.5


def read_host_load(*, cpu_interval: float = 0.25) -> dict:
    """Нагрузка VPS-хоста (для Улья в Docker)."""
    global _load_cache_at, _load_cache_snap
    now = time.monotonic()
    if _load_cache_snap is not None and (now - _load_cache_at) < _LOAD_CACHE_TTL:
        return dict(_load_cache_snap)

    for reader in (
        lambda: _load_via_proc_files(cpu_interval=cpu_interval),
        lambda: _load_via_docker_host(cpu_interval=cpu_interval),
    ):
        snap = reader()
        if snap is not None:
            _load_cache_at = time.monotonic()
            _load_cache_snap = snap
            return dict(snap)
    cpu = float(psutil.cpu_percent(interval=cpu_interval))
    mem = psutil.virtual_memory()
    snap = {
        "cpu_percent": round(cpu, 1),
        "memory_percent": round(float(mem.percent), 1),
    }
    _load_cache_at = time.monotonic()
    _load_cache_snap = snap
    return dict(snap)
