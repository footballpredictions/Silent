"""WB API create — перебор RoomType."""
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
        owner = str(jwt_payload(tok).get("user") or "")
        headers = {
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
            "Origin": "https://stream.wb.ru",
            "Referer": "https://stream.wb.ru/",
            "User-Agent": "Mozilla/5.0",
        }
        types = [
            "ROOM_TYPE_PRIVATE", "ROOM_TYPE_PUBLIC", "ROOM_TYPE_STREAM",
            "PRIVATE", "PUBLIC", "STREAM", 1, 2, 3, "1", "2",
            "room_type_private", "private", "public",
        ]
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            for rt in types:
                body = {"roomInfo": {"title": "silent-vpn", "isPublic": False, "ownerId": owner, "roomType": rt}}
                r = await client.post("https://stream.wb.ru/api-room/api/v1/room", headers=headers, json=body)
                print("rt=", rt, "->", r.status_code, (r.text or "")[:180])
                if r.status_code in (200, 201):
                    print("SUCCESS", r.text[:500])
                    return
                body2 = {"roomInfo": {"title": "silent-vpn", "isPublic": False, "ownerId": owner, "RoomType": rt}}
                r2 = await client.post("https://stream.wb.ru/api-room/api/v1/room", headers=headers, json=body2)
                print("RT=", rt, "->", r2.status_code, (r2.text or "")[:180])
                if r2.status_code in (200, 201):
                    print("SUCCESS", r2.text[:500])
                    return

asyncio.run(main())
'''
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/wb_api_rt.py")
    run(client, "docker cp /tmp/wb_api_rt.py backend-api-1:/tmp/wb_api_rt.py")
    print(run(client, "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/wb_api_rt.py"))
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
