"""Диагностика пула olcrtc на проде (только чтение).

  cd backend
  python scripts/diag_olcrtc_pool.py

Показывает: комнаты + online/max, sticky, статусы unit'ов, память контейнеров и хоста.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _deploy_common import connect, run  # noqa: E402

PROBE = r"""
import asyncio, json
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models.olcrtc_room import OlcrtcRoom, OlcrtcRoomSticky


async def main():
    async with AsyncSessionLocal() as db:
        rooms = (await db.execute(select(OlcrtcRoom))).scalars().all()
        print(f"ROOMS total={len(rooms)}")
        by_status = {}
        for r in rooms:
            by_status[r.status] = by_status.get(r.status, 0) + 1
        print("by_status", json.dumps(by_status))
        for r in sorted(rooms, key=lambda x: (x.provider, x.slot_label or "", x.unit_name or "")):
            print(
                f"  {r.provider:9s} {(r.slot_label or '-'):8s} {(r.unit_name or '-'):26s} "
                f"{r.status:9s} online={r.online_count}/{r.max_clients} "
                f"room={(r.room_url or '')[:40]} err={(r.last_error or '')[:60]}"
            )
        st = (await db.execute(select(OlcrtcRoomSticky))).scalars().all()
        print(f"STICKY total={len(st)}")
        per_room = {}
        for s in st:
            per_room[str(s.room_id)] = per_room.get(str(s.room_id), 0) + 1
        for rid, n in sorted(per_room.items(), key=lambda kv: -kv[1])[:20]:
            room = next((r for r in rooms if str(r.id) == rid), None)
            print(f"  {n:4d} -> {room.unit_name if room else rid}")
        try:
            from app.services.olcrtc_rooms_db import pool_metrics
            print("METRICS", json.dumps(await pool_metrics(db), default=str))
        except Exception as e:
            print("METRICS fail", e)

asyncio.run(main())
"""


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(PROBE.encode()), "/tmp/diag_olcrtc.py")
    run(client, "docker cp /tmp/diag_olcrtc.py backend-api-1:/tmp/diag_olcrtc.py")
    print(run(client, "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/diag_olcrtc.py", timeout=180))

    print("=== systemd olcrtc units ===")
    print(run(client, "systemctl list-units 'olcrtc@*' --all --no-pager --no-legend | head -80"))
    print("=== host memory ===")
    print(run(client, "free -m; echo; ps -eo pid,rss,etimes,comm --sort=-rss | head -25"))
    print("=== docker stats ===")
    print(run(client, "docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}'"))
    print("=== olcrtc processes ===")
    print(run(client, "ps -eo pid,rss,etimes,args --sort=-rss | grep -i olcrtc | head -30 || true"))
    client.close()


if __name__ == "__main__":
    main()
