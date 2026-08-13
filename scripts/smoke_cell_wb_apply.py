"""Force cell-agent main.py sync + smoke apply wbstream env write."""
from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import httpx
import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, connect, run  # noqa: E402

CELL = "78.17.74.27"

CREDS = r"""
import asyncio, json, sys
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.hive_cell import HiveCell
from app.models.olcrtc2_room import Olcrtc2Room
from app.services.hive_service import resolve_ssh_password
from app.core.security import decrypt_value

async def main():
    async with AsyncSessionLocal() as db:
        cell = (await db.execute(select(HiveCell).where(HiveCell.public_ip == sys.argv[1]))).scalar_one()
        secret = decrypt_value(cell.api_secret_enc) if cell.api_secret_enc else ""
        room = (await db.execute(
            select(Olcrtc2Room).where(Olcrtc2Room.provider == "wbstream").order_by(Olcrtc2Room.created_at.desc())
        )).scalars().first()
        print(json.dumps({
            "pwd": resolve_ssh_password(cell) or "",
            "api_url": cell.api_url,
            "secret": secret or "",
            "unit": room.unit_name if room else "",
            "room": room.room_url if room else "",
            "key": room.crypto_key if room else "",
            "tok": (room.auth_token or "") if room else "",
            "provider": room.provider if room else "",
        }))
asyncio.run(main())
"""


def main() -> None:
    local = BACKEND_ROOT / "cell-agent" / "main.py"
    agent = local.read_bytes()
    local_md5 = hashlib.md5(agent).hexdigest()
    print("local_md5", local_md5, "has_fix", b'mode = "wbstream" if prov == "wbstream"' in agent)

    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(CREDS.encode()), "/tmp/c2a.py")
    sftp.close()
    run(queen, "docker cp /tmp/c2a.py backend-api-1:/tmp/c2a.py")
    raw = run(
        queen,
        f"docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/c2a.py {CELL}",
    )
    queen.close()
    data = json.loads([ln for ln in raw.splitlines() if ln.strip().startswith("{")][-1])
    pwd = data["pwd"]
    secret = data["secret"]
    api = (data.get("api_url") or f"http://{CELL}:9100").rstrip("/")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(CELL, username="root", password=pwd, timeout=25)
    sftp = c.open_sftp()
    sftp.putfo(io.BytesIO(agent), "/opt/silent-vpn/cell-agent/main.py")
    sftp.close()

    def sh(cmd: str) -> str:
        _, o, e = c.exec_command(cmd, timeout=60)
        return (o.read() + e.read()).decode("utf-8", "replace")

    print(sh(
        "md5sum /opt/silent-vpn/cell-agent/main.py; "
        "grep -n 'mode = .wbstream. if prov' /opt/silent-vpn/cell-agent/main.py; "
        "grep -n 'wbstream requires auth_token' /opt/silent-vpn/cell-agent/main.py; "
        "rm -rf /opt/silent-vpn/cell-agent/__pycache__; "
        "systemctl stop silent-cell-agent; sleep 1; "
        "systemctl start silent-cell-agent; sleep 2; "
        "systemctl is-active silent-cell-agent"
    ))

    # Direct apply smoke
    unit = "o2-smoke-wb"
    body = {
        "unit_name": unit,
        "room": data["room"] or "svpn_test",
        "crypto_key": data["key"] or ("ab" * 32),
        "provider": "wbstream",
        "auth_token": data["tok"],
        "restart": True,
    }
    print("POST apply provider=wbstream tok_len", len(data.get("tok") or ""))
    r = httpx.post(
        f"{api}/v1/olcrtc2/apply",
        json=body,
        headers={"X-Cell-Agent-Secret": secret},
        timeout=90.0,
    )
    print("HTTP", r.status_code, (r.text or "")[:300])
    print(sh(
        f"echo '--- env ---'; "
        f"cat /opt/silent-vpn/olcrtc2/env.d/{unit}.env | "
        f"sed -E 's/^(OLCRTC2_AUTH_TOKEN=).*/\\1LEN='\"$(grep ^OLCRTC2_AUTH_TOKEN= /opt/silent-vpn/olcrtc2/env.d/{unit}.env | cut -d= -f2- | wc -c)\"'/; "
        f"s/^(OLCRTC2_KEY=).*/\\1<redacted>/'; "
        f"systemctl is-active olcrtc2@{unit}.service; "
        f"journalctl -u olcrtc2@{unit}.service -n 15 --no-pager | sed -E 's/eyJ[A-Za-z0-9_.=-]{{20,}}/<JWT>/g'"
    ))
    # teardown smoke unit
    httpx.post(
        f"{api}/v1/olcrtc2/teardown",
        json={"unit_name": unit},
        headers={"X-Cell-Agent-Secret": secret},
        timeout=60.0,
    )
    c.close()


if __name__ == "__main__":
    main()
