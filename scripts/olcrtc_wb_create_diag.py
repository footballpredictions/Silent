"""Диагностика WB create на проде."""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _deploy_common import connect, run  # noqa: E402


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    py = """
import asyncio
from app.database import AsyncSessionLocal
from app.services.olcrtc_room_accounts import load_room_accounts, resolve_storage_state
from ai.olcrtc_host_provision_client import create_room_best, host_provision_status, push_storage_to_host

async def main():
    st = await host_provision_status()
    print("host", st)
    async with AsyncSessionLocal() as db:
        accounts = await load_room_accounts(db)
        storage = None
        for acc in accounts.wbstream:
            storage = resolve_storage_state(acc)
            if storage:
                print("storage cookies", len(storage.get("cookies") or []), "origins", len(storage.get("origins") or []))
                break
        if not storage:
            print("NO WB storage_state in DB")
            return
        ok = await push_storage_to_host("wbstream", storage)
        print("push", ok)
        print("creating wbstream room via host...")
        res = await create_room_best("wbstream", storage, headless=True)
        print("ok=", res.ok, "room=", res.room_id, "msg=", (res.message or "")[:500])

asyncio.run(main())
"""
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/wb_create_diag.py")
    run(client, "docker cp /tmp/wb_create_diag.py backend-api-1:/tmp/wb_create_diag.py")
    print(
        run(
            client,
            "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/wb_create_diag.py",
        )
    )
    print(
        run(
            client,
            "journalctl -u silent-olcrtc-host-provision -n 40 --no-pager 2>/dev/null || true",
        )
    )
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
