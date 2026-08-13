"""WB create room через API (без Playwright) — OwnerId из JWT."""
from __future__ import annotations

import base64
import io
import json
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
    try:
        part = tok.split(".")[1]
        pad = "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part + pad))
    except Exception as e:
        return {"_err": str(e)}

async def main():
    async with AsyncSessionLocal() as db:
        tok = await resolve_wbstream_access_token(db)
        print("token_len", len(tok or ""))
        payload = jwt_payload(tok or "")
        print("jwt_keys", sorted(payload.keys())[:40])
        for k in ("sub", "user_id", "userId", "ownerId", "owner_id", "uid", "id", "sid"):
            if k in payload:
                print("field", k, "=", str(payload[k])[:80])
        owner = (
            str(payload.get("sub") or payload.get("user_id") or payload.get("userId")
                or payload.get("ownerId") or payload.get("uid") or "")
        )
        print("owner_candidate", owner[:80])
        if not tok or not owner:
            print("FAIL no tok/owner")
            return
        headers = {
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
            "Origin": "https://stream.wb.ru",
            "Referer": "https://stream.wb.ru/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
        }
        bodies = [
            {"roomInfo": {"title": "silent-vpn", "isPublic": False, "ownerId": owner}},
            {"roomInfo": {"title": "silent-vpn", "isPublic": False, "OwnerId": owner}},
            {"RoomInfo": {"Title": "silent-vpn", "IsPublic": False, "OwnerId": owner}},
        ]
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for i, body in enumerate(bodies):
                r = await client.post(
                    "https://stream.wb.ru/api-room/api/v1/room",
                    headers=headers,
                    json=body,
                )
                print("try", i, "status", r.status_code, (r.text or "")[:350])
                if r.status_code in (200, 201):
                    print("OK BODY", (r.text or "")[:500])
                    break

asyncio.run(main())
'''
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/wb_api_owner.py")
    run(client, "docker cp /tmp/wb_api_owner.py backend-api-1:/tmp/wb_api_owner.py")
    print(
        run(
            client,
            "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/wb_api_owner.py",
        )
    )
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
