from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

CREDS = r"""
import asyncio, json
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

CMD = r"""
set -e
for f in /opt/silent-vpn/olcrtc2/env.d/*.env; do
  echo "FILE $f"
  grep '^OLCRTC2_MODE=' "$f" || true
  grep '^OLCRTC2_ROOM=' "$f" || true
  if grep -q '^OLCRTC2_AUTH_TOKEN=' "$f"; then
    echo "AUTH_TOKEN_LEN=$(grep '^OLCRTC2_AUTH_TOKEN=' "$f" | cut -d= -f2- | wc -c)"
  else
    echo "AUTH_TOKEN_LEN=0"
  fi
done
echo ---
systemctl list-units 'olcrtc2@*' --no-legend | head -20
echo ---
u=$(ls /opt/silent-vpn/olcrtc2/env.d/*.env | head -1 | xargs -n1 basename | sed 's/.env$//')
echo journal_for=$u
journalctl -u "olcrtc2@$u.service" -n 20 --no-pager | sed -E 's/eyJ[A-Za-z0-9_.=-]{10,}/JWT/g'
"""


def main() -> None:
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(CREDS.encode()), "/tmp/p.py")
    sftp.close()
    run(queen, "docker cp /tmp/p.py backend-api-1:/tmp/p.py")
    raw = run(queen, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/p.py")
    queen.close()
    pwd = json.loads([ln for ln in raw.splitlines() if ln.strip().startswith("{")][-1])["pwd"]
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("78.17.74.27", username="root", password=pwd, timeout=25)
    _, o, e = c.exec_command(CMD, timeout=60)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[:500])
    c.close()


if __name__ == "__main__":
    main()
