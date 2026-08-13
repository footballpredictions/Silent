"""Apply one WB room from queen, then print safe MODE/token len + journal on Cell 2."""
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

INNER = r"""
import asyncio, json, sys
sys.path.insert(0, "/app")

async def main():
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.olcrtc2_room import Olcrtc2Room
    from app.services.olcrtc2_cell_units import apply_olcrtc2_unit

    async with AsyncSessionLocal() as db:
        r = (await db.execute(
            select(Olcrtc2Room).where(Olcrtc2Room.provider == "wbstream")
            .order_by(Olcrtc2Room.created_at.desc())
        )).scalars().first()
        if not r:
            print(json.dumps({"error": "no room"}))
            return
        print(json.dumps({
            "unit": r.unit_name,
            "provider": r.provider,
            "room": r.room_url,
            "tok_len": len(r.auth_token or ""),
            "tok_ok": (r.auth_token or "").startswith("eyJ"),
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
        r = (await db.execute(select(HiveCell).where(HiveCell.public_ip == sys.argv[1]))).scalar_one()
        print(json.dumps({"pwd": resolve_ssh_password(r) or ""}))
asyncio.run(main())
"""


def redact(s: str) -> str:
    s = re.sub(r"eyJ[A-Za-z0-9_\-.=]+", "<JWT>", s)
    s = re.sub(r"(OLCRTC2_KEY=)\S+", r"\1<redacted>", s)
    s = re.sub(r"(OLCRTC2_AUTH_TOKEN=)\S+", r"\1<redacted>", s)
    return s


def main() -> None:
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode()), "/tmp/verify_apply.py")
    sftp.putfo(io.BytesIO(CREDS.encode()), "/tmp/c2pwd.py")
    sftp.close()
    run(queen, "docker cp /tmp/verify_apply.py backend-api-1:/tmp/verify_apply.py")
    run(queen, "docker cp /tmp/c2pwd.py backend-api-1:/tmp/c2pwd.py")
    raw = run(
        queen,
        "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/verify_apply.py",
        timeout=120,
    )
    print("=== queen apply ===")
    print(raw)
    lines = [ln for ln in raw.splitlines() if ln.strip().startswith("{")]
    meta = json.loads(lines[0])
    unit = meta.get("unit") or ""
    pwd_raw = run(
        queen,
        f"docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/c2pwd.py {CELL}",
    )
    queen.close()
    pwd = json.loads([ln for ln in pwd_raw.splitlines() if ln.strip().startswith("{")][-1])["pwd"]

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(CELL, username="root", password=pwd, timeout=25)

    def sh(cmd: str, timeout: int = 40) -> str:
        _, o, e = c.exec_command(cmd, timeout=timeout)
        return (o.read() + e.read()).decode("utf-8", "replace")

    env = f"/opt/silent-vpn/olcrtc2/env.d/{unit}.env"
    print("=== cell env ===")
    print(redact(sh(
        f"python3 - <<'PY'\n"
        f"from pathlib import Path\n"
        f"p=Path({env!r})\n"
        f"print('exists', p.is_file())\n"
        f"if p.is_file():\n"
        f"  d={{}}\n"
        f"  for ln in p.read_text().splitlines():\n"
        f"    if '=' in ln and not ln.startswith('#'):\n"
        f"      k,v=ln.split('=',1); d[k]=v\n"
        f"  print('MODE', d.get('OLCRTC2_MODE'))\n"
        f"  print('ROOM', (d.get('OLCRTC2_ROOM') or '')[:40])\n"
        f"  tok=d.get('OLCRTC2_AUTH_TOKEN') or ''\n"
        f"  print('TOKEN_len', len(tok), 'eyJ', tok.startswith('eyJ'))\n"
        f"  print('KEY_len', len(d.get('OLCRTC2_KEY') or ''))\n"
        f"PY"
    )))
    print("=== agent apply log ===")
    print(redact(sh(
        "journalctl -u silent-cell-agent -n 40 --no-pager | "
        "grep -E 'olcrtc2_apply|ERROR|Traceback' | tail -20"
    )))
    print("=== unit journal ===")
    print(redact(sh(
        f"systemctl is-active 'olcrtc2@{unit}.service'; "
        f"journalctl -u 'olcrtc2@{unit}.service' -n 12 --no-pager"
    )))
    print("=== agent code snippet ===")
    print(sh(
        "grep -n 'lines = \\|OLCRTC2_AUTH_TOKEN\\|mode = .wbstream' "
        "/opt/silent-vpn/cell-agent/main.py | head -15"
    ))
    c.close()


if __name__ == "__main__":
    main()
