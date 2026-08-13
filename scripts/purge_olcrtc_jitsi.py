"""Удалить Jitsi из olcrtc на проде: settings, rooms, sticky, systemd units.

  cd backend
  python scripts/purge_olcrtc_jitsi.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _deploy_common import REMOTE, connect, run  # noqa: E402

REMOTE_OLCRTC = "/opt/silent-vpn/olcrtc"


def main() -> None:
    client = connect()
    sftp = client.open_sftp()

    py = r"""
import asyncio
import json
from sqlalchemy import delete, select, update
from app.database import AsyncSessionLocal
from app.models import AppSetting
from app.models.olcrtc_room import OlcrtcRoom, OlcrtcRoomSticky
from app.services.olcrtc_settings import (
    OLCRTC_SETTINGS_KEY,
    PROVIDERS,
    load_olcrtc_settings,
    parse_settings,
    save_olcrtc_settings,
)
from app.services.olcrtc_rooms_db import write_all_unit_yaml_from_db, pool_metrics

async def main():
    async with AsyncSessionLocal() as db:
        settings = await load_olcrtc_settings(db)
        # strip unknown providers (jitsi) — parse_settings already only PROVIDERS
        raw = settings.to_dict()
        raw["providers"] = {k: v for k, v in raw.get("providers", {}).items() if k in PROVIDERS}
        settings = parse_settings(raw)
        # ensure telemost + wbstream enabled in session mode (jitsi already purged)
        if settings.enabled:
            for name in PROVIDERS:
                p = settings.providers.get(name)
                if not p:
                    continue
                if name in ("telemost", "wbstream"):
                    p.enabled = True
                settings.providers[name] = p
        await save_olcrtc_settings(db, settings)
        print("settings providers", list(settings.providers.keys()))

        sticky = await db.execute(delete(OlcrtcRoomSticky).where(OlcrtcRoomSticky.provider == "jitsi"))
        print("sticky deleted", sticky.rowcount)

        rooms = await db.execute(
            update(OlcrtcRoom)
            .where(OlcrtcRoom.provider == "jitsi")
            .values(status="draining", last_error="jitsi removed")
        )
        print("rooms draining", rooms.rowcount)
        await db.commit()

        # hard-delete drained jitsi with 0 online
        gone = await db.execute(
            delete(OlcrtcRoom).where(
                OlcrtcRoom.provider == "jitsi",
                OlcrtcRoom.online_count <= 0,
            )
        )
        print("rooms deleted", gone.rowcount)
        await db.commit()

        files = await write_all_unit_yaml_from_db(db)
        print("yaml units", ",".join(sorted(files.keys())))
        print("metrics", await pool_metrics(db))

asyncio.run(main())
"""
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/purge_olcrtc_jitsi.py")
    run(client, "docker cp /tmp/purge_olcrtc_jitsi.py backend-api-1:/tmp/purge_olcrtc_jitsi.py")
    print(
        run(
            client,
            "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/purge_olcrtc_jitsi.py",
        )
    )

    # stop/disable all jitsi units + remove yaml
    run(
        client,
        "systemctl list-units 'olcrtc@*-jitsi*' --all --no-legend 2>/dev/null "
        "| awk '{print $1}' | while read u; do "
        "echo STOP $u; systemctl disable --now \"$u\" 2>/dev/null || true; done",
    )
    run(
        client,
        f"rm -f {REMOTE_OLCRTC}/server-*-jitsi.yaml {REMOTE_OLCRTC}/server-*-jitsi-*.yaml 2>/dev/null; "
        f"ls {REMOTE_OLCRTC}/server-*.yaml 2>/dev/null | head -40",
    )
    # apply remaining units from yaml on disk (written by API into /app — copy out)
    run(
        client,
        "docker exec backend-api-1 sh -c 'ls /app/olcrtc-units 2>/dev/null || true'",
    )
    print("purge done — next: python scripts/apply_olcrtc_units_from_db.py")
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
