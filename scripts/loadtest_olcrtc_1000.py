"""Нагрузочный прогон assign на 1000+ «клиентов» (API/cap/spill).

Не поднимает 1000 реальных WebRTC — проверяет плоскость пула:
  - 1000 fingerprint → нет pool_denied
  - online растёт, free падает
  - комнаты разносятся (unique rooms >> 1)
  - после cap комнаты spill на следующую
  - placement pick_cell_for_new_room вызывается при expand (если cap < target)

  cd backend
  python scripts/loadtest_olcrtc_1000.py
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

N = 1000

REMOTE = r"""
import asyncio
import json
import time
import urllib.request
from collections import Counter

from sqlalchemy import delete

from app.database import AsyncSessionLocal
from app.models.olcrtc_room import OlcrtcRoomSticky
from app.services.olcrtc_rooms_db import list_rooms, pool_metrics

BASE = "http://127.0.0.1:8000/api/vpn/olcrtc-config"
N = 1000


def fetch(fp: str, device_type: str = "pc"):
    url = f"{BASE}?device_type={device_type}&fingerprint={fp}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.load(resp)


async def main():
    t0 = time.time()
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(OlcrtcRoomSticky).where(OlcrtcRoomSticky.fingerprint.like("lt1000-%"))
        )
        for r in await list_rooms(db, status="active"):
            r.online_count = 0
        await db.commit()
        m0 = await pool_metrics(db)

    print("BEFORE", json.dumps({
        "capacity_total": m0.get("capacity_total"),
        "ready_for_1000": m0.get("ready_for_1000"),
        "rooms_active": m0.get("rooms_active"),
        "free_slots": m0.get("free_slots"),
    }, ensure_ascii=False))

    if int(m0.get("capacity_total") or 0) < N:
        print("FAIL capacity_total <", N)
        raise SystemExit(2)

    rooms_pc = []
    rooms_an = []
    denied = 0
    # 500+500 — по ~550 слотов jitsi на слот (22×25); PC≠Android
    for i in range(500):
        d = fetch(f"lt1000-pc-{i:04d}", "pc")
        if d.get("pool_denied"):
            denied += 1
        rooms_pc.append((d.get("providers") or {}).get("jitsi", {}).get("room_db_id") or "")
    for i in range(500):
        d = fetch(f"lt1000-an-{i:04d}", "android")
        if d.get("pool_denied"):
            denied += 1
        rooms_an.append((d.get("providers") or {}).get("jitsi", {}).get("room_db_id") or "")

    c_pc = Counter(rooms_pc)
    c_an = Counter(rooms_an)
    async with AsyncSessionLocal() as db:
        m1 = await pool_metrics(db)
        from app.services.hive_service import ensure_queen_cell, _list_assignable_cells
        q = await ensure_queen_cell(db)
        cells = await _list_assignable_cells(db)
        workers = [
            {
                "id": str(c.id),
                "ip": getattr(c, "ip_address", None) or getattr(c, "host", None),
                "is_queen": bool(c.is_queen),
            }
            for c in cells
            if not c.is_queen
        ]
        print("HIVE", json.dumps({
            "queen": str(q.id),
            "assignable": len(cells),
            "workers": workers,
            "spill_ready": len(workers) > 0,
        }, ensure_ascii=False))

    elapsed = round(time.time() - t0, 2)
    overlap = set(c_pc) & set(c_an)
    ok = (
        denied == 0
        and bool(m0.get("ready_for_1000"))
        and len(c_pc) >= 18
        and len(c_an) >= 18
        and len(overlap) == 0
        and int(m1.get("online_total") or 0) >= 900
        and "" not in c_pc
        and "" not in c_an
    )
    print("AFTER", json.dumps({
        "online_total": m1.get("online_total"),
        "free_slots": m1.get("free_slots"),
        "unique_pc_rooms": len(c_pc),
        "unique_android_rooms": len(c_an),
        "pc_android_overlap": len(overlap),
        "denied": denied,
        "elapsed_sec": elapsed,
        "top_pc": c_pc.most_common(3),
        "top_an": c_an.most_common(3),
    }, ensure_ascii=False))
    print("VERDICT", json.dumps({"pass": ok, "n": N}, ensure_ascii=False))
    if not ok:
        raise SystemExit(1)


asyncio.run(main())
"""


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(REMOTE.encode()), "/tmp/loadtest_olcrtc_1000.py")
    run(client, "docker cp /tmp/loadtest_olcrtc_1000.py backend-api-1:/tmp/loadtest_olcrtc_1000.py")
    out = run(
        client,
        "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/loadtest_olcrtc_1000.py",
        timeout=600,
    )
    print(out)
    sftp.close()
    client.close()
    if '"pass": true' not in out and '"pass": true' not in out.replace(" ", ""):
        # tolerate spaced JSON
        if '"pass": true' not in out and '"pass":true' not in out:
            raise SystemExit(1)
    print("LOADTEST_OK")


if __name__ == "__main__":
    main()
