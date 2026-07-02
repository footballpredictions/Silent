"""CPU/RAM/канал хоста — не контейнера API (через /host/proc или docker.sock)."""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

import psutil
from app.config import settings

logger = logging.getLogger(__name__)

_IGNORE_IFACE_PREFIXES = ("lo", "docker", "veth", "br-", "wg", "tun", "tailscale")
_net_prev: dict | None = None


def _host_proc_root() -> str | None:
    for root in (os.environ.get("HOST_PROC_ROOT", "/host/proc"), "/host/proc", "/proc"):
        if os.path.isfile(os.path.join(root, "stat")):
            if root == "/proc" and not Path("/host/proc/stat").is_file():
                return None
            return root
    return None


def _proc_paths() -> tuple[str, str]:
    root = _host_proc_root() or "/proc"
    return os.path.join(root, "stat"), os.path.join(root, "meminfo")


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


def _is_ignored_iface(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n or n == "lo":
        return True
    return any(n.startswith(p) for p in _IGNORE_IFACE_PREFIXES)


def _detect_default_iface(proc_root: str) -> str | None:
    route_path = os.path.join(proc_root, "net", "route")
    try:
        with open(route_path, encoding="utf-8", errors="replace") as f:
            next(f, None)
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 4 and parts[1] == "00000000" and parts[3] != "0000":
                    iface = parts[0].strip()
                    if not _is_ignored_iface(iface):
                        return iface
    except OSError:
        pass
    return None


def _list_iface_bytes(proc_root: str) -> dict[str, tuple[int, int]]:
    dev_path = os.path.join(proc_root, "net", "dev")
    out: dict[str, tuple[int, int]] = {}
    try:
        with open(dev_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                row = line.strip()
                if not row or ":" not in row or row.startswith("face"):
                    continue
                name, rest = row.split(":", 1)
                iface = name.strip()
                if _is_ignored_iface(iface):
                    continue
                vals = rest.split()
                if len(vals) < 9:
                    continue
                out[iface] = (int(vals[0]), int(vals[8]))
    except OSError:
        pass
    return out


def _pick_wan_interface(proc_root: str) -> str | None:
    manual = (getattr(settings, "HIVE_NETWORK_INTERFACE", "") or "").strip()
    if manual:
        return manual
    route_iface = _detect_default_iface(proc_root)
    if route_iface:
        return route_iface
    stats = _list_iface_bytes(proc_root)
    if not stats:
        return None
    return max(stats.keys(), key=lambda k: stats[k][0] + stats[k][1])


def _net_bytes(proc_root: str, iface: str) -> tuple[int, int] | None:
    return _list_iface_bytes(proc_root).get(iface)


def _host_sys_root(proc_root: str) -> str:
    if proc_root.startswith("/host/proc"):
        return "/host/sys"
    return proc_root.replace("/proc", "/sys")


def _iface_speed_mbps(proc_root: str, iface: str) -> float:
    speed_path = os.path.join(_host_sys_root(proc_root), "class", "net", iface, "speed")
    try:
        raw = Path(speed_path).read_text(encoding="utf-8").strip()
        speed = float(raw)
        if speed > 0:
            return speed
    except Exception:
        pass
    return float(settings.HIVE_LINK_CAPACITY_MBPS)


def _network_rates(proc_root: str, iface: str) -> tuple[float, float, float]:
    """Скорость по дельте между вызовами (без sleep внутри запроса)."""
    global _net_prev
    counters = _net_bytes(proc_root, iface)
    if not counters:
        return 0.0, 0.0, 0.0
    now = time.monotonic()
    rx_mbps = tx_mbps = 0.0
    if (
        _net_prev
        and _net_prev.get("iface") == iface
        and _net_prev.get("proc_root") == proc_root
    ):
        dt = now - float(_net_prev.get("at") or 0)
        if dt >= 0.2:
            drx = counters[0] - int(_net_prev.get("rx") or 0)
            dtx = counters[1] - int(_net_prev.get("tx") or 0)
            if drx < 0:
                drx = 0
            if dtx < 0:
                dtx = 0
            rx_mbps = drx * 8.0 / dt / 1_000_000.0
            tx_mbps = dtx * 8.0 / dt / 1_000_000.0
    _net_prev = {
        "proc_root": proc_root,
        "iface": iface,
        "rx": counters[0],
        "tx": counters[1],
        "at": now,
    }
    cap = max(1.0, _iface_speed_mbps(proc_root, iface))
    util = min(100.0, (max(rx_mbps, tx_mbps) / cap) * 100.0)
    return round(rx_mbps, 3), round(tx_mbps, 3), round(util, 2)


def _network_stats(proc_root: str) -> dict:
    iface = _pick_wan_interface(proc_root) or ""
    if not iface:
        return {
            "network_interface": None,
            "network_mbps_rx": 0.0,
            "network_mbps_tx": 0.0,
            "network_util_percent": 0.0,
            "network_link_capacity_mbps": float(settings.HIVE_LINK_CAPACITY_MBPS),
        }
    rx_mbps, tx_mbps, util = _network_rates(proc_root, iface)
    return {
        "network_interface": iface,
        "network_mbps_rx": rx_mbps,
        "network_mbps_tx": tx_mbps,
        "network_util_percent": util,
        "network_link_capacity_mbps": round(_iface_speed_mbps(proc_root, iface), 1),
    }


def read_network_load() -> dict:
    """Только канал — одна дельта на вызов, без sleep."""
    proc_root = _host_proc_root()
    if not proc_root:
        return {
            "network_interface": (settings.HIVE_NETWORK_INTERFACE or "").strip() or None,
            "network_mbps_rx": 0.0,
            "network_mbps_tx": 0.0,
            "network_util_percent": 0.0,
            "network_link_capacity_mbps": float(settings.HIVE_LINK_CAPACITY_MBPS),
        }
    return _network_stats(proc_root)


def _load_via_proc_files(*, cpu_interval: float) -> dict | None:
    proc_root = _host_proc_root()
    if not proc_root:
        return None
    stat_path = os.path.join(proc_root, "stat")
    mem_path = os.path.join(proc_root, "meminfo")
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
dev="${{HIVE_NET_IFACE}}"
if [ -z "$dev" ]; then
  dev=$(awk '$2=="00000000" && $3!="00000000" {{print $1; exit}}' /host/proc/net/route)
fi
rx=0; tx=0; util=0; cap=${{HIVE_LINK_CAP}}
if [ -n "$dev" ]; then
  read rx1 tx1 < <(awk -F: -v d="$dev" '$1 ~ "^[[:space:]]*" d "[[:space:]]*$" {{gsub(/^[[:space:]]+|[[:space:]]+$/,"",$2); n=split($2,a); print a[1], a[9]}}' /host/proc/net/dev)
  sleep {cpu_interval}
  read rx2 tx2 < <(awk -F: -v d="$dev" '$1 ~ "^[[:space:]]*" d "[[:space:]]*$" {{gsub(/^[[:space:]]+|[[:space:]]+$/,"",$2); n=split($2,a); print a[1], a[9]}}' /host/proc/net/dev)
  drx=$((rx2-rx1)); dtx=$((tx2-tx1))
  if [ "$drx" -lt 0 ]; then drx=0; fi
  if [ "$dtx" -lt 0 ]; then dtx=0; fi
  rx=$(awk -v b="$drx" -v i="{cpu_interval}" 'BEGIN {{printf "%.1f", (b*8)/(i*1000000)}}')
  tx=$(awk -v b="$dtx" -v i="{cpu_interval}" 'BEGIN {{printf "%.1f", (b*8)/(i*1000000)}}')
  if [ -r "/host/sys/class/net/$dev/speed" ]; then
    sp=$(cat /host/sys/class/net/$dev/speed 2>/dev/null)
    if [ -n "$sp" ] && [ "$sp" -gt 0 ] 2>/dev/null; then cap=$sp; fi
  fi
  top=$(awk -v a="$rx" -v b="$tx" 'BEGIN {{if (a>b) print a; else print b}}')
  util=$(awk -v t="$top" -v c="$cap" 'BEGIN {{if (c<=0) print 0; else {{u=(t/c)*100; if(u>100)u=100; printf "%.1f", u}}}}')
fi
echo "cpu=$cpu mem=$mem iface=$dev rx=$rx tx=$tx util=$util cap=$cap"
"""
    try:
        r = subprocess.run(
            [
                "docker", "run", "--rm",
                "-e", f"HIVE_NET_IFACE={(settings.HIVE_NETWORK_INTERFACE or '').strip()}",
                "-e", f"HIVE_LINK_CAP={float(settings.HIVE_LINK_CAPACITY_MBPS)}",
                "-v", "/:/host:ro",
                "alpine:3.19",
                "sh", "-c", shell,
            ],
            capture_output=True,
            text=True,
            timeout=max(30.0, cpu_interval * 2 + 10.0),
        )
        if r.returncode != 0:
            logger.debug("proc_stats docker rc=%s stderr=%s", r.returncode, (r.stderr or "")[:200])
            return None
        cpu = mem = rx = tx = util = cap = None
        iface = None
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if "cpu=" in line:
                parts = dict(part.split("=", 1) for part in line.split() if "=" in part)
                cpu = float(parts.get("cpu", "0"))
                mem = float(parts.get("mem", "0"))
                rx = float(parts.get("rx", "0"))
                tx = float(parts.get("tx", "0"))
                util = float(parts.get("util", "0"))
                cap = float(parts.get("cap", str(settings.HIVE_LINK_CAPACITY_MBPS)))
                iface = parts.get("iface") or None
        if cpu is None or mem is None:
            return None
        return {
            "cpu_percent": cpu,
            "memory_percent": mem,
            "network_interface": iface,
            "network_mbps_rx": rx or 0.0,
            "network_mbps_tx": tx or 0.0,
            "network_util_percent": util or 0.0,
            "network_link_capacity_mbps": cap or float(settings.HIVE_LINK_CAPACITY_MBPS),
        }
    except Exception as e:
        logger.debug("proc_stats docker: %s", e)
        return None


_load_cache_at: float = 0.0
_load_cache_snap: dict | None = None
_LOAD_CACHE_TTL = 2.5


def _read_cpu_cores(proc_root: str | None = None) -> int:
    root = proc_root or _host_proc_root() or "/proc"
    path = os.path.join(root, "cpuinfo")
    try:
        count = 0
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("processor"):
                    count += 1
        return max(1, count)
    except OSError:
        return max(1, os.cpu_count() or 1)


def _read_memory_total_gb(proc_root: str | None = None) -> float:
    root = proc_root or _host_proc_root() or "/proc"
    path = os.path.join(root, "meminfo")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024 / 1024, 1)
    except OSError:
        pass
    try:
        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        return 0.0


def _host_hardware_meta() -> dict:
    proc_root = _host_proc_root()
    return {
        "cpu_cores": _read_cpu_cores(proc_root),
        "memory_total_gb": _read_memory_total_gb(proc_root),
    }


def read_host_load(*, cpu_interval: float = 0.25) -> dict:
    """Нагрузка VPS-хоста (для Улья в Docker)."""
    global _load_cache_at, _load_cache_snap
    now = time.monotonic()
    snap: dict | None = None
    if _load_cache_snap is not None and (now - _load_cache_at) < _LOAD_CACHE_TTL:
        snap = dict(_load_cache_snap)
    else:
        for reader in (
            lambda: _load_via_proc_files(cpu_interval=cpu_interval),
            lambda: _load_via_docker_host(cpu_interval=cpu_interval),
        ):
            loaded = reader()
            if loaded is not None:
                snap = dict(loaded)
                _load_cache_at = time.monotonic()
                _load_cache_snap = dict(loaded)
                break
        if snap is None:
            cpu = float(psutil.cpu_percent(interval=cpu_interval))
            mem = psutil.virtual_memory()
            snap = {
                "cpu_percent": round(cpu, 1),
                "memory_percent": round(float(mem.percent), 1),
            }

    return {**snap, **read_network_load(), **_host_hardware_meta()}
