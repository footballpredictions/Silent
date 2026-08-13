"""Снести PLACEHOLDER-комнаты на проде + выключить мёртвые unit'ы.

  cd backend
  python scripts/olcrtc_cleanup_placeholders.py
"""
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
from app.models.olcrtc_room import OlcrtcRoom
from app.services.olcrtc_rooms_db import delete_room_row, list_rooms, pool_metrics
from app.services.olcrtc_settings import is_placeholder_room, load_olcrtc_settings, save_olcrtc_settings
from ai.olcrtc_host_provision_client import apply_units_via_host
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        rooms = await list_rooms(db)
        removed = []
        for r in rooms:
            url = (r.room_url or "").strip()
            if is_placeholder_room(url) or url.upper() == "PLACEHOLDER":
                unit = r.unit_name
                await delete_room_row(db, r.id, reason="placeholder cleanup")
                removed.append(unit)
                print("deleted", unit, url)
        if removed:
            try:
                await apply_units_via_host({}, remove=removed)
                print("units removed", removed)
            except Exception as e:
                print("apply remove fail", e)
        settings = await load_olcrtc_settings(db)
        for name, p in settings.providers.items():
            if name != "telemost":
                p.enabled = False
            else:
                p.enabled = True
            for slot in list(p.rooms or []):
                if is_placeholder_room(slot.url) or (slot.url or "").strip().upper() == "PLACEHOLDER":
                    slot.url = ""
            settings.providers[name] = p
        await save_olcrtc_settings(db, settings)
        print("settings cleaned")
        print("metrics", await pool_metrics(db))
        left = await list_rooms(db)
        print("left", [(r.unit_name, r.room_url, r.status, r.online_count) for r in left])

asyncio.run(main())
"""
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/olcrtc_cleanup_ph.py")
    run(client, "docker cp /tmp/olcrtc_cleanup_ph.py backend-api-1:/tmp/olcrtc_cleanup_ph.py")
    # ensure latest is_placeholder on server first
    local = ROOT / "app" / "services" / "olcrtc_settings.py"
    sftp.put(str(local), "/tmp/olcrtc_settings.py")
    run(client, "docker cp /tmp/olcrtc_settings.py backend-api-1:/app/app/services/olcrtc_settings.py")
    local2 = ROOT / "app" / "services" / "olcrtc_rooms_db.py"
    sftp.put(str(local2), "/tmp/olcrtc_rooms_db.py")
    run(client, "docker cp /tmp/olcrtc_rooms_db.py backend-api-1:/app/app/services/olcrtc_rooms_db.py")
    print(
        run(
            client,
            "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/olcrtc_cleanup_ph.py",
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
