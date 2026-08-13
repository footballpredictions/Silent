"""Deploy fixed cell-agent to queen, upgrade Cell 2, apply WB, verify MODE=wbstream."""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, REMOTE, connect, run  # noqa: E402

CELL = "78.17.74.27"

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

APPLY = r"""
import asyncio, json, sys
sys.path.insert(0, "/app")
async def main():
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.olcrtc2_room import Olcrtc2Room
    from app.services.olcrtc2_cell_units import apply_olcrtc2_unit
    async with AsyncSessionLocal() as db:
        rooms = (await db.execute(
            select(Olcrtc2Room).where(Olcrtc2Room.provider == "wbstream")
        )).scalars().all()
        print(json.dumps({"count": len(rooms)}))
        for r in rooms:
            applied = await apply_olcrtc2_unit(db, r)
            print(json.dumps({
                "unit": r.unit_name,
                "room": r.room_url,
                "ok": applied.get("ok"),
                "msg": (applied.get("message") or "")[:120],
                "env": applied.get("env"),
            }))
asyncio.run(main())
"""

BUILD_CHECK = r"""
import json, sys
sys.path.insert(0, "/app")
from app.services.hive_provision_service import cell_agent_build_id, _load_cell_agent_py
src = _load_cell_agent_py()
print(json.dumps({
  "build_id": cell_agent_build_id(),
  "has_wb_mode": 'mode = "wbstream" if prov == "wbstream"' in src,
  "has_auth_token_line": "OLCRTC2_AUTH_TOKEN=" in src,
  "size": len(src),
}))
"""


def redact(s: str) -> str:
    s = re.sub(r"eyJ[A-Za-z0-9_\-.=]+", "<JWT>", s)
    return s


def main() -> None:
    agent = (BACKEND_ROOT / "cell-agent" / "main.py").read_bytes()
    if b'mode = "wbstream" if prov == "wbstream"' not in agent:
        raise SystemExit("local agent missing wbstream fix")
    if b"OLCRTC2_AUTH_TOKEN=" not in agent:
        raise SystemExit("local agent missing AUTH_TOKEN write")
    local_md5 = hashlib.md5(agent).hexdigest()
    print("local_md5", local_md5, "size", len(agent))

    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(agent), f"{REMOTE}/cell-agent/main.py")
    sftp.putfo(io.BytesIO(CREDS.encode()), "/tmp/c2pwd.py")
    sftp.putfo(io.BytesIO(APPLY.encode()), "/tmp/wb_apply_all.py")
    sftp.putfo(io.BytesIO(BUILD_CHECK.encode()), "/tmp/agent_build_check.py")
    sftp.close()

    print("=== sync agent into api container ===")
    print(run(queen, f"docker exec backend-api-1 mkdir -p /app/cell-agent"))
    print(run(queen, f"docker cp {REMOTE}/cell-agent/main.py backend-api-1:/app/cell-agent/main.py"))
    # no full restart needed for file used by upgrade path; but restart so auto-upgrade sees new build
    print(run(queen, "docker compose -f /opt/silent-vpn/backend/docker-compose.yml restart api", timeout=60))
    time.sleep(12)
    print(run(queen, "curl -sf http://localhost:8000/health || true"))

    print("=== queen agent source check ===")
    run(queen, "docker cp /tmp/agent_build_check.py backend-api-1:/tmp/agent_build_check.py")
    print(run(queen, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/agent_build_check.py"))

    run(queen, "docker cp /tmp/c2pwd.py backend-api-1:/tmp/c2pwd.py")
    pwd_raw = run(
        queen,
        f"docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/c2pwd.py {CELL}",
    )
    pwd = json.loads([ln for ln in pwd_raw.splitlines() if ln.strip().startswith("{")][-1])["pwd"]

    print("=== upgrade Cell 2 from queen source ===")
    # use container helper so build_id matches
    UPGRADE = f"""
import sys
sys.path.insert(0, "/app")
from app.services.hive_provision_service import upgrade_cell_agent_via_ssh, cell_agent_build_id
print("target", cell_agent_build_id())
upgrade_cell_agent_via_ssh({CELL!r}, {pwd!r})
print("upgraded_ok")
"""
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(UPGRADE.encode()), "/tmp/upgrade_c2.py")
    sftp.close()
    run(queen, "docker cp /tmp/upgrade_c2.py backend-api-1:/tmp/upgrade_c2.py")
    print(run(queen, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/upgrade_c2.py", timeout=120))

    print("=== apply all WB rooms ===")
    run(queen, "docker cp /tmp/wb_apply_all.py backend-api-1:/tmp/wb_apply_all.py")
    print(run(
        queen,
        "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/wb_apply_all.py",
        timeout=300,
    ))
    queen.close()

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(CELL, username="root", password=pwd, timeout=25)

    def sh(cmd: str, timeout: int = 40) -> str:
        _, o, e = c.exec_command(cmd, timeout=timeout)
        return (o.read() + e.read()).decode("utf-8", "replace")

    print("=== cell agent markers ===")
    print(sh(
        "md5sum /opt/silent-vpn/cell-agent/main.py; "
        "grep -n 'mode = .wbstream. if prov\\|OLCRTC2_AUTH_TOKEN=\\|olcrtc2_apply unit=' "
        "/opt/silent-vpn/cell-agent/main.py | head -20"
    ))
    print("=== all env MODEs ===")
    print(redact(sh(
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "d=Path('/opt/silent-vpn/olcrtc2/env.d')\n"
        "for p in sorted(d.glob('*.env')):\n"
        "  data={}\n"
        "  for ln in p.read_text().splitlines():\n"
        "    if '=' in ln and not ln.startswith('#'):\n"
        "      k,v=ln.split('=',1); data[k]=v\n"
        "  tok=data.get('OLCRTC2_AUTH_TOKEN') or ''\n"
        "  print(p.name, 'MODE='+str(data.get('OLCRTC2_MODE')), 'ROOM='+str(data.get('OLCRTC2_ROOM') or '')[:28], 'tok_len='+str(len(tok)), 'eyJ='+str(tok.startswith('eyJ')))\n"
        "PY"
    )))
    print("=== sample unit journal ===")
    print(redact(sh(
        "u=$(ls /opt/silent-vpn/olcrtc2/env.d/*.env 2>/dev/null | head -1 | xargs -n1 basename | sed 's/.env$//'); "
        "echo UNIT=$u; systemctl is-active olcrtc2@$u.service; "
        "journalctl -u olcrtc2@$u.service -n 10 --no-pager"
    )))
    print("=== agent apply log ===")
    print(redact(sh(
        "journalctl -u silent-cell-agent -n 30 --no-pager | grep olcrtc2_apply | tail -15"
    )))
    c.close()
    print("DONE")


if __name__ == "__main__":
    main()
