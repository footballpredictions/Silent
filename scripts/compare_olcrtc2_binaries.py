"""Compare olcrtc2-srv md5/size on Cell1 vs Cell2; sample KCP/bitrate related logs."""
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
        out={}
        for ip in ("87.58.213.193","78.17.74.27"):
            r=(await db.execute(select(HiveCell).where(HiveCell.public_ip==ip))).scalar_one()
            out[ip]=resolve_ssh_password(r) or ""
        print(json.dumps(out))
asyncio.run(main())
"""


def main() -> None:
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(CREDS.encode()), "/tmp/pwds.py")
    sftp.close()
    run(queen, "docker cp /tmp/pwds.py backend-api-1:/tmp/pwds.py")
    raw = run(queen, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/pwds.py")
    queen.close()
    pwds = json.loads([ln for ln in raw.splitlines() if ln.strip().startswith("{")][-1])

    for ip, pwd in pwds.items():
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(ip, username="root", password=pwd, timeout=25)
        _, o, e = c.exec_command(
            "echo CELL=$(curl -4 -s --max-time 3 ifconfig.me); "
            "md5sum /opt/silent-vpn/olcrtc2/olcrtc2-srv; "
            "stat -c '%s %y' /opt/silent-vpn/olcrtc2/olcrtc2-srv; "
            "echo '--- strings KCP/NoDelay ---'; "
            "strings /opt/silent-vpn/olcrtc2/olcrtc2-srv | grep -E 'SetNoDelay|vp8channel|wbstream|telemost' | head -20; "
            "echo '--- env modes ---'; "
            "grep -h ^OLCRTC2_MODE= /opt/silent-vpn/olcrtc2/env.d/*.env 2>/dev/null | sort | uniq -c; "
            "echo '--- active units ---'; "
            "systemctl list-units 'olcrtc2@*' --state=running --no-pager | wc -l",
            timeout=40,
        )
        print(f"\n===== {ip} =====")
        print((o.read() + e.read()).decode("utf-8", "replace"))
        c.close()


if __name__ == "__main__":
    main()
