"""Stop orphan wrong-mode units; verify WB hosts are active with mode=wbstream."""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

CELL = "78.17.74.27"

CREDS = r"""
import asyncio, json, sys
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.hive_cell import HiveCell
from app.models.olcrtc2_room import Olcrtc2Room
from app.services.hive_service import resolve_ssh_password
async def main():
    async with AsyncSessionLocal() as db:
        cell = (await db.execute(select(HiveCell).where(HiveCell.public_ip == sys.argv[1]))).scalar_one()
        rooms = (await db.execute(select(Olcrtc2Room).where(Olcrtc2Room.provider == "wbstream"))).scalars().all()
        print(json.dumps({
            "pwd": resolve_ssh_password(cell) or "",
            "units": [r.unit_name for r in rooms if r.unit_name],
            "rooms": [{"unit": r.unit_name, "room": r.room_url, "status": r.status} for r in rooms],
        }))
asyncio.run(main())
"""


def redact(s: str) -> str:
    return re.sub(r"eyJ[A-Za-z0-9_\-.=]+", "<JWT>", s)


def main() -> None:
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(CREDS.encode()), "/tmp/wb_units.py")
    sftp.close()
    run(queen, "docker cp /tmp/wb_units.py backend-api-1:/tmp/wb_units.py")
    raw = run(
        queen,
        f"docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/wb_units.py {CELL}",
    )
    queen.close()
    data = json.loads([ln for ln in raw.splitlines() if ln.strip().startswith("{")][-1])
    pwd = data["pwd"]
    keep = set(data["units"])
    print("DB rooms:", json.dumps(data["rooms"], ensure_ascii=False))
    print("keep units:", sorted(keep))

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(CELL, username="root", password=pwd, timeout=25)

    def sh(cmd: str, timeout: int = 60) -> str:
        _, o, e = c.exec_command(cmd, timeout=timeout)
        return (o.read() + e.read()).decode("utf-8", "replace")

    print("=== cleanup orphans ===")
    print(sh(
        "python3 - <<'PY'\n"
        "import subprocess\n"
        "from pathlib import Path\n"
        f"keep={sorted(keep)!r}\n"
        "envd=Path('/opt/silent-vpn/olcrtc2/env.d')\n"
        "for p in envd.glob('*.env'):\n"
        "  unit=p.stem\n"
        "  if unit not in keep:\n"
        "    subprocess.run(['systemctl','stop',f'olcrtc2@{unit}.service'], capture_output=True)\n"
        "    subprocess.run(['systemctl','reset-failed',f'olcrtc2@{unit}.service'], capture_output=True)\n"
        "    p.unlink(missing_ok=True)\n"
        "    print('removed', unit)\n"
        "print('left', sorted(x.stem for x in envd.glob('*.env')))\n"
        "PY"
    ))

    print("=== WB unit status ===")
    for u in sorted(keep):
        print(redact(sh(
            f"echo '--- {u} ---'; "
            f"systemctl is-active 'olcrtc2@{u}.service'; "
            f"python3 -c \"from pathlib import Path; t=Path('/opt/silent-vpn/olcrtc2/env.d/{u}.env').read_text(); "
            f"print([ln for ln in t.splitlines() if ln.startswith('OLCRTC2_MODE=') or ln.startswith('OLCRTC2_ROOM=') or ln.startswith('OLCRTC2_AUTH_TOKEN=')][:3])\"; "
            f"journalctl -u 'olcrtc2@{u}.service' -n 15 --no-pager | sed -E 's/eyJ[A-Za-z0-9_.=-]{{16,}}/<JWT>/g'"
        )))
    c.close()


if __name__ == "__main__":
    main()
