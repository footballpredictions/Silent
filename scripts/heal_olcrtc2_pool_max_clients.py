"""Force occupancy 1:1 — all olcrtc2 rooms max_clients=1 (do NOT bump to 25)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r'''
import asyncio, json
from sqlalchemy import text, select
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room

async def main():
    async with AsyncSessionLocal() as db:
        r = await db.execute(text(
            "UPDATE olcrtc2_rooms SET max_clients = 1 WHERE COALESCE(max_clients, 0) <> 1"
        ))
        await db.commit()
        rows = (await db.execute(select(Olcrtc2Room))).scalars().all()
        by = {}
        for x in rows:
            k = f"{x.provider}/{x.device_type}/{x.status}"
            by.setdefault(k, {"n": 0, "min": 99, "max": 0})
            by[k]["n"] += 1
            by[k]["min"] = min(by[k]["min"], int(x.max_clients or 0))
            by[k]["max"] = max(by[k]["max"], int(x.max_clients or 0))
        print(json.dumps({"updated_hint": r.rowcount, "rooms": by}, ensure_ascii=False))

asyncio.run(main())
'''


def main() -> int:
    c = connect()
    try:
        run(c, "cat > /tmp/heal_max_clients.py <<'PY'\n" + INNER + "\nPY")
        out = run(
            c,
            "docker cp /tmp/heal_max_clients.py backend-api-1:/tmp/heal_max_clients.py "
            "&& docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/heal_max_clients.py",
        )
        print(out)
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    raise SystemExit(main())
