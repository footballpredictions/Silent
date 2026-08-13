"""Поставить PROXY_HTTP_HOST для WB Playwright + redeploy host-provision + smoke WB."""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _deploy_common import connect, run  # noqa: E402

# Primary HTTP proxy из Memory Bank (админка «Прокси»).
DEFAULT_PROXY_HOST = "185.182.65.175"


def main() -> None:
    client = connect()
    # Не печатаем пароль: только дописать HOST если нет.
    run(
        client,
        f"grep -q '^PROXY_HTTP_HOST=' /opt/silent-vpn/backend/.env 2>/dev/null "
        f"|| echo 'PROXY_HTTP_HOST={DEFAULT_PROXY_HOST}' >> /opt/silent-vpn/backend/.env; "
        f"grep -q '^PROXY_PRIMARY_IP=' /opt/silent-vpn/backend/.env 2>/dev/null "
        f"|| echo 'PROXY_PRIMARY_IP={DEFAULT_PROXY_HOST}' >> /opt/silent-vpn/backend/.env; "
        f"grep -E '^(PROXY_HTTP_HOST|PROXY_PRIMARY_IP)=' /opt/silent-vpn/backend/.env | head -5",
    )
    # свежий provision.py на host-provision
    sftp = client.open_sftp()
    local = ROOT / "ai" / "olcrtc_room_provision.py"
    sftp.put(str(local), "/tmp/olcrtc_room_provision.py")
    run(
        client,
        "cp /tmp/olcrtc_room_provision.py /opt/silent-vpn/olcrtc/host-provision/ai/olcrtc_room_provision.py 2>/dev/null "
        "|| (mkdir -p /opt/silent-vpn/olcrtc/host-provision/ai && "
        "cp /tmp/olcrtc_room_provision.py /opt/silent-vpn/olcrtc/host-provision/ai/olcrtc_room_provision.py); "
        "cp /tmp/olcrtc_room_provision.py /opt/silent-vpn/backend/ai/olcrtc_room_provision.py; "
        "docker cp /tmp/olcrtc_room_provision.py backend-api-1:/app/ai/olcrtc_room_provision.py; "
        "systemctl restart silent-olcrtc-host-provision; sleep 2; systemctl is-active silent-olcrtc-host-provision",
    )
    # curl WB через proxy (без печати пароля)
    print(
        run(
            client,
            "set -a; . /opt/silent-vpn/backend/.env; set +a; "
            "curl -sS -m 15 -o /dev/null -w 'wb_via_proxy %{http_code}\\n' "
            "-x \"http://${PROXY_HTTP_USER}:${PROXY_HTTP_PASS}@${PROXY_HTTP_HOST:-185.182.65.175}:${PROXY_HTTP_PORT:-3128}\" "
            "https://stream.wb.ru/ || echo wb_via_proxy fail",
        )
    )
    py = """
import asyncio, os
from app.database import AsyncSessionLocal
from app.services.olcrtc_room_accounts import load_room_accounts, resolve_storage_state, sync_wbstream_auth_token_to_settings
from app.services.olcrtc_settings import load_olcrtc_settings, save_olcrtc_settings
from app.services.olcrtc_assign import assign_public_config, release_session_room
from ai.olcrtc_room_agent import load_agent_state, save_agent_state
from ai.olcrtc_host_provision_client import create_room_best, push_storage_to_host
from ai.olcrtc_room_provision import _playwright_proxy

async def main():
    print("wb proxy configured=", bool(_playwright_proxy("wbstream")))
    async with AsyncSessionLocal() as db:
        st = await load_agent_state(db)
        st.session_mode = True
        st.enabled = True
        st.cooldown_until = ""
        await save_agent_state(db, st)
        settings = await load_olcrtc_settings(db)
        for name in ("telemost", "wbstream"):
            p = settings.providers.get(name)
            if p:
                p.enabled = True
                settings.providers[name] = p
        await save_olcrtc_settings(db, settings)
        accounts = await load_room_accounts(db)
        storage = None
        for acc in accounts.wbstream:
            storage = resolve_storage_state(acc)
            if storage:
                break
        if not storage:
            print("NO storage")
            return
        await push_storage_to_host("wbstream", storage)
        await sync_wbstream_auth_token_to_settings(db)
        print("direct create...")
        res = await create_room_best("wbstream", storage, headless=True)
        print("create ok=", res.ok, "room=", res.room_id, "msg=", (res.message or "")[:300])
        if not res.ok:
            return
        # full assign path
        cfg = await assign_public_config(db, device_type="pc", fingerprint="smoke-wb-pc-2", preferred_provider="wbstream")
        p = (cfg.get("providers") or {}).get("wbstream") or {}
        print("assign denied=", p.get("denied"), "room=", p.get("room"), "unit=", cfg.get("assigned_slot"))
        rid = p.get("room_db_id") or ""
        if rid:
            print("release", await release_session_room(db, room_db_id=rid, fingerprint="smoke-wb-pc-2", provider="wbstream", reason="smoke"))
            print("SMOKE OK wb")
        else:
            print("SMOKE FAIL no room_db_id")

asyncio.run(main())
"""
    # host-provision читает .env при старте — proxy уже в EnvironmentFile
    # но create_room_best в API container тоже может fallback — OLCRTC_HOST_ONLY=1 so only host
    # Ensure host process has PROXY_* from EnvironmentFile - already does
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/wb_smoke2.py")
    run(client, "docker cp /tmp/wb_smoke2.py backend-api-1:/tmp/wb_smoke2.py")
    # copy provision into host venv path used by server
    run(
        client,
        "HP=/opt/silent-vpn/olcrtc/host-provision; "
        "mkdir -p $HP/ai; "
        "cp /tmp/olcrtc_room_provision.py $HP/ai/olcrtc_room_provision.py; "
        "touch $HP/ai/__init__.py; "
        "systemctl restart silent-olcrtc-host-provision; sleep 3; "
        "systemctl is-active silent-olcrtc-host-provision",
    )
    time.sleep(2)
    print(
        run(
            client,
            "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/wb_smoke2.py",
        )
    )
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
