"""Playwright-провижининг комнат WB Stream / Яндекс Телемост.

Требует установленный playwright + chromium:
  pip install playwright
  playwright install chromium

Без storage_state (логин) создание невозможно — olcrtc API CreateRoom не поддерживает
эти провайдеры. Аккаунты создаёшь вручную один раз; сюда кладётся cookies/session.

WB (stream.wb.ru) с IP Улья часто отдаёт HTTP 498 + ``/__wbaas/challenges`` (antibot).
Тогда нужен свежий storage_state после ручного логина или egress-прокси
``OLCRTC_WB_PLAYWRIGHT_PROXY`` / ``OLCRTC_PLAYWRIGHT_PROXY``.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


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


def _playwright_proxy(provider: str) -> dict[str, str] | None:
    """Опциональный HTTP(S) proxy для Chromium (residential / RU egress).

    Для WB с IP Улья часто 498 antibot — берём OLCRTC_WB_PLAYWRIGHT_PROXY
    или собираем из PROXY_HTTP_* (тот же primary proxy, что для сайтов).
    """
    raw = (
        os.environ.get(f"OLCRTC_{provider.upper()}_PLAYWRIGHT_PROXY")
        or os.environ.get("OLCRTC_PLAYWRIGHT_PROXY")
        or ""
    ).strip()
    if not raw and provider == "wbstream":
        host = (
            os.environ.get("PROXY_HTTP_HOST")
            or os.environ.get("PROXY_PRIMARY_IP")
            or ""
        ).strip()
        user = (os.environ.get("PROXY_HTTP_USER") or "").strip()
        password = (os.environ.get("PROXY_HTTP_PASS") or "").strip()
        port = (os.environ.get("PROXY_HTTP_PORT") or "3128").strip() or "3128"
        if host and user and password:
            from urllib.parse import quote

            raw = (
                f"http://{quote(user, safe='')}:{quote(password, safe='')}"
                f"@{host}:{port}"
            )
    if not raw:
        return None
    return {"server": raw}


def _launch_args() -> list[str]:
    return [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ]


async def _page_looks_like_wb_antibot(page: Any) -> bool:
    try:
        url = (page.url or "").lower()
        if "__wbaas" in url or "challenge" in url:
            return True
        html = (await page.content())[:4000].lower()
        if "__wbaas/challenges" in html:
            return True
        if "wbaas" in html and "challenge" in html:
            return True
        return False
    except Exception:
        return False


async def _wait_out_wb_antibot(page: Any, *, max_ms: int = 25_000) -> bool:
    """Ждём, пока challenge исчезнет (иногда JS challenge проходит сам)."""
    elapsed = 0
    step = 1500
    while elapsed < max_ms:
        if not await _page_looks_like_wb_antibot(page):
            # UI встреч обычно появляется после challenge.
            try:
                if await page.locator('button:has-text("Новая"), button:has-text("Создать")').count() > 0:
                    return True
            except Exception:
                pass
            # Не antibot и не пустая заглушка — считаем ок.
            try:
                body = (await page.inner_text("body")).strip()
                if len(body) > 40 and "challenge" not in body.lower():
                    return True
            except Exception:
                return True
        await page.wait_for_timeout(step)
        elapsed += step
    return not await _page_looks_like_wb_antibot(page)


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
            launch_kwargs: dict[str, Any] = {
                "headless": headless,
                "args": _launch_args(),
            }
            proxy = _playwright_proxy("telemost")
            if proxy:
                launch_kwargs["proxy"] = proxy
            browser = await p.chromium.launch(**launch_kwargs)
            try:
                context = await browser.new_context(
                    storage_state=storage_state,
                    user_agent=_CHROME_UA,
                    locale="ru-RU",
                    viewport={"width": 1280, "height": 800},
                )
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
                if not room_id or not re.search(r"\d{8,}", room_id):
                    return ProvisionResult(
                        ok=False,
                        provider="telemost",
                        message=f"комната создана?, но room id не извлечён (url={url})",
                    )
                return ProvisionResult(ok=True, provider="telemost", room_id=room_id, message="ok")
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
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
            launch_kwargs: dict[str, Any] = {
                "headless": headless,
                "args": _launch_args(),
            }
            proxy = _playwright_proxy("wbstream")
            if proxy:
                launch_kwargs["proxy"] = proxy
            browser = await p.chromium.launch(**launch_kwargs)
            try:
                context = await browser.new_context(
                    storage_state=storage_state,
                    user_agent=_CHROME_UA,
                    locale="ru-RU",
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()
                nav_errors: list[str] = []
                opened = False
                # stream-meetup.wildberries.ru с Улья часто NXDOMAIN — только stream.wb.ru.
                for start in ("https://stream.wb.ru/",):
                    try:
                        resp = await page.goto(start, wait_until="domcontentloaded", timeout=45000)
                        status = resp.status if resp is not None else 0
                        if status == 498 or await _page_looks_like_wb_antibot(page):
                            # Даём challenge шанс пройти (JS), иначе явная ошибка.
                            ok_challenge = await _wait_out_wb_antibot(page)
                            if not ok_challenge or await _page_looks_like_wb_antibot(page):
                                return ProvisionResult(
                                    ok=False,
                                    provider="wbstream",
                                    message=(
                                        "WB antibot (HTTP 498 / __wbaas/challenges) блокирует IP Улья. "
                                        "Обновите storage_state после ручного логина в обычном браузере "
                                        "или задайте OLCRTC_WB_PLAYWRIGHT_PROXY (residential/RU egress)."
                                    ),
                                )
                        opened = True
                        break
                    except Exception as e:
                        nav_errors.append(f"{start}: {e}")
                        continue
                if not opened:
                    detail = "; ".join(nav_errors)[:220] or "navigation failed"
                    return ProvisionResult(
                        ok=False,
                        provider="wbstream",
                        message=f"не открылся stream.wb.ru ({detail})",
                    )
                await page.wait_for_timeout(2000)
                if await _page_looks_like_wb_antibot(page):
                    return ProvisionResult(
                        ok=False,
                        provider="wbstream",
                        message=(
                            "WB antibot challenge не пройден — Playwright видит только "
                            "__wbaas/challenges, кнопки создания нет"
                        ),
                    )
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
                    return ProvisionResult(
                        ok=False,
                        provider="wbstream",
                        message=(
                            "не найдена кнопка создания комнаты WB "
                            "(логин протух / UI изменился / antibot). "
                            "Пересохраните storage_state в админке."
                        ),
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
                if not room_id or "REPLACE" in room_id.upper():
                    return ProvisionResult(
                        ok=False,
                        provider="wbstream",
                        message=f"room id не извлечён (url={url})",
                    )
                return ProvisionResult(ok=True, provider="wbstream", room_id=room_id, message="ok")
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
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
