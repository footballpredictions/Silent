"""WB API create — numeric RoomType + RoomPrivacy."""
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
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            for rt in (1, 2):
                for rp in (1, 2, 3):
                    body = {
                        "roomInfo": {
                            "title": "silent-vpn",
                            "isPublic": False,
                            "ownerId": owner,
                            "roomType": rt,
                            "roomPrivacy": rp,
                        }
                    }
                    r = await client.post(
                        "https://stream.wb.ru/api-room/api/v1/room",
                        headers=headers,
                        json=body,
                    )
                    print(f"rt={rt} rp={rp} -> {r.status_code} {(r.text or '')[:220]}")
                    if r.status_code in (200, 201):
                        print("SUCCESS", r.text[:800])
                        return

asyncio.run(main())
'''
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/wb_api_enums.py")
    run(client, "docker cp /tmp/wb_api_enums.py backend-api-1:/tmp/wb_api_enums.py")
    print(run(client, "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/wb_api_enums.py"))
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
