"""Playwright-провижининг комнат WB Stream / Яндекс Телемост.

Требует установленный playwright + chromium:
  pip install playwright
  playwright install chromium

Без storage_state (логин) создание невозможно — olcrtc API CreateRoom не поддерживает
эти провайдеры. Аккаунты создаёшь вручную один раз; сюда кладётся cookies/session.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class ProvisionResult:
    ok: bool
    room_id: str = ""
    message: str = ""
    provider: str = ""


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def _extract_telemost_id(url: str) -> str:
    """https://telemost.yandex.ru/j/02789996238784 → 02789996238784"""
    u = (url or "").strip()
    if not u:
        return ""
    if re.fullmatch(r"\d{10,}", u):
        return u
    m = re.search(r"/j/(\d+)", u)
    if m:
        return m.group(1)
    path = urlparse(u).path.strip("/")
    parts = path.split("/")
    for p in reversed(parts):
        if re.fullmatch(r"\d{10,}", p):
            return p
    return u


def _extract_wb_id(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    # UUID-ish
    m = re.search(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        u,
        re.I,
    )
    if m:
        return m.group(1)
    if "/" not in u and len(u) > 8:
        return u
    path = urlparse(u).path.strip("/")
    return path.split("/")[-1] if path else u


async def create_telemost_room(storage_state: dict[str, Any], *, headless: bool = True) -> ProvisionResult:
    if not playwright_available():
        return ProvisionResult(
            ok=False,
            provider="telemost",
            message="playwright не установлен (pip install playwright && playwright install chromium)",
        )
    if not storage_state:
        return ProvisionResult(
            ok=False,
            provider="telemost",
            message="нет storage_state Яндекс-аккаунта — залогинься вручную и сохрани cookies",
        )
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return ProvisionResult(ok=False, provider="telemost", message="playwright import failed")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(storage_state=storage_state)
            page = await context.new_page()
            await page.goto("https://telemost.yandex.ru/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2000)
            created = False
            for sel in (
                '[data-testid="create-call-button"]',
                'button:has-text("Создать видеовстречу")',
                'button:has-text("Создать встречу")',
                'button:has-text("Новая встреча")',
                'a:has-text("Создать встречу")',
                '[data-testid="create-meeting"]',
                'button:has-text("Create")',
            ):
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.click(timeout=8000)
                        created = True
                        break
                except Exception:
                    continue
            if not created:
                try:
                    await page.get_by_text("Создать видеовстречу", exact=False).first.click(timeout=5000)
                    created = True
                except Exception:
                    pass
            if not created:
                await browser.close()
                return ProvisionResult(
                    ok=False,
                    provider="telemost",
                    message="не найдена кнопка создания встречи (UI Яндекса изменился или нет логина)",
                )
            # ждём редирект на /j/<id>
            room_id = ""
            url = page.url
            for _ in range(20):
                await page.wait_for_timeout(500)
                url = page.url
                room_id = _extract_telemost_id(url)
                if room_id and re.fullmatch(r"\d{8,}", room_id):
                    break
            if not room_id or not re.fullmatch(r"\d{8,}", room_id):
                for sel in (
                    'input[readonly]',
                    'input[value*="/j/"]',
                    '[data-testid="meeting-link"]',
                    'input[type="text"]',
                ):
                    try:
                        val = await page.locator(sel).first.input_value(timeout=2000)
                        room_id = _extract_telemost_id(val) or room_id
                        if room_id and re.fullmatch(r"\d{8,}", room_id):
                            break
                    except Exception:
                        continue
            await browser.close()
            if not room_id or not re.search(r"\d{8,}", room_id):
                return ProvisionResult(
                    ok=False,
                    provider="telemost",
                    message=f"комната создана?, но room id не извлечён (url={url})",
                )
            return ProvisionResult(ok=True, provider="telemost", room_id=room_id, message="ok")
    except Exception as e:
        logger.exception("telemost provision failed")
        return ProvisionResult(ok=False, provider="telemost", message=str(e)[:300])


async def create_wbstream_room(storage_state: dict[str, Any], *, headless: bool = True) -> ProvisionResult:
    if not playwright_available():
        return ProvisionResult(
            ok=False,
            provider="wbstream",
            message="playwright не установлен",
        )
    if not storage_state:
        return ProvisionResult(
            ok=False,
            provider="wbstream",
            message="нет storage_state WB-аккаунта",
        )
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return ProvisionResult(ok=False, provider="wbstream", message="playwright import failed")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(storage_state=storage_state)
            page = await context.new_page()
            for start in (
                "https://stream.wb.ru/",
                "https://stream-meetup.wildberries.ru/",
            ):
                try:
                    await page.goto(start, wait_until="domcontentloaded", timeout=45000)
                    break
                except Exception:
                    continue
            await page.wait_for_timeout(2500)
            created = False
            for sel in (
                'button:has-text("Новая видеовстреча")',
                'text=Новая видеовстреча',
                'button:has-text("Создать")',
                'button:has-text("Новая комната")',
                'button:has-text("Create")',
                'a:has-text("Создать")',
            ):
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.click(timeout=8000)
                        created = True
                        break
                except Exception:
                    continue
            if not created:
                for label in ("Новая видеовстреча", "Новая встреча", "Создать встречу"):
                    try:
                        await page.get_by_text(label, exact=False).first.click(timeout=5000)
                        created = True
                        break
                    except Exception:
                        continue
            if not created:
                await browser.close()
                return ProvisionResult(
                    ok=False,
                    provider="wbstream",
                    message="не найдена кнопка создания комнаты WB (нужен логин / UI изменился)",
                )
            room_id = ""
            url = page.url
            for _ in range(24):
                await page.wait_for_timeout(500)
                url = page.url
                room_id = _extract_wb_id(url)
                if room_id and re.search(
                    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                    room_id,
                    re.I,
                ):
                    break
            await browser.close()
            if not room_id or "REPLACE" in room_id.upper():
                return ProvisionResult(
                    ok=False,
                    provider="wbstream",
                    message=f"room id не извлечён (url={url})",
                )
            return ProvisionResult(ok=True, provider="wbstream", room_id=room_id, message="ok")
    except Exception as e:
        logger.exception("wbstream provision failed")
        return ProvisionResult(ok=False, provider="wbstream", message=str(e)[:300])


async def create_room(
    provider: str,
    storage_state: dict[str, Any],
    *,
    headless: bool = True,
) -> ProvisionResult:
    if provider == "telemost":
        return await create_telemost_room(storage_state, headless=headless)
    if provider == "wbstream":
        return await create_wbstream_room(storage_state, headless=headless)
    return ProvisionResult(ok=False, provider=provider, message=f"unsupported provider: {provider}")
