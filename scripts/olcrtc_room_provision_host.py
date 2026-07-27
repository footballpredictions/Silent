"""Host-side Playwright provision (когда в Docker API нет chromium).

1) Один раз залогинься и сохрани storage_state:
   python scripts/olcrtc_room_provision_host.py login telemost
   python scripts/olcrtc_room_provision_host.py login wbstream

   WB: скрипт сам ждёт свежий accessToken (не надо жать Enter).
   Telemost: после логина нажми Enter.

2) Создать комнаты и записать в DB на VPS (нужен SSH/.env.deploy):
   python scripts/olcrtc_room_provision_host.py create-all

3) Полный цикл WB (login → 2 комнаты → sync token + rooms на прод):
   python scripts/olcrtc_room_provision_host.py refresh-wb

Или только локально создать и напечатать room id:
   python scripts/olcrtc_room_provision_host.py create telemost
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

STATE_DIR = ROOT / "update" / "olcrtc" / "agent_states"
TELEMOST_STATE = STATE_DIR / "telemost_state.json"
WB_STATE = STATE_DIR / "wbstream_state.json"

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _wb_token_meta(storage_state: dict) -> tuple[str, int]:
    """return (accessToken, ttl_ms) from Playwright storage_state."""
    for origin in storage_state.get("origins") or []:
        if not isinstance(origin, dict):
            continue
        for item in origin.get("localStorage") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "") != "wb_auth_auth_slice":
                continue
            raw = item.get("value")
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            tok = str((data or {}).get("accessToken") or "").strip()
            ttl = int((data or {}).get("ttl") or 0)
            if tok.startswith("eyJ"):
                return tok, ttl
    return "", 0


def _wb_token_fresh(storage_state: dict, *, skew_ms: int = 5_000) -> bool:
    tok, ttl = _wb_token_meta(storage_state)
    if not tok:
        return False
    if ttl <= 0:
        return True
    # WB отдаёт accessToken с ttl ≈ 45–90с — нельзя требовать +60с запаса.
    return ttl > int(time.time() * 1000) + skew_ms


async def _read_page_storage_state(context) -> dict:
    return await context.storage_state()


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
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        # Переиспользуем старый state — иногда wbx-refresh сам обновляет JWT.
        ctx_kwargs: dict = {
            "user_agent": _CHROME_UA,
            "locale": "ru-RU",
            "viewport": {"width": 1280, "height": 800},
        }
        if provider == "wbstream" and out.is_file():
            ctx_kwargs["storage_state"] = str(out)
            print(f"подставляю старый state: {out}", flush=True)
        context = await browser.new_context(**ctx_kwargs)
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        if provider == "wbstream":
            print(
                "WB: залогинься в открывшемся Chromium "
                "(аккаунт, который МОЖЕТ создавать комнаты).\n"
                "Скрипт сам сохранит cookies, когда появится свежий accessToken…",
                flush=True,
            )
            deadline = time.time() + 10 * 60
            last_msg = ""
            while time.time() < deadline:
                state = await _read_page_storage_state(context)
                tok, ttl = _wb_token_meta(state)
                now = int(time.time() * 1000)
                # Достаточно любого живого JWT (>5с) — сразу пишем и синкаем на VPS.
                if tok and (ttl <= 0 or ttl > now + 5_000):
                    await context.storage_state(path=str(out))
                    await browser.close()
                    left_s = max(0, (ttl - now) // 1000) if ttl > 0 else -1
                    print(f"saved {out} (token OK, ~{left_s}s до ttl)", flush=True)
                    return
                msg = (
                    "ждём логин…"
                    if not tok
                    else f"токен есть, но ttl протух/короткий (ttl={ttl}, now={now})"
                )
                if msg != last_msg:
                    print(msg, flush=True)
                    last_msg = msg
                await page.wait_for_timeout(1000)
            await browser.close()
            raise SystemExit("timeout: не дождались свежего WB accessToken за 10 мин")

        print(f"Залогинься в браузере ({provider}), затем нажми Enter здесь…")
        await asyncio.get_event_loop().run_in_executor(None, input)
        await context.storage_state(path=str(out))
        await browser.close()
    print("saved", out)


async def create_one(provider: str, *, headless: bool = True) -> str:
    from ai.olcrtc_room_provision import create_room

    path = TELEMOST_STATE if provider == "telemost" else WB_STATE
    if not path.is_file():
        raise SystemExit(f"нет {path} — сначала: login {provider}")
    state = json.loads(path.read_text(encoding="utf-8"))
    if provider == "wbstream" and not _wb_token_fresh(state):
        raise SystemExit(
            f"WB storage_state протух ({path}) — сначала: "
            "python scripts/olcrtc_room_provision_host.py login wbstream"
        )
    # WB antibot на datacenter IP часто ломает headless — пробуем headed.
    result = await create_room(provider, state, headless=headless)
    if not result.ok and provider == "wbstream" and headless:
        print("create headless failed, retry headed:", result.message)
        result = await create_room(provider, state, headless=False)
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
            rid = await create_one(provider, headless=(provider != "wbstream"))
            rooms[provider][slot] = rid

    await _seed_rooms_remote(rooms)
    print("Done — rooms patched. Run: python scripts/configure_olcrtc_prod.py or deploy_olcrtc.py")


async def _seed_rooms_remote(rooms: dict) -> None:
    from _deploy_common import connect, run

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
            # keep non-touched providers; replace rooms for this provider
            new_rooms = []
            for sid, url in slots.items():
                if not url:
                    continue
                new_rooms.append({{
                    "id": sid,
                    "url": url,
                    "max_clients": 25,
                    "device_types": [sid],
                }})
            if new_rooms:
                p["rooms"] = new_rooms
                p["room"] = new_rooms[0]["url"]
        await db.execute(
            text("UPDATE app_settings SET value=:v WHERE key='olcrtc_settings'"),
            {{"v": json.dumps(d, ensure_ascii=False)}},
        )
        await db.commit()
        print("db_ok", ROOMS)

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


async def refresh_wb() -> None:
    """login (if needed) → 2 WB rooms → upload state + seed rooms + sync auth token on VPS."""
    from _deploy_common import connect, run

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    need_login = True
    if WB_STATE.is_file():
        state = json.loads(WB_STATE.read_text(encoding="utf-8"))
        if _wb_token_fresh(state):
            need_login = False
            print("local WB token still fresh — skip login")
    if need_login:
        await login("wbstream")

    # Two rooms: android + pc (separate hosts).
    android_room = await create_one("wbstream", headless=False)
    pc_room = await create_one("wbstream", headless=False)
    rooms = {"wbstream": {"android": android_room, "pc": pc_room}}
    await _seed_rooms_remote(rooms)

    # Upload storage_state to VPS host + container, bootstrap accounts, sync token, apply units.
    client = connect()
    sftp = client.open_sftp()
    remote_host_state = "/opt/silent-vpn/olcrtc/agent_states/wbstream_state.json"
    remote_backend_state = "/opt/silent-vpn/backend/update/olcrtc/agent_states/wbstream_state.json"
    run(client, "mkdir -p /opt/silent-vpn/olcrtc/agent_states /opt/silent-vpn/backend/update/olcrtc/agent_states")
    sftp.put(str(WB_STATE), remote_host_state)
    sftp.put(str(WB_STATE), remote_backend_state)
    sftp.close()
    print("uploaded wbstream_state.json")

    boot = r"""
import asyncio, json
from pathlib import Path
from sqlalchemy import text
from app.database import AsyncSessionLocal
from app.services.olcrtc_room_accounts import (
    OlcrtcRoomAccounts,
    ProviderAccount,
    extract_wb_access_token,
    load_room_accounts,
    save_room_accounts,
    sync_wbstream_auth_token_to_settings,
)
from app.services.olcrtc_rooms_db import (
    sync_rooms_from_settings_json,
    write_all_unit_yaml_from_db,
)

async def main():
    state_path = Path("/app/update/olcrtc/agent_states/wbstream_state.json")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    tok = extract_wb_access_token(state)
    print("token_len", len(tok or ""))
    async with AsyncSessionLocal() as db:
        acc = await load_room_accounts(db)
        if not acc.wbstream:
            acc.wbstream = [ProviderAccount(label="host-wb", storage_state=state)]
        else:
            acc.wbstream[0].storage_state = state
            acc.wbstream[0].label = acc.wbstream[0].label or "host-wb"
        await save_room_accounts(db, acc)
        synced = await sync_wbstream_auth_token_to_settings(db)
        print("auth_token_synced", bool(synced), "len", len(synced or ""))
        # revive previously broken android wb units with new rooms from settings
        await db.execute(text(
            "UPDATE olcrtc_rooms SET status='active', last_error='' "
            "WHERE provider='wbstream' AND unit_name LIKE 'android-wbstream%'"
        ))
        await db.execute(text(
            "DELETE FROM olcrtc_room_sticky s USING olcrtc_rooms r "
            "WHERE s.room_id=r.id AND r.provider='wbstream'"
        ))
        n = await sync_rooms_from_settings_json(db)
        files = await write_all_unit_yaml_from_db(db)
        print("rooms_synced", n, "yaml", ",".join(sorted(files)))
        await db.commit()

asyncio.run(main())
"""
    sftp2 = client.open_sftp()
    sftp2.putfo(__import__("io").BytesIO(boot.encode()), "/tmp/refresh_wb_boot.py")
    sftp2.close()
    run(client, "docker cp /opt/silent-vpn/backend/update/olcrtc/agent_states/wbstream_state.json "
                "backend-api-1:/app/update/olcrtc/agent_states/wbstream_state.json")
    run(client, "docker cp /tmp/refresh_wb_boot.py backend-api-1:/tmp/refresh_wb_boot.py")
    print(run(client, "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/refresh_wb_boot.py", timeout=120))

    # copy yaml to host + restart wb units
    print(
        run(
            client,
            "mkdir -p /opt/silent-vpn/olcrtc; "
            "for y in $(docker exec backend-api-1 sh -c 'ls /app/update/olcrtc/server*wbstream*.yaml 2>/dev/null'); do "
            "  b=$(basename \"$y\"); docker cp \"backend-api-1:$y\" \"/opt/silent-vpn/olcrtc/$b\"; "
            "  echo host_yaml $b; "
            "done; "
            "systemctl restart olcrtc@android-wbstream olcrtc@pc-wbstream || true; "
            "sleep 2; "
            "systemctl is-active olcrtc@android-wbstream olcrtc@pc-wbstream || true; "
            "journalctl -u olcrtc@android-wbstream -n 12 --no-pager | "
            "sed 's/eyJ[A-Za-z0-9_.=-]*/JWT/g' | tail -n 12",
            timeout=90,
        )
    )
    client.close()
    print("refresh-wb done")
    print("android room:", android_room)
    print("pc room:", pc_room)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "cmd",
        choices=["login", "create", "create-all", "refresh-wb"],
    )
    ap.add_argument("provider", nargs="?", choices=["telemost", "wbstream"])
    args = ap.parse_args()
    if args.cmd == "login":
        if not args.provider:
            raise SystemExit("login needs provider")
        asyncio.run(login(args.provider))
    elif args.cmd == "create":
        if not args.provider:
            raise SystemExit("create needs provider")
        asyncio.run(create_one(args.provider, headless=False))
    elif args.cmd == "create-all":
        asyncio.run(create_all_and_seed())
    else:
        asyncio.run(refresh_wb())


if __name__ == "__main__":
    main()
