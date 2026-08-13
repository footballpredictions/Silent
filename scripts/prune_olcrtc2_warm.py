"""Prune excess warm rooms down to warm_pool_per_dt."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r"""
import asyncio, json
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.services.olcrtc2_assign import prune_stale_sessions, ensure_warm_pool, pool_stats
from app.models.olcrtc2_room import Olcrtc2Room
from collections import Counter

async def main():
    async with AsyncSessionLocal() as db:
        print("BEFORE", json.dumps(await pool_stats(db)))
        print("PRUNE", json.dumps(await prune_stale_sessions(db), default=str))
        print("WARM", json.dumps(await ensure_warm_pool(db), default=str))
        rows=(await db.execute(select(Olcrtc2Room))).scalars().all()
        print("COUNTS", json.dumps(dict(Counter(f"{r.provider}:{r.device_type}" for r in rows))))
        print("AFTER", json.dumps(await pool_stats(db)))
asyncio.run(main())
"""


def main() -> None:
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode()), "/tmp/prune_warm.py")
    sftp.close()
    run(queen, "docker cp /tmp/prune_warm.py backend-api-1:/tmp/prune_warm.py")
    print(run(queen, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/prune_warm.py", timeout=300))
    queen.close()


if __name__ == "__main__":
    main()
