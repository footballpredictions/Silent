"""Диагностика Telemost на Соте 1: MODE/Link/crash-loop vs «раньше летал».

  cd backend
  python scripts/diag_olcrtc2_telemost.py
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

CELL = "87.58.213.193"

DB = r"""
import asyncio, json, sys
from collections import defaultdict
from sqlalchemy import func, select
from app.database import AsyncSessionLocal
from app.models.hive_cell import HiveCell
from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
from app.services.hive_service import resolve_ssh_password
from app.services.olcrtc2_settings import load_olcrtc2_settings, cell_ip_for_provider, enabled_providers

async def main():
    async with AsyncSessionLocal() as db:
        settings = await load_olcrtc2_settings(db)
        cell_ip = cell_ip_for_provider(settings, "telemost")
        cell = (await db.execute(select(HiveCell).where(HiveCell.public_ip == cell_ip))).scalar_one_or_none()
        rooms = (await db.execute(select(Olcrtc2Room).where(Olcrtc2Room.provider == "telemost"))).scalars().all()
        rows = []
        for r in rooms:
            st = int((await db.execute(select(func.count()).select_from(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id == r.id))).scalar() or 0)
            rows.append({
                "unit": r.unit_name,
                "status": r.status,
                "dt": r.device_type,
                "room": (r.room_url or "")[:48],
                "stickies": st,
                "max": r.max_clients,
                "cell_id": str(r.cell_id) if r.cell_id else None,
            })
        by_status = defaultdict(int)
        for r in rows:
            by_status[r["status"]] += 1
        print(json.dumps({
            "pwd": (resolve_ssh_password(cell) if cell else "") or "",
            "cell_ip": cell_ip,
            "settings": {
                "enabled": settings.get("enabled"),
                "agent": settings.get("agent_enabled"),
                "warm_pool_per_dt": settings.get("warm_pool_per_dt"),
                "providers": enabled_providers(settings),
                "cells": settings.get("cells"),
                "cell_provision_url": settings.get("cell_provision_url"),
            },
            "telemost_rooms": len(rows),
            "by_status": dict(by_status),
            "rooms": rows,
        }, ensure_ascii=False))
asyncio.run(main())
"""


def redact(s: str) -> str:
    return re.sub(r"eyJ[A-Za-z0-9_\-.=]+", "<JWT>", s)


def main() -> None:
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(DB.encode()), "/tmp/diag_tm.py")
    sftp.close()
    run(queen, "docker cp /tmp/diag_tm.py backend-api-1:/tmp/diag_tm.py")
    raw = run(queen, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/diag_tm.py")
    queen.close()
    data = json.loads([ln for ln in raw.splitlines() if ln.strip().startswith("{")][-1])
    print("=== DB telemost ===")
    print(json.dumps({k: v for k, v in data.items() if k != "pwd"}, ensure_ascii=False, indent=2))
    pwd = data.get("pwd") or ""
    cell = data.get("cell_ip") or CELL
    if not pwd:
        raise SystemExit("no cell pwd")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(cell, username="root", password=pwd, timeout=25)

    def sh(cmd: str, timeout: int = 60) -> str:
        _, o, e = c.exec_command(cmd, timeout=timeout)
        return (o.read() + e.read()).decode("utf-8", "replace")

    print("=== Cell agent / binary ===")
    print(sh(
        "systemctl is-active silent-cell-agent; "
        "md5sum /opt/silent-vpn/olcrtc2/olcrtc2-srv 2>/dev/null; "
        "ls -la /opt/silent-vpn/olcrtc2/olcrtc2-srv; "
        "grep -n 'mode = .wbstream. if prov\\|OLCRTC2_AUTH_TOKEN' /opt/silent-vpn/cell-agent/main.py | head -8"
    ))
    print("=== env MODEs (telemost cell) ===")
    print(redact(sh(
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "d=Path('/opt/silent-vpn/olcrtc2/env.d')\n"
        "print('env_count', len(list(d.glob('*.env'))))\n"
        "for p in sorted(d.glob('*.env')):\n"
        "  data={}\n"
        "  for ln in p.read_text().splitlines():\n"
        "    if '=' in ln and not ln.startswith('#'):\n"
        "      k,v=ln.split('=',1); data[k]=v\n"
        "  print(p.name, 'MODE='+str(data.get('OLCRTC2_MODE')), 'ROOM='+str(data.get('OLCRTC2_ROOM') or '')[:36], "
        "'tok_len='+str(len(data.get('OLCRTC2_AUTH_TOKEN') or '')))\n"
        "PY"
    )))
    print("=== systemd olcrtc2 units ===")
    print(sh(
        "systemctl list-units 'olcrtc2@*' --all --no-pager | head -40; "
        "echo '--- failed ---'; "
        "systemctl --failed --no-pager | grep olcrtc2 || true"
    ))
    print("=== sample journals (up to 5 units) ===")
    print(redact(sh(
        "python3 - <<'PY'\n"
        "import subprocess\n"
        "from pathlib import Path\n"
        "units=[p.stem for p in sorted(Path('/opt/silent-vpn/olcrtc2/env.d').glob('*.env'))][:5]\n"
        "for u in units:\n"
        "  print('=====', u, '=====')\n"
        "  st=subprocess.run(['systemctl','is-active',f'olcrtc2@{u}.service'],capture_output=True,text=True)\n"
        "  print('state', (st.stdout or st.stderr or '').strip())\n"
        "  j=subprocess.run(['journalctl','-u',f'olcrtc2@{u}.service','-n','12','--no-pager'],capture_output=True,text=True)\n"
        "  print(j.stdout)\n"
        "PY"
    )))
    print("=== provision :9101 ===")
    print(sh(
        "ss -lntp | grep -E '9101|9100' || true; "
        "curl -sf -m 3 http://127.0.0.1:9101/health || curl -sf -m 3 http://127.0.0.1:9101/ || echo 'provision_http_fail'; "
        "systemctl is-active silent-olcrtc-provision 2>/dev/null || systemctl is-active olcrtc-host-provision 2>/dev/null || "
        "ls /etc/systemd/system/*provision* 2>/dev/null | head"
    ))
    c.close()


if __name__ == "__main__":
    main()
