"""Fetch telemost unit env from cell via queen SSH."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r'''
import asyncio, json
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room
from app.services.olcrtc2_settings import load_olcrtc2_settings, cell_ip_for_provider

async def main():
    async with AsyncSessionLocal() as db:
        s = await load_olcrtc2_settings(db)
        print("transport", s.get("transport"))
        print("tm_cell", cell_ip_for_provider(s, "telemost"))
        print("wb_cell", cell_ip_for_provider(s, "wbstream"))
        rows = (await db.execute(
            select(Olcrtc2Room).where(
                Olcrtc2Room.provider == "telemost",
                Olcrtc2Room.device_type == "android",
                Olcrtc2Room.status == "active",
            )
        )).scalars().all()
        for r in rows:
            print("ROOM", r.unit_name, r.room_url, "key", (r.crypto_key or "")[:12])

asyncio.run(main())
'''

REMOTE_SH = r'''
set -e
echo "=== running olcrtc2 units ==="
systemctl list-units --type=service --state=running --no-legend 'olcrtc2@*' 2>/dev/null | head -20 || true
echo "=== env.d ==="
ls -la /opt/silent-vpn/olcrtc2/env.d/ 2>/dev/null | head -30 || ls -la /etc/olcrtc2/ 2>/dev/null | head -30 || true
echo "=== sample env telemost ==="
for f in /opt/silent-vpn/olcrtc2/env.d/*.env; do
  [ -f "$f" ] || continue
  mode=$(grep -E '^OLCRTC2_MODE=' "$f" | head -1 | cut -d= -f2)
  if [ "$mode" = "telemost" ]; then
    echo "FILE $f"
    grep -E '^OLCRTC2_' "$f" | sed -E 's/^(OLCRTC2_KEY=).*/\1<redacted>/; s/^(OLCRTC2_AUTH_TOKEN=).*/\1<redacted>/'
    echo "---"
  fi
done | head -80
echo "=== binary strings transport ==="
strings /opt/silent-vpn/olcrtc2/olcrtc2-srv 2>/dev/null | grep -E 'OLCRTC2_|vp8channel|datachannel|fps|batch' | head -40 || true
'''


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode("utf-8")), "/tmp/tm_cfg.py")
    sftp.putfo(io.BytesIO(REMOTE_SH.encode("utf-8")), "/tmp/tm_cell.sh")
    sftp.close()
    run(client, "docker cp /tmp/tm_cfg.py backend-api-1:/tmp/tm_cfg.py")
    run(client, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/tm_cfg.py")
    run(
        client,
        "scp -o StrictHostKeyChecking=no /tmp/tm_cell.sh root@87.58.213.193:/tmp/tm_cell.sh "
        "&& ssh -o StrictHostKeyChecking=no root@87.58.213.193 'bash /tmp/tm_cell.sh'",
    )
    client.close()


if __name__ == "__main__":
    main()
