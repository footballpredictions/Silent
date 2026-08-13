"""WB API create — OwnerId из jwt.user."""
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
    py = r'''
import asyncio, base64, json, httpx
from app.database import AsyncSessionLocal
from app.services.olcrtc_room_accounts import resolve_wbstream_access_token

def jwt_payload(tok: str) -> dict:
    part = tok.split(".")[1]
    pad = "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part + pad))

async def main():
    async with AsyncSessionLocal() as db:
        tok = await resolve_wbstream_access_token(db)
        payload = jwt_payload(tok)
        user = payload.get("user")
        print("user_type", type(user).__name__, "user=", json.dumps(user, ensure_ascii=False)[:300] if not isinstance(user, (dict, list)) else json.dumps(user, ensure_ascii=False)[:500])
        owner = ""
        if isinstance(user, dict):
            owner = str(user.get("id") or user.get("userId") or user.get("ownerId") or user.get("uuid") or "")
        elif isinstance(user, str):
            owner = user
        print("owner", owner)
        if not owner:
            print("FAIL")
            return
        headers = {
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
            "Origin": "https://stream.wb.ru",
            "Referer": "https://stream.wb.ru/",
            "User-Agent": "Mozilla/5.0",
        }
        body = {"roomInfo": {"title": "silent-vpn", "isPublic": False, "ownerId": owner}}
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.post("https://stream.wb.ru/api-room/api/v1/room", headers=headers, json=body)
            print("status", r.status_code, (r.text or "")[:600])

asyncio.run(main())
'''
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/wb_api_user.py")
    run(client, "docker cp /tmp/wb_api_user.py backend-api-1:/tmp/wb_api_user.py")
    print(run(client, "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/wb_api_user.py"))
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
