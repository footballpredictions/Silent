"""Quick prod peek: olcrtc2 telemost vs wb pool + cell unit sample."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r"""
import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room
from app.services.olcrtc2_settings import load_olcrtc2_settings, cell_ip_for_provider

async def main():
    async with AsyncSessionLocal() as db:
        s = await load_olcrtc2_settings(db)
        print("enabled", s.get("enabled"))
        print("transport", s.get("transport"))
        print("tm_cell", cell_ip_for_provider(s, "telemost"))
        print("wb_cell", cell_ip_for_provider(s, "wbstream"))
        for prov in ("telemost", "wbstream"):
            rows = (
                await db.execute(
                    select(Olcrtc2Room).where(
                        Olcrtc2Room.provider == prov,
                        Olcrtc2Room.status == "active",
                    )
                )
            ).scalars().all()
            mc = sorted({int(r.max_clients or 0) for r in rows})
            print(
                prov,
                "active",
                len(rows),
                "max_clients",
                mc,
                "online_sum",
                sum(int(r.online_count or 0) for r in rows),
            )
            for r in [x for x in rows if x.device_type == "android"][:3]:
                print(
                    " ",
                    r.unit_name,
                    (r.room_url or "")[:48],
                    "on",
                    r.online_count,
                    "max",
                    r.max_clients,
                )

asyncio.run(main())
"""

CELL = r"""
set -e
echo "=== running ==="
systemctl list-units --type=service --state=running --no-legend 'olcrtc2@*' 2>/dev/null | head -15 || true
echo "=== telemost env sample ==="
n=0
for f in /opt/silent-vpn/olcrtc2/env.d/*.env; do
  [ -f "$f" ] || continue
  mode=$(grep -E '^OLCRTC2_MODE=' "$f" | head -1 | cut -d= -f2-)
  [ "$mode" = "telemost" ] || continue
  echo "FILE $f"
  grep -E '^OLCRTC2_(MODE|ROOM)=' "$f"
  n=$((n+1))
  [ "$n" -ge 3 ] && break
done
echo "=== journal last telemost ==="
journalctl -u 'olcrtc2@*' -n 40 --no-pager 2>/dev/null | grep -iE 'telemost|vp8|session|error|fail' | tail -25 || true
"""


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode("utf-8")), "/tmp/tm_pool_q.py")
    sftp.putfo(io.BytesIO(CELL.encode("utf-8")), "/tmp/tm_cell_q.sh")
    sftp.close()
    run(client, "docker cp /tmp/tm_pool_q.py backend-api-1:/tmp/tm_pool_q.py")
    run(client, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/tm_pool_q.py")
    run(
        client,
        "scp -o StrictHostKeyChecking=no -o ConnectTimeout=15 /tmp/tm_cell_q.sh "
        "root@87.58.213.193:/tmp/tm_cell_q.sh && "
        "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 root@87.58.213.193 "
        "'bash /tmp/tm_cell_q.sh'",
    )
    client.close()


if __name__ == "__main__":
    main()
