"""Host-side Playwright provision (когда в Docker API нет chromium).

1) Один раз залогинься и сохрани storage_state:
   python scripts/olcrtc_room_provision_host.py login telemost
   python scripts/olcrtc_room_provision_host.py login wbstream

2) Создать комнаты и записать в DB на VPS (нужен SSH/.env.deploy):
   python scripts/olcrtc_room_provision_host.py create-all

Или только локально создать и напечатать room id:
   python scripts/olcrtc_room_provision_host.py create telemost
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

STATE_DIR = ROOT / "update" / "olcrtc" / "agent_states"
TELEMOST_STATE = STATE_DIR / "telemost_state.json"
WB_STATE = STATE_DIR / "wbstream_state.json"


async def login(provider: str) -> None:
    from playwright.async_api import async_playwright

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    url = (
        "https://telemost.yandex.ru/"
        if provider == "telemost"
        else "https://stream.wb.ru/"
    )
    out = TELEMOST_STATE if provider == "telemost" else WB_STATE
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        print(f"Залогинься в браузере ({provider}), затем нажми Enter здесь…")
        await asyncio.get_event_loop().run_in_executor(None, input)
        await context.storage_state(path=str(out))
        await browser.close()
    print("saved", out)


async def create_one(provider: str) -> str:
    from ai.olcrtc_room_provision import create_room

    path = TELEMOST_STATE if provider == "telemost" else WB_STATE
    if not path.is_file():
        raise SystemExit(f"нет {path} — сначала: login {provider}")
    state = json.loads(path.read_text(encoding="utf-8"))
    result = await create_room(provider, state, headless=True)
    if not result.ok:
        raise SystemExit(result.message)
    print(provider, result.room_id)
    return result.room_id


async def create_all_and_seed() -> None:
    """Создаёт pc+android для wb+telemost и пишет в prod DB через SSH docker exec."""
    from _deploy_common import connect, run

    rooms = {
        "telemost": {"pc": "", "android": ""},
        "wbstream": {"pc": "", "android": ""},
    }
    for provider in ("telemost", "wbstream"):
        for slot in ("pc", "android"):
            rid = await create_one(provider)
            rooms[provider][slot] = rid

    patch = json.dumps(rooms)
    seed = f"""
import json, asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal

ROOMS = {patch!r}

async def main():
    async with AsyncSessionLocal() as db:
        r = await db.execute(text("SELECT value FROM app_settings WHERE key='olcrtc_settings'"))
        row = r.fetchone()
        if not row:
            print("no_settings")
            return
        d = json.loads(row[0])
        providers = d.setdefault("providers", {{}})
        for pname, slots in json.loads(ROOMS).items():
            p = providers.setdefault(pname, {{"enabled": True, "transport": "vp8channel", "rooms": []}})
            p["enabled"] = True
            p["transport"] = "vp8channel"
            new_rooms = []
            for sid, url in slots.items():
                new_rooms.append({{
                    "id": sid,
                    "url": url,
                    "max_clients": 4,
                    "device_types": [sid],
                }})
            p["rooms"] = new_rooms
            p["room"] = new_rooms[0]["url"] if new_rooms else ""
        await db.execute(
            text("UPDATE app_settings SET value=:v WHERE key='olcrtc_settings'"),
            {{"v": json.dumps(d, ensure_ascii=False)}},
        )
        await db.commit()
        print("db_ok")

asyncio.run(main())
"""
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(__import__("io").BytesIO(seed.encode()), "/tmp/patch_olcrtc_rooms.py")
    sftp.close()
    run(client, "docker cp /tmp/patch_olcrtc_rooms.py backend-api-1:/tmp/patch_olcrtc_rooms.py")
    run(
        client,
        "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/patch_olcrtc_rooms.py",
    )
    client.close()
    print("Done — rooms patched. Run: python scripts/configure_olcrtc_prod.py or deploy_olcrtc.py")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["login", "create", "create-all"])
    ap.add_argument("provider", nargs="?", choices=["telemost", "wbstream"])
    args = ap.parse_args()
    if args.cmd == "login":
        if not args.provider:
            raise SystemExit("login needs provider")
        asyncio.run(login(args.provider))
    elif args.cmd == "create":
        if not args.provider:
            raise SystemExit("create needs provider")
        asyncio.run(create_one(args.provider))
    else:
        asyncio.run(create_all_and_seed())


if __name__ == "__main__":
    main()
