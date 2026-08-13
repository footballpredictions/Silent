"""Tear WB/orphan units with journal not-found; rebuild warm pool; report."""
from __future__ import annotations

import io
import json
import re
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
        for ip in ("78.17.74.27","87.58.213.193"):
            r=(await db.execute(select(HiveCell).where(HiveCell.public_ip==ip))).scalar_one()
            out[ip]=resolve_ssh_password(r) or ""
        print(json.dumps(out))
asyncio.run(main())
"""

HEAL_DB = r"""
import asyncio, json, sys
from sqlalchemy import delete, select
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
from app.services.olcrtc2_assign import ensure_warm_pool
from app.services.olcrtc2_cell_units import teardown_olcrtc2_unit
from app.services.olcrtc2_settings import load_olcrtc2_settings, enabled_providers

async def main():
    mode = sys.argv[1]  # wb|all
    async with AsyncSessionLocal() as db:
        settings = await load_olcrtc2_settings(db)
        rooms = (await db.execute(select(Olcrtc2Room))).scalars().all()
        keep_units = []
        torn = 0
        for r in list(rooms):
            if mode == "wb" and (r.provider or "") != "wbstream":
                keep_units.append(r.unit_name)
                continue
            # tear all WB (or all) — rebuild warm; kills stale WB conferences
            await db.execute(delete(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id == r.id))
            await teardown_olcrtc2_unit(db, r)
            if (r.provider or "") == "wbstream":
                try:
                    from ai.olcrtc_wb_api import delete_wbstream_room_api
                    tok = (r.auth_token or "").strip()
                    if tok.startswith("eyJ") and r.room_url:
                        await delete_wbstream_room_api(tok, r.room_url)
                except Exception as e:
                    print("remote_del_err", str(e)[:80])
            await db.delete(r)
            await db.commit()
            torn += 1
        # wipe orphan envs on cells happens via SSH below; return keep list for telemost if wb-only
        if mode == "wb":
            left = (await db.execute(select(Olcrtc2Room))).scalars().all()
            keep_units = [r.unit_name for r in left if r.unit_name]
        print(json.dumps({
            "torn": torn,
            "keep_units": keep_units,
            "warm_target": int(settings.get("warm_pool_per_dt") or 12),
            "providers": enabled_providers(settings),
        }))
        warm = await ensure_warm_pool(db)
        print("WARM", json.dumps(warm, ensure_ascii=False, default=str))
        left = (await db.execute(select(Olcrtc2Room))).scalars().all()
        by = {}
        for r in left:
            by.setdefault(f"{r.provider}:{r.device_type}", 0)
            by[f"{r.provider}:{r.device_type}"] += 1
        print("AFTER_COUNTS", json.dumps(by))
asyncio.run(main())
"""


def wipe_orphans(ip: str, pwd: str, keep: set[str]) -> str:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(ip, username="root", password=pwd, timeout=25)
    script = (
        "python3 - <<'PY'\n"
        "import json, subprocess\n"
        "from pathlib import Path\n"
        f"keep=set({json.dumps(sorted(keep))})\n"
        "envd=Path('/opt/silent-vpn/olcrtc2/env.d')\n"
        "removed=[]\n"
        "for p in list(envd.glob('*.env')):\n"
        "  u=p.stem\n"
        "  if u in keep: continue\n"
        "  subprocess.run(['systemctl','stop',f'olcrtc2@{u}.service'], capture_output=True)\n"
        "  subprocess.run(['systemctl','reset-failed',f'olcrtc2@{u}.service'], capture_output=True)\n"
        "  p.unlink(missing_ok=True)\n"
        "  removed.append(u)\n"
        "print('removed', len(removed), removed[:30])\n"
        "print('left', sorted(x.stem for x in envd.glob('*.env')))\n"
        "PY\n"
    )
    _, o, e = c.exec_command(script, timeout=120)
    out = (o.read() + e.read()).decode("utf-8", "replace")
    c.close()
    return out


def main() -> None:
    mode = "wb" if len(sys.argv) < 2 else sys.argv[1]
    if mode not in ("wb", "all"):
        mode = "wb"
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(CREDS.encode()), "/tmp/cell_pwds.py")
    sftp.putfo(io.BytesIO(HEAL_DB.encode()), "/tmp/heal_wb_db.py")
    sftp.close()
    run(queen, "docker cp /tmp/cell_pwds.py backend-api-1:/tmp/cell_pwds.py")
    run(queen, "docker cp /tmp/heal_wb_db.py backend-api-1:/tmp/heal_wb_db.py")
    print("=== DB tear+warm ===")
    print(run(
        queen,
        f"docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/heal_wb_db.py {mode}",
        timeout=900,
    ))
    # collect keep units after warm
    KEEP = r"""
import asyncio, json
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room
async def main():
    async with AsyncSessionLocal() as db:
        rows=(await db.execute(select(Olcrtc2Room))).scalars().all()
        print(json.dumps({
            "units": [r.unit_name for r in rows if r.unit_name],
            "by": {}
        }))
        from collections import Counter
        c=Counter(f"{r.provider}:{r.device_type}" for r in rows)
        print("COUNTS", json.dumps(dict(c)))
asyncio.run(main())
"""
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(KEEP.encode()), "/tmp/keep_units.py")
    sftp.close()
    run(queen, "docker cp /tmp/keep_units.py backend-api-1:/tmp/keep_units.py")
    keep_raw = run(queen, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/keep_units.py")
    print(keep_raw)
    units = []
    for ln in keep_raw.splitlines():
        if ln.strip().startswith("{") and "units" in ln:
            units = json.loads(ln).get("units") or []
    pwd_raw = run(queen, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/cell_pwds.py")
    queen.close()
    pwds = json.loads([ln for ln in pwd_raw.splitlines() if ln.strip().startswith("{")][-1])
    keep = set(units)
    for ip, pwd in pwds.items():
        print(f"=== wipe orphans on {ip} ===")
        print(wipe_orphans(ip, pwd, keep))
    print("HEAL_WB_DONE")


if __name__ == "__main__":
    main()
