"""Push olcrtc2.env to Hive cell and (re)start systemd unit — never on queen."""
from __future__ import annotations

import logging
from typing import Any

import paramiko
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.olcrtc2_settings import DEFAULT_CELL_IP, load_olcrtc2_settings

logger = logging.getLogger(__name__)

QUEEN_IP = "132.243.234.162"
REMOTE = "/opt/silent-vpn/olcrtc2"


async def apply_olcrtc2_to_cell(db: AsyncSession) -> dict[str, Any]:
    settings = await load_olcrtc2_settings(db)
    cell_ip = (settings.get("cell_ip") or DEFAULT_CELL_IP).strip()
    if cell_ip == QUEEN_IP:
        return {"ok": False, "message": "refuse: cannot deploy olcrtc2 on WDTT queen"}

    from sqlalchemy import select
    from app.models.hive_cell import HiveCell
    from app.services.hive_service import resolve_ssh_password

    row = (
        await db.execute(select(HiveCell).where(HiveCell.public_ip == cell_ip))
    ).scalar_one_or_none()
    if not row:
        return {"ok": False, "message": f"cell {cell_ip} not in hive_cells"}
    pwd = resolve_ssh_password(row)
    if not pwd:
        return {"ok": False, "message": f"no SSH password for cell {cell_ip}"}

    room = (settings.get("room") or "").strip()
    key = (settings.get("crypto_key") or "").strip()
    if not settings.get("enabled"):
        # stop unit
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(cell_ip, username="root", password=pwd, timeout=20)
            client.exec_command("systemctl stop olcrtc2-srv.service", timeout=60)
            client.close()
            return {"ok": True, "message": "stopped olcrtc2-srv (disabled)", "cell_ip": cell_ip}
        except Exception as e:
            return {"ok": False, "message": str(e)[:200]}

    if not room or len(key) != 64:
        return {"ok": False, "message": "enabled but room/key incomplete"}

    env = (
        "OLCRTC2_MODE=telemost\n"
        f"OLCRTC2_ROOM={room}\n"
        f"OLCRTC2_KEY={key}\n"
    )
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(cell_ip, username="root", password=pwd, timeout=25)
        sftp = client.open_sftp()
        import io

        sftp.putfo(io.BytesIO(env.encode()), f"{REMOTE}/olcrtc2.env")
        sftp.close()
        _, stdout, stderr = client.exec_command(
            "systemctl daemon-reload; "
            "systemctl restart olcrtc2-srv.service; "
            "sleep 2; "
            "systemctl is-active olcrtc2-srv.service; "
            "systemctl status olcrtc2-srv.service --no-pager -l | head -n 20",
            timeout=90,
        )
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        client.close()
        active = "active" in out.splitlines()[0] if out.strip() else False
        return {
            "ok": active,
            "message": "restarted olcrtc2-srv" if active else "unit not active",
            "cell_ip": cell_ip,
            "detail": (out + "\n" + err)[:1500],
        }
    except Exception as e:
        logger.exception("apply_olcrtc2_to_cell")
        return {"ok": False, "message": str(e)[:200], "cell_ip": cell_ip}
