#!/usr/bin/env python3
"""Быстрый push уже созданных WB комнат + свежий account JWT.

  python scripts/wb_push_rooms.py
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _deploy_common import CONTAINER, REMOTE, connect, run  # noqa: E402
from wb_hot_bootstrap import (  # noqa: E402
    STATE_DIR,
    UA,
    WB_STATE,
    _auth,
    _is_account,
    _push,
    _wait_account_token,
)

# комнаты из успешного UI create (последний прогон)
ANDROID_ROOM = "019fa3a0-3ff8-77fa-a5a5-2c87a48e34e0"
PC_ROOM = "019fa3a0-4ed6-7467-b45b-8b536cec1fec"


async def main() -> None:
    from playwright.async_api import async_playwright

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"rooms android={ANDROID_ROOM} pc={PC_ROOM}", flush=True)

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
        ctx = await browser.new_context(**kwargs)
        page = await ctx.new_page()
        await page.goto("https://stream.wb.ru/", wait_until="domcontentloaded", timeout=60_000)

        # уже залогинен — ждём ротацию ttl, не 10 минут логина
        token = ""
        for i in range(90):
            auth = await _auth(page)
            left = max(0, (auth["ttl"] - int(time.time() * 1000)) // 1000) if auth["ttl"] else 0
            if i % 5 == 0:
                print(
                    f"authType={auth['authType'] or '∅'} left≈{left}s",
                    flush=True,
                )
            if _is_account(auth, min_left_ms=20_000):
                token = auth["tok"]
                print(f"TOKEN OK left≈{left}s", flush=True)
                break
            await page.wait_for_timeout(1000)
        else:
            # fallback: полный wait (если сессия слетела)
            token = await _wait_account_token(page, timeout_s=180)

        await ctx.storage_state(path=str(WB_STATE))
        await browser.close()

    # push сразу после close — токен уже в файле/переменной
    _push(ANDROID_ROOM, PC_ROOM, token)
    print("OK", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    asyncio.run(main())
