"""Адреса cell-agent для SMTP-релея, когда Улей не достучится до smtp.mail.ru."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


def smtp_relay_candidate_urls(*urls: str) -> list[str]:
    """Куда Улей шлёт POST /v1/smtp-send. Тот же публичный :9100, что bootstrap.

    10.x/localhost с Улья до чужой соты не маршрутизируются — в список не берём.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in urls:
        clean = (raw or "").strip().rstrip("/")
        if not clean:
            continue
        host = (urlsplit(clean if "://" in clean else f"http://{clean}").hostname or "").lower()
        if not host or host == "localhost" or host.startswith(("10.", "127.")):
            continue
        if clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


async def smtp_relays_from_db(db) -> list[dict[str, str]]:
    """Живые worker-соты, порядок как у bootstrap (Сота 1 первая)."""
    from app.core.security import decrypt_value
    from app.services.hive_standby import cell_public_api_base, get_standby_cells

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for cell in await get_standby_cells(db):
        if getattr(cell, "ai_exit", False):
            continue
        try:
            secret = decrypt_value(cell.api_secret_enc or "")
        except Exception:
            continue
        if len(secret or "") < 8:
            continue
        for url in smtp_relay_candidate_urls(
            cell_public_api_base(cell),
            (cell.api_url or "").strip(),
        ):
            if url in seen:
                continue
            seen.add(url)
            out.append({"api_url": url, "secret": secret})
    return out


async def _smtp_relays_async() -> list[dict[str, str]]:
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return await smtp_relays_from_db(db)


def load_smtp_relays_blocking() -> list[dict[str, str]]:
    """Для sync `_send` (BackgroundTasks / MFA). Секреты в лог не пишем."""

    def _run() -> list[dict[str, str]]:
        return asyncio.run(_smtp_relays_async())

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return _run()
        except Exception as e:
            logger.warning("email relays: %s", e)
            return []
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run).result(timeout=8)
    except Exception as e:
        logger.warning("email relays (loop): %s", e)
        return []
