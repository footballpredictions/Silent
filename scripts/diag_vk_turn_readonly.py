"""Read-only: test if a VK join hash can get TURN creds (simulate creds.go steps)."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from _deploy_common import connect, run

client = connect()

# Get one fresh hash from silent27
hash_cmd = r"""docker exec backend-api-1 python -c "
import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import User, VkHash

async def main():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.email=='silent27@bk.ru'))).scalar_one()
        h = (await db.execute(select(VkHash).where(VkHash.user_id==u.id, VkHash.is_active==True, VkHash.slot_index==0))).scalar_one()
        print(h.hash_value)
asyncio.run(main())
"
"""
join_hash = run(client, hash_cmd, timeout=30).strip().splitlines()[-1].strip()
print("TEST_HASH", join_hash[:24])

client.close()

def post(url, data: str, headers: dict | None = None) -> dict:
    h = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
    req = urllib.request.Request(url, data=data.encode(), headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"_error": str(e)}


VK_SECRETS = {
    "6287487": "QbYic1K3lEV5kTGiqlq2",
    "8202606": "lMRsTiMCyPnp5vfoldmn",
}

for client_id, secret in VK_SECRETS.items():
    print(f"\n=== client_id={client_id} ===")
    # step1 anonym token (token_type=messages on login.vk.com, ref 2bd5f79)
    p1 = f"client_id={client_id}&token_type=messages&client_secret={secret}&version=1&app_id={client_id}"
    r1 = post("https://login.vk.com/?act=get_anonym_token", p1)
    if "_error" in r1:
        print("step1 FAIL", r1["_error"])
        continue
    token1 = (r1.get("data") or {}).get("access_token")
    print("step1 token1", (token1 or "")[:20] or "NONE", "keys", list(r1.keys()))

    if not token1:
        print("step1 body", json.dumps(r1)[:300])
        continue

    # step3 getAnonymousToken
    link = urllib.parse.quote(f"https://vk.com/call/join/{join_hash}", safe="")
    name = urllib.parse.quote("test")
    p3 = f"vk_join_link=https://vk.com/call/join/{join_hash}&name={name}&access_token={token1}"
    url3 = f"https://api.vk.com/method/calls.getAnonymousToken?v=5.282&client_id={client_id}"
    r3 = post(url3, p3)
    if "_error" in r3:
        print("step3 FAIL", r3["_error"])
        continue
    if "error" in r3:
        print("step3 VK error", r3["error"])
        continue
    token2 = (r3.get("response") or {}).get("token", "")
    print("step3 token2", (token2 or "")[:20] or "NONE")

    if not token2:
        continue

    # step4 ok anonymLogin
    import uuid
    sd = urllib.parse.quote(json.dumps({"version": 2, "device_id": str(uuid.uuid4()), "client_version": 1.1, "client_type": "SDK_JS"}))
    p4 = f"session_data={sd}&method=auth.anonymLogin&format=JSON&application_key=CGMMEJLGDIHBABABA"
    r4 = post("https://calls.okcdn.ru/fb.do", p4)
    if "_error" in r4:
        print("step4 FAIL", r4["_error"])
        continue
    token3 = r4.get("session_key", "")
    print("step4 session_key", (token3 or "")[:20] or "NONE", "err", r4.get("error_code"), r4.get("error_msg", "")[:60])

    if not token3:
        print("step4 body", json.dumps(r4)[:300])
        continue

    # step5 joinConversationByLink — the failing step
    p5 = (
        f"joinLink={join_hash}&isVideo=false&protocolVersion=5&capabilities=2F7F"
        f"&anonymToken={token2}&method=vchat.joinConversationByLink&format=JSON"
        f"&application_key=CGMMEJLGDIHBABABA&session_key={token3}"
    )
    r5 = post("https://calls.okcdn.ru/fb.do", p5)
    if "_error" in r5:
        print("step5 FAIL", r5["_error"])
        continue
    if r5.get("turn_server"):
        print("step5 SUCCESS turn_server urls", len(r5["turn_server"].get("urls", [])))
    else:
        print("step5 FAIL (same as app)", json.dumps(r5)[:400])
