"""Verify room 94038621041836 unit env vs DB key; try cell via queen."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

ROOM = "94038621041836"

INNER = r"""
import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room

ROOM = "94038621041836"

async def main():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Olcrtc2Room))).scalars().all()
        hit = [r for r in rows if ROOM in (r.room_url or "") or ROOM in (r.unit_name or "")]
        print("hits", len(hit))
        for r in hit:
            print("id", r.id)
            print("unit", r.unit_name)
            print("prov", r.provider, "dt", r.device_type, "status", r.status)
            print("room", r.room_url)
            print("key", (r.crypto_key or "")[:16], "len", len(r.crypto_key or ""))
            print("online", r.online_count, "max", r.max_clients)
            print("cell", getattr(r, "cell_ip", None) or getattr(r, "host_ip", None))
            print("updated", r.updated_at)

asyncio.run(main())
"""


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode("utf-8")), "/tmp/tm_room.py")
    sftp.close()
    run(client, "docker cp /tmp/tm_room.py backend-api-1:/tmp/tm_room.py")
    run(client, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/tm_room.py")
    # cell-agent HTTP via queen (no interactive ssh hang): probe unit via API if possible
    run(
        client,
        "timeout 20 ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 -o BatchMode=yes "
        "root@87.58.213.193 "
        f"'u=$(grep -l {ROOM} /opt/silent-vpn/olcrtc2/env.d/*.env 2>/dev/null | head -1); "
        "echo UNIT_ENV=$u; "
        "if [ -n \"$u\" ]; then grep -E \"^OLCRTC2_(MODE|ROOM)=\" \"$u\"; "
        "bn=$(basename \"$u\" .env); "
        "systemctl is-active olcrtc2@$bn 2>/dev/null || true; "
        "journalctl -u olcrtc2@$bn -n 30 --no-pager 2>/dev/null | tail -30; fi; "
        "pgrep -a olcrtc2-srv | head -5; "
        "ls /opt/silent-vpn/olcrtc2/olcrtc2-srv 2>/dev/null; "
        "stat -c \"%s %y\" /opt/silent-vpn/olcrtc2/olcrtc2-srv 2>/dev/null'",
    )
    client.close()


if __name__ == "__main__":
    main()
