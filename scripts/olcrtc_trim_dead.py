"""Снести мёртвые/пустые/WB комнаты в session-mode на проде."""
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
from app.services.olcrtc_rooms_db import delete_room_row, list_rooms, pool_metrics
from app.services.olcrtc_settings import load_olcrtc_settings, save_olcrtc_settings
from ai.olcrtc_host_provision_client import apply_units_via_host, host_unit_health

async def main():
    remove_units = []
    async with AsyncSessionLocal() as db:
        settings = await load_olcrtc_settings(db)
        wb = settings.providers.get("wbstream")
        if wb:
            wb.enabled = False
            settings.providers["wbstream"] = wb
            await save_olcrtc_settings(db, settings)
        for r in await list_rooms(db):
            reason = ""
            if r.provider == "wbstream":
                reason = "wb disabled"
            else:
                h = await host_unit_health(r.unit_name)
                online = int(r.online_count or 0)
                if online <= 0 and h.get("healthy") is False:
                    reason = "empty+unhealthy"
                elif online <= 0 and r.status in ("offline", "error", "draining"):
                    reason = "empty+bad status"
            if reason:
                print("teardown", r.unit_name, reason, r.room_url[:40])
                remove_units.append(r.unit_name)
                await delete_room_row(db, r.id, reason=reason)
        if remove_units:
            res = await apply_units_via_host({}, remove=remove_units)
            print("apply", res.get("ok"), res.get("message"), "stopped", res.get("stopped"))
        print("metrics", await pool_metrics(db))
        for r in await list_rooms(db):
            print("keep", r.unit_name, r.slot_label, r.online_count, r.room_url[:36], r.status)

asyncio.run(main())
"""
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/olcrtc_trim.py")
    run(client, "docker cp /tmp/olcrtc_trim.py backend-api-1:/tmp/olcrtc_trim.py")
    print(
        run(
            client,
            "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/olcrtc_trim.py",
        )
    )
    print(
        run(
            client,
            "systemctl list-units 'olcrtc@*' --no-legend 2>/dev/null | head -20 || true",
        )
    )
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
