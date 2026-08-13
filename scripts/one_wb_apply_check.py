"""From queen: apply one WB room and print cell env MODE (prove provider wire)."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r"""
import asyncio, json, sys
sys.path.insert(0, "/app")

async def main():
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.olcrtc2_room import Olcrtc2Room
    from app.services.olcrtc2_cell_units import apply_olcrtc2_unit, resolve_olcrtc2_cell

    async with AsyncSessionLocal() as db:
        r = (await db.execute(
            select(Olcrtc2Room).where(Olcrtc2Room.provider == "wbstream").order_by(Olcrtc2Room.created_at.desc())
        )).scalars().first()
        if not r:
            print(json.dumps({"error": "no room"}))
            return
        cell = await resolve_olcrtc2_cell(db, provider="wbstream")
        print(json.dumps({
            "unit": r.unit_name,
            "provider": r.provider,
            "room": r.room_url,
            "tok_prefix": (r.auth_token or "")[:8],
            "tok_len": len(r.auth_token or ""),
            "cell_ip": cell.public_ip if cell else None,
            "api_url": cell.api_url if cell else None,
        }))
        applied = await apply_olcrtc2_unit(db, r)
        print(json.dumps({"applied": applied}))

asyncio.run(main())
"""

CREDS = r"""
import asyncio, json, sys
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.hive_cell import HiveCell
from app.services.hive_service import resolve_ssh_password
async def main():
    async with AsyncSessionLocal() as db:
        r = (await db.execute(select(HiveCell).where(HiveCell.public_ip == "78.17.74.27"))).scalar_one()
        print(json.dumps({"pwd": resolve_ssh_password(r) or ""}))
asyncio.run(main())
"""


def main() -> None:
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode()), "/tmp/one_apply.py")
    sftp.putfo(io.BytesIO(CREDS.encode()), "/tmp/c2pwd2.py")
    sftp.close()
    run(queen, "docker cp /tmp/one_apply.py backend-api-1:/tmp/one_apply.py")
    run(queen, "docker cp /tmp/c2pwd2.py backend-api-1:/tmp/c2pwd2.py")
    raw = run(
        queen,
        "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/one_apply.py",
        timeout=120,
    )
    print(raw)
    lines = [ln for ln in raw.splitlines() if ln.strip().startswith("{")]
    meta = json.loads(lines[0])
    unit = meta.get("unit") or ""
    pwd_raw = run(
        queen,
        "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/c2pwd2.py",
    )
    queen.close()
    pwd = json.loads([ln for ln in pwd_raw.splitlines() if ln.strip().startswith("{")][-1])["pwd"]

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("78.17.74.27", username="root", password=pwd, timeout=25)
    _, o, e = c.exec_command(
        f"echo UNIT={unit}; cat /opt/silent-vpn/olcrtc2/env.d/{unit}.env | "
        f"sed -E 's/^(OLCRTC2_AUTH_TOKEN=).*/\\1len='\"$(grep ^OLCRTC2_AUTH_TOKEN= /opt/silent-vpn/olcrtc2/env.d/{unit}.env 2>/dev/null | cut -d= -f2- | wc -c)\"'/; "
        f"s/^(OLCRTC2_KEY=).*/\\1x/; "
        f"journalctl -u olcrtc2@{unit}.service -n 8 --no-pager | sed -E 's/eyJ[A-Za-z0-9_.=-]{{20,}}/<JWT>/g'",
        timeout=30,
    )
    print((o.read() + e.read()).decode("utf-8", "replace"))
    c.close()


if __name__ == "__main__":
    main()
