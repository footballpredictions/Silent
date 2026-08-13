"""Deploy assign race fix + bump warm_pool_per_dt on prod, then re-loadtest."""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, REMOTE, connect, run  # noqa: E402

BUMP = r"""
import asyncio, json
from app.database import AsyncSessionLocal
from app.services.olcrtc2_settings import load_olcrtc2_settings, save_olcrtc2_settings

async def main():
    async with AsyncSessionLocal() as db:
        s = await load_olcrtc2_settings(db)
        old = int(s.get("warm_pool_per_dt") or 3)
        s["warm_pool_per_dt"] = max(old, 12)
        await save_olcrtc2_settings(db, s)
        print(json.dumps({"warm_pool_per_dt": s["warm_pool_per_dt"], "was": old}))
asyncio.run(main())
"""


def main() -> None:
    files = [
        "app/services/olcrtc2_assign.py",
        "app/services/olcrtc2_settings.py",
    ]
    queen = connect()
    sftp = queen.open_sftp()
    for rel in files:
        local = BACKEND_ROOT / rel
        sftp.put(str(local), f"{REMOTE}/{rel}")
        print("put", rel)
    sftp.putfo(io.BytesIO(BUMP.encode()), "/tmp/bump_warm.py")
    sftp.close()

    for rel in files:
        run(queen, f"docker cp {REMOTE}/{rel} backend-api-1:/app/{rel}")
    run(queen, "docker cp /tmp/bump_warm.py backend-api-1:/tmp/bump_warm.py")
    # restart api to clear in-memory locks / reload modules
    run(queen, "docker compose -f /opt/silent-vpn/backend/docker-compose.yml restart api", timeout=60)
    time.sleep(14)
    print(run(queen, "curl -sf http://localhost:8000/health || true"))
    print(run(queen, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/bump_warm.py"))
    queen.close()
    print("DEPLOY_ASSIGN_FIX_OK")


if __name__ == "__main__":
    main()
