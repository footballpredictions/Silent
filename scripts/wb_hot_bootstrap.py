#!/usr/bin/env python3
"""WB hot bootstrap — один Chromium, account JWT, 2 комнаты, заливка на прод.

НЕ использует guest (authType=none) — только залогиненный аккаунт.

  cd backend
  python scripts/wb_hot_bootstrap.py

В открывшемся Chromium нажми «Войти» и залогинься. Скрипт сам поймает
токен, создаст android+pc комнаты и зальёт olcrtc@*-wbstream.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _deploy_common import CONTAINER, REMOTE, connect, run  # noqa: E402

STATE_DIR = ROOT / "update" / "olcrtc" / "agent_states"
WB_STATE = STATE_DIR / "wbstream_state.json"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.I,
)

CREATE_ENDPOINTS = [
    # WB: CreateRoomRequest.RoomInfo обязателен
    (
        "POST",
        "https://stream.wb.ru/api-room/api/v1/room",
        '{"roomInfo":{"title":"silent-vpn","isPublic":false}}',
    ),
    (
        "POST",
        "https://stream.wb.ru/api-room/api/v1/room",
        '{"RoomInfo":{"title":"silent-vpn"}}',
    ),
    (
        "POST",
        "https://stream.wb.ru/api-room/api/v1/room",
        '{"room_info":{"title":"silent-vpn"}}',
    ),
]


def _left_ms(ttl: int) -> int:
    if ttl <= 0:
        return 0
    return ttl - int(time.time() * 1000)


def _extract_uuid(text: str) -> str:
    m = UUID_RE.search(text or "")
    return m.group(1) if m else ""


async def _auth(page) -> dict[str, Any]:
    data = await page.evaluate(
        """() => {
          try {
            const raw = localStorage.getItem('wb_auth_auth_slice');
            if (!raw) return {tok:'', ttl:0, authType:''};
            const j = JSON.parse(raw);
            return {
              tok: (j && j.accessToken) || '',
              ttl: Number((j && j.ttl) || 0),
              authType: String((j && j.authType) || ''),
            };
          } catch (e) { return {tok:'', ttl:0, authType:''}; }
        }"""
    )
    return {
        "tok": str(data.get("tok") or ""),
        "ttl": int(data.get("ttl") or 0),
        "authType": str(data.get("authType") or ""),
    }


def _is_account(auth: dict[str, Any], *, min_left_ms: int) -> bool:
    tok = auth["tok"]
    atype = (auth["authType"] or "").lower()
    left = _left_ms(auth["ttl"])
    if not tok or left < min_left_ms:
        return False
    # guest бесполезен для create/host
    if atype in ("", "none"):
        return False
    return True


async def _click_login(page) -> None:
    for sel in (
        'button:has-text("Войти")',
        'a:has-text("Войти")',
        'text=Войти',
        'button:has-text("Log in")',
        '[data-testid*="login"]',
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible(timeout=1200):
                await loc.click(timeout=5000)
                print(f"нажал: {sel}", flush=True)
                return
        except Exception:
            continue


async def _wait_account_token(page, *, timeout_s: int = 600) -> str:
    print(
        "\n"
        "############################################################\n"
        "#  CHROMIUM ОТКРЫТ — ЗАЛОГИНЬСЯ В WB STREAM (кнопка Войти) #\n"
        "#  Guest НЕ подойдёт. Нужен аккаунт с правом создавать     #\n"
        "#  комнаты. Жду до 10 минут.                               #\n"
        "############################################################\n",
        flush=True,
    )
    await _click_login(page)
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        auth = await _auth(page)
        left = _left_ms(auth["ttl"])
        msg = (
            f"authType={auth['authType'] or '∅'} "
            f"tok={'yes' if auth['tok'] else 'no'} "
            f"left≈{max(0, left)//1000}s"
        )
        if msg != last:
            print(msg, flush=True)
            last = msg
        if _is_account(auth, min_left_ms=10_000):
            print(f"ACCOUNT OK type={auth['authType']} left≈{left//1000}s", flush=True)
            return auth["tok"]
        await page.wait_for_timeout(1000)
    raise SystemExit("timeout 10м: нет account JWT — залогинься в Chromium")


async def _api_create(page, token: str) -> str:
    result = await page.evaluate(
        """async ({token, endpoints}) => {
          const tries = [];
          for (const [method, url, body] of endpoints) {
            try {
              const resp = await fetch(url, {
                method,
                headers: {
                  Authorization: 'Bearer ' + token,
                  'Content-Type': 'application/json',
                  Accept: 'application/json',
                },
                body: body,
                credentials: 'include',
              });
              const text = await resp.text();
              tries.push({url, status: resp.status, text: text.slice(0, 400)});
              if (resp.ok) return {ok:true, url, text};
            } catch (e) {
              tries.push({url, error: String(e)});
            }
          }
          return {ok:false, tries};
        }""",
        {"token": token, "endpoints": [list(x) for x in CREATE_ENDPOINTS]},
    )
    if result.get("ok"):
        rid = _extract_uuid(str(result.get("text") or ""))
        print(f"API OK {result.get('url')} → {rid or '?'}", flush=True)
        return rid
    for t in (result.get("tries") or [])[:5]:
        print(
            f"  API {t.get('url')} status={t.get('status')} "
            f"{str(t.get('text') or t.get('error') or '')[:140]}",
            flush=True,
        )
    return ""


async def _ui_create(page) -> str:
    await page.goto("https://stream.wb.ru/", wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(1200)
    for sel in (
        'button:has-text("Новая видеовстреча")',
        'text=Новая видеовстреча',
        'button:has-text("Создать встречу")',
        'button:has-text("Новая комната")',
        'button:has-text("Создать")',
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible(timeout=1500):
                await loc.click(timeout=8000)
                print(f"UI click {sel}", flush=True)
                break
        except Exception:
            continue
    else:
        shot = STATE_DIR / f"wb_ui_fail_{int(time.time())}.png"
        try:
            await page.screenshot(path=str(shot), full_page=True)
            print(f"нет кнопки create → {shot}", flush=True)
        except Exception:
            pass
        return ""

    for _ in range(40):
        await page.wait_for_timeout(500)
        rid = _extract_uuid(page.url)
        if rid:
            print(f"UI room={rid}", flush=True)
            return rid
    print(f"UI no uuid url={page.url}", flush=True)
    return ""


async def _create_two(page) -> tuple[str, str]:
    rooms: list[str] = []
    for label in ("android", "pc"):
        auth = await _auth(page)
        if not _is_account(auth, min_left_ms=8_000):
            print(f"токен слабый перед {label} — жду refresh…", flush=True)
            # не reload-spam: просто подождать ротацию ttl
            for _ in range(90):
                await page.wait_for_timeout(1000)
                auth = await _auth(page)
                if _is_account(auth, min_left_ms=12_000):
                    break
            else:
                raise SystemExit(f"токен не обновился перед {label}")
        print(f"=== room {label} ===", flush=True)
        rid = await _api_create(page, auth["tok"])
        if not rid:
            rid = await _ui_create(page)
        if not rid or rid in rooms:
            raise SystemExit(f"не создал уникальную комнату {label}: {rid!r}")
        rooms.append(rid)
        print(f"{label} = {rid}", flush=True)
        if label == "android":
            await page.goto("https://stream.wb.ru/", wait_until="domcontentloaded")
            await page.wait_for_timeout(700)
    return rooms[0], rooms[1]


def _push(android_room: str, pc_room: str, token: str) -> None:
    print("PUSH → VPS", flush=True)
    client = connect()
    sftp = client.open_sftp()
    run(
        client,
        "mkdir -p /opt/silent-vpn/olcrtc/agent_states "
        f"{REMOTE}/update/olcrtc/agent_states",
    )
    sftp.put(str(WB_STATE), "/opt/silent-vpn/olcrtc/agent_states/wbstream_state.json")
    sftp.put(str(WB_STATE), f"{REMOTE}/update/olcrtc/agent_states/wbstream_state.json")

    payload = {"android": android_room, "pc": pc_room, "token": token}
    remote_py = f"""
import asyncio, json, time
from pathlib import Path
from sqlalchemy import text
from app.database import AsyncSessionLocal
from app.services.olcrtc_rooms_db import write_all_unit_yaml_from_db
from app.services.olcrtc_settings import load_olcrtc_settings
from app.services.olcrtc_room_accounts import (
    ProviderAccount, load_room_accounts, save_room_accounts,
)

DATA = json.loads({json.dumps(payload, ensure_ascii=False)!r})
STATE = json.loads(Path("/app/update/olcrtc/agent_states/wbstream_state.json").read_text())

async def main():
    async with AsyncSessionLocal() as db:
        acc = await load_room_accounts(db)
        if not acc.wbstream:
            acc.wbstream = [ProviderAccount(label="host-wb", storage_state=STATE)]
        else:
            acc.wbstream[0].storage_state = STATE
            acc.wbstream[0].label = acc.wbstream[0].label or "host-wb"
        await save_room_accounts(db, acc)

        r = await db.execute(text("SELECT value FROM app_settings WHERE key='olcrtc_settings'"))
        d = json.loads(r.fetchone()[0])
        wb = d.setdefault("providers", {{}}).setdefault("wbstream", {{}})
        wb["enabled"] = True
        wb["auth_token"] = DATA["token"]
        wb["transport"] = "vp8channel"
        wb["rooms"] = [
            {{"id":"android","url":DATA["android"],"max_clients":25,"device_types":["android"]}},
            {{"id":"pc","url":DATA["pc"],"max_clients":25,"device_types":["pc"]}},
        ]
        wb["room"] = DATA["android"]
        await db.execute(
            text("UPDATE app_settings SET value=:v WHERE key='olcrtc_settings'"),
            {{"v": json.dumps(d, ensure_ascii=False)}},
        )
        for unit, url, dtype in (
            ("android-wbstream", DATA["android"], "android"),
            ("pc-wbstream", DATA["pc"], "pc"),
        ):
            exists = (await db.execute(
                text("SELECT id FROM olcrtc_rooms WHERE unit_name=:u"), {{"u": unit}}
            )).fetchone()
            if exists:
                await db.execute(text(
                    "UPDATE olcrtc_rooms SET room_url=:url, status='active', last_error=NULL, "
                    "slot_label=:dt, device_types=ARRAY[:dt]::varchar[], provider='wbstream', "
                    "max_clients=25, data_dir=:dd WHERE unit_name=:u"
                ), {{"url": url, "dt": dtype, "u": unit, "dd": f"data-{{unit}}"}})
            else:
                await db.execute(text(
                    "INSERT INTO olcrtc_rooms (provider, unit_name, room_url, data_dir, status, "
                    "max_clients, online_count, slot_label, device_types) "
                    "VALUES ('wbstream', :u, :url, :dd, 'active', 25, 0, :dt, ARRAY[:dt]::varchar[])"
                ), {{"u": unit, "url": url, "dd": f"data-{{unit}}", "dt": dtype}})
        await db.execute(text(
            "DELETE FROM olcrtc_room_sticky s USING olcrtc_rooms r "
            "WHERE s.room_id=r.id AND r.provider='wbstream'"
        ))
        await db.commit()
        db.expire_all()
        settings = await load_olcrtc_settings(db)
        tok = (settings.providers.get("wbstream").auth_token or "").strip()
        print("token_len", len(tok), "t", int(time.time()))
        if not tok:
            raise SystemExit("empty auth_token")
        files = await write_all_unit_yaml_from_db(db)
        print("yaml", ",".join(sorted(k for k in files if "wb" in k)))

asyncio.run(main())
"""
    sftp.putfo(io.BytesIO(remote_py.encode("utf-8")), "/tmp/wb_hot_boot.py")
    sftp.close()

    run(client, f"docker cp /tmp/wb_hot_boot.py {CONTAINER}:/tmp/wb_hot_boot.py")
    run(
        client,
        f"docker cp {REMOTE}/update/olcrtc/agent_states/wbstream_state.json "
        f"{CONTAINER}:/app/update/olcrtc/agent_states/wbstream_state.json",
    )
    run(
        client,
        f"docker exec -w /app -e PYTHONPATH=/app {CONTAINER} python /tmp/wb_hot_boot.py",
    )
    out = run(
        client,
        r"""
set -e
for u in android-wbstream pc-wbstream; do
  docker cp backend-api-1:/app/update/olcrtc/server-$u.yaml /opt/silent-vpn/olcrtc/server-$u.yaml
  echo "$u bytes=$(wc -c < /opt/silent-vpn/olcrtc/server-$u.yaml) token=$(grep -c 'token:' /opt/silent-vpn/olcrtc/server-$u.yaml || true)"
  grep -E 'id:|provider:' /opt/silent-vpn/olcrtc/server-$u.yaml | head -5
done
systemctl enable olcrtc@android-wbstream olcrtc@pc-wbstream >/dev/null 2>&1 || true
systemctl restart olcrtc@android-wbstream olcrtc@pc-wbstream
sleep 6
journalctl -u olcrtc@android-wbstream -n 30 --no-pager | sed 's/eyJ[A-Za-z0-9_.=-]*/JWT/g' | tail -n 30
""",
    )
    client.close()
    if "token=0" in out:
        raise SystemExit("YAML без token")
    print("PUSH DONE", flush=True)


async def main() -> None:
    from playwright.async_api import async_playwright

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        kwargs: dict[str, Any] = {
            "user_agent": UA,
            "locale": "ru-RU",
            "viewport": {"width": 1280, "height": 800},
        }
        if WB_STATE.is_file():
            kwargs["storage_state"] = str(WB_STATE)
            print(f"reuse cookies: {WB_STATE}", flush=True)
        ctx = await browser.new_context(**kwargs)
        page = await ctx.new_page()
        await page.goto("https://stream.wb.ru/", wait_until="domcontentloaded", timeout=60_000)

        await _wait_account_token(page, timeout_s=600)
        android_room, pc_room = await _create_two(page)

        # Сразу push — не ждать ротацию (ttl~60с, ожидание убивает JWT).
        auth = await _auth(page)
        if not _is_account(auth, min_left_ms=2_000):
            # один быстрый reload главной — часто ротирует ttl
            await page.goto("https://stream.wb.ru/", wait_until="domcontentloaded")
            for _ in range(45):
                await page.wait_for_timeout(1000)
                auth = await _auth(page)
                if _is_account(auth, min_left_ms=8_000):
                    break
            else:
                raise SystemExit("JWT протух перед push")
        token = auth["tok"]
        await ctx.storage_state(path=str(WB_STATE))
        print(f"saved state token_len={len(token)} left≈{_left_ms(auth['ttl'])//1000}s", flush=True)
        _push(android_room, pc_room, token)
        await browser.close()

    print(f"DONE {int(time.time()-t0)}s android={android_room} pc={pc_room}", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    asyncio.run(main())
