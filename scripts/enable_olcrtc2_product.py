"""Enable olcrtc2 product flags on queen DB (agent session-mode).

  cd backend
  python scripts/enable_olcrtc2_product.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

ENABLE_PY = r"""
import asyncio, json, secrets
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import AppSetting
from app.services.olcrtc2_settings import SETTINGS_KEY, load_olcrtc2_settings, save_olcrtc2_settings
from app.services.olcrtc_room_accounts import load_room_accounts

async def main():
    async with AsyncSessionLocal() as db:
        cur = await load_olcrtc2_settings(db)
        patch = {
            "enabled": True,
            "agent_enabled": True,
            "provider": "telemost",
            "cell_ip": "87.58.213.193",
            "cell_provision_url": "http://87.58.213.193:9101",
            "session_mode": True,
        }
        if not cur.get("crypto_key"):
            patch["crypto_key"] = secrets.token_hex(32)
        # keep optional diag room empty for product path
        out = await save_olcrtc2_settings(db, patch)
        acc = await load_room_accounts(db)
        has_tm = any(resolveable(a) for a in acc.telemost)
        print(json.dumps({
            "enabled": out.get("enabled"),
            "agent_enabled": out.get("agent_enabled"),
            "cell_ip": out.get("cell_ip"),
            "cell_provision_url": out.get("cell_provision_url"),
            "has_crypto_key": len(out.get("crypto_key") or "") == 64,
            "telemost_accounts": len(acc.telemost),
            "telemost_with_storage": has_tm,
        }, ensure_ascii=False))

def resolveable(a):
    try:
        from app.services.olcrtc_room_accounts import resolve_storage_state
        return bool(resolve_storage_state(a))
    except Exception:
        return False

asyncio.run(main())
"""


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    import io

    sftp.putfo(io.BytesIO(ENABLE_PY.encode()), "/tmp/enable_olcrtc2.py")
    sftp.close()
    run(client, "docker cp /tmp/enable_olcrtc2.py backend-api-1:/tmp/enable_olcrtc2.py")
    _, stdout, stderr = client.exec_command(
        "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/enable_olcrtc2.py",
        timeout=120,
    )
    print(stdout.read().decode(errors="replace"))
    err = stderr.read().decode(errors="replace")
    if err.strip():
        print(err[:500])
    run(client, "rm -f /tmp/enable_olcrtc2.py; docker exec backend-api-1 rm -f /tmp/enable_olcrtc2.py")
    client.close()


if __name__ == "__main__":
    main()
