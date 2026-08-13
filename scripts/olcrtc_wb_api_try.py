"""Проверка сети ВБ / API create без браузера."""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _deploy_common import connect, run  # noqa: E402


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    print(
        run(
            client,
            "timeout 3 bash -c 'echo >/dev/tcp/185.182.65.175/3128' && echo PROXY_OPEN || echo PROXY_CLOSED; "
            "PID=$(systemctl show -p MainPID --value silent-olcrtc-host-provision); "
            "tr '\\0' '\\n' < /proc/$PID/environ 2>/dev/null | grep -E 'PROXY_HTTP_HOST|PROXY_HTTP_USER|PROXY_HTTP_PORT|OLCRTC_' | sed 's/PASS=.*/PASS=***/' || true",
        )
    )
    py = r"""
import asyncio, json, httpx
from app.database import AsyncSessionLocal
from app.services.olcrtc_room_accounts import resolve_wbstream_access_token, load_room_accounts, resolve_storage_state

async def main():
    async with AsyncSessionLocal() as db:
        tok = await resolve_wbstream_access_token(db)
        print("token_len", len(tok or ""))
        if not tok:
            return
        headers = {
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
            "Origin": "https://stream.wb.ru",
            "Referer": "https://stream.wb.ru/",
            "User-Agent": "Mozilla/5.0",
        }
        body = {"roomInfo": {"title": "silent-vpn", "isPublic": False}}
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            r = await client.post("https://stream.wb.ru/api-room/api/v1/room", headers=headers, json=body)
            print("api_status", r.status_code, (r.text or "")[:400])

asyncio.run(main())
"""
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/wb_api_create.py")
    run(client, "docker cp /tmp/wb_api_create.py backend-api-1:/tmp/wb_api_create.py")
    print(
        run(
            client,
            "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/wb_api_create.py",
        )
    )
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
