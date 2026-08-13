"""Снимок памяти прода: топ процессов, рост RSS, goroutine/задачи API (только чтение).

  cd backend
  python scripts/diag_memory.py [интервал_сек]

Делает два замера с интервалом и показывает дельту RSS — видно, что течёт.
"""
from __future__ import annotations

import io
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _deploy_common import connect, run  # noqa: E402

SNAP_CMD = "ps -eo pid,rss,etimes,comm --sort=-rss | head -20"

API_PROBE = r"""
import asyncio, gc, os, sys

try:
    import resource
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
except Exception:
    rss_mb = -1

loop_tasks = -1
try:
    loop_tasks = len(asyncio.all_tasks(asyncio.get_event_loop()))
except Exception:
    pass

print(f"api_max_rss_mb={rss_mb:.1f}")
print(f"gc_objects={len(gc.get_objects())}")
print(f"gc_counts={gc.get_count()}")
"""


def _parse(snapshot: str) -> dict[int, tuple[int, str]]:
    out: dict[int, tuple[int, str]] = {}
    for line in snapshot.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(\d+)\s+(\S+)", line)
        if m:
            out[int(m.group(1))] = (int(m.group(2)), m.group(4))
    return out


def main() -> None:
    gap = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    client = connect()
    first = _parse(run(client, SNAP_CMD))
    print(f"=== замер 1, ждём {gap}с ===")
    for pid, (rss, comm) in list(first.items())[:12]:
        print(f"  {comm:20s} pid={pid:<8} rss={rss/1024:8.1f} MB")

    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(API_PROBE.encode()), "/tmp/diag_mem_api.py")
    run(client, "docker cp /tmp/diag_mem_api.py backend-api-1:/tmp/diag_mem_api.py")
    print(run(client, "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/diag_mem_api.py"))

    time.sleep(gap)
    second = _parse(run(client, SNAP_CMD))
    print(f"=== замер 2 (+{gap}с), дельта RSS ===")
    rows = []
    for pid, (rss, comm) in second.items():
        prev = first.get(pid)
        delta = rss - prev[0] if prev else 0
        rows.append((delta, rss, pid, comm))
    for delta, rss, pid, comm in sorted(rows, reverse=True):
        mark = "  <== РАСТЁТ" if delta > 2048 else ""
        print(f"  {comm:20s} pid={pid:<8} rss={rss/1024:8.1f} MB  Δ{delta/1024:+8.2f} MB{mark}")

    print("=== systemd RSS/лимиты ===")
    print(run(client, "systemctl show wdtt -p MemoryCurrent -p MemoryMax -p MemoryHigh -p ActiveEnterTimestamp"))
    print(run(client, "docker stats --no-stream --format '{{.Name}} {{.MemUsage}}'"))
    client.close()


if __name__ == "__main__":
    main()
