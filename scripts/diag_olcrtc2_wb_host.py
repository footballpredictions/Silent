"""Diag WB olcrtc2: DB rooms + Cell2 unit env/journal (no JWT dump).

  cd backend
  python scripts/diag_olcrtc2_wb_host.py
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

CELL2 = "78.17.74.27"

CREDS = r"""
import asyncio, json, sys
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.hive_cell import HiveCell
from app.models.olcrtc2_room import Olcrtc2Room
from app.services.hive_service import resolve_ssh_password

async def main():
    want = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    async with AsyncSessionLocal() as db:
        cell = (await db.execute(select(HiveCell).where(HiveCell.public_ip == want))).scalar_one_or_none()
        pwd = resolve_ssh_password(cell) if cell else ""
        rooms = (await db.execute(
            select(Olcrtc2Room).where(Olcrtc2Room.provider == "wbstream").order_by(Olcrtc2Room.created_at.desc()).limit(10)
        )).scalars().all()
        out = {
            "pwd": pwd or "",
            "rooms": [
                {
                    "unit": r.unit_name,
                    "room": r.room_url,
                    "status": r.status,
                    "dt": r.device_type,
                    "tok": (r.auth_token or "").startswith("eyJ"),
                    "tok_len": len(r.auth_token or ""),
                }
                for r in rooms
            ],
        }
        print(json.dumps(out))
asyncio.run(main())
"""


def main() -> None:
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(CREDS.encode()), "/tmp/wb_host_creds.py")
    sftp.close()
    run(queen, "docker cp /tmp/wb_host_creds.py backend-api-1:/tmp/wb_host_creds.py")
    raw = run(
        queen,
        f"docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/wb_host_creds.py {CELL2}",
    )
    queen.close()
    data = json.loads([ln for ln in raw.splitlines() if ln.strip().startswith("{")][-1])
    print("=== DB wbstream rooms ===")
    for r in data.get("rooms") or []:
        print(r)
    pwd = data.get("pwd") or ""
    if not pwd:
        raise SystemExit("no cell password")

    cell = paramiko.SSHClient()
    cell.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cell.connect(CELL2, username="root", password=pwd, timeout=25)

    def sh(cmd: str) -> str:
        _, o, e = cell.exec_command(cmd, timeout=60)
        return (o.read() + e.read()).decode("utf-8", "replace")

    print("=== units ===")
    print(sh("systemctl list-units 'olcrtc2@*' --no-pager --no-legend | head -30"))
    print("=== env.d (mode/token flags, no JWT) ===")
    print(
        sh(
            "for f in /opt/silent-vpn/olcrtc2/env.d/*.env; do "
            "echo \"== $f\"; "
            "grep -E '^OLCRTC2_' \"$f\" | sed -E "
            "'s/^(OLCRTC2_AUTH_TOKEN=).*/\\1<redacted len='\"$(wc -c < \"$f\")\"'>/; "
            "s/^(OLCRTC2_KEY=).*/\\1<redacted>/'; "
            "done"
        )
    )
    # better per-file token length
    print("=== token lens ===")
    print(
        sh(
            "for f in /opt/silent-vpn/olcrtc2/env.d/*.env; do "
            "u=$(basename \"$f\" .env); "
            "mode=$(grep ^OLCRTC2_MODE= \"$f\" | cut -d= -f2); "
            "room=$(grep ^OLCRTC2_ROOM= \"$f\" | cut -d= -f2- | tail -c 24); "
            "tok=$(grep ^OLCRTC2_AUTH_TOKEN= \"$f\" | cut -d= -f2-); "
            "echo \"$u mode=$mode room=…$room tok_len=${#tok}\"; "
            "done"
        )
    )
    print("=== journal last units ===")
    print(
        sh(
            "for u in $(systemctl list-units 'olcrtc2@*' --no-legend --plain | awk '{print $1}' | head -5); do "
            "echo \"==== $u\"; "
            "journalctl -u \"$u\" -n 25 --no-pager | sed -E 's/eyJ[A-Za-z0-9_.=-]{20,}/<JWT>/g'; "
            "done"
        )
    )
    print("=== binary ===")
    print(sh("ls -la /opt/silent-vpn/olcrtc2/olcrtc2-srv; /opt/silent-vpn/olcrtc2/olcrtc2-srv 2>&1 | head -3 || true"))
    cell.close()


if __name__ == "__main__":
    main()
