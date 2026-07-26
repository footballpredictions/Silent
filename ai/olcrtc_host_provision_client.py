"""Клиент host-side Playwright provision (Chromium на Улье, не в Docker API).

Сервис: systemd ``silent-olcrtc-host-provision`` → ``:9101`` (UFW docker-only).
Auth: ``X-Internal-Secret: INTERNAL_API_SECRET``.
Из контейнера: ``host.docker.internal`` или ``172.17.0.1``.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ai.olcrtc_room_provision import ProvisionResult, playwright_available

logger = logging.getLogger(__name__)

DEFAULT_URLS = (
    os.environ.get("OLCRTC_HOST_PROVISION_URL", "").strip(),
    "http://host.docker.internal:9101",
    "http://172.18.0.1:9101",  # docker compose bridge
    "http://172.17.0.1:9101",  # docker0
    "http://127.0.0.1:9101",
)


def _candidate_urls() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in DEFAULT_URLS:
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u.rstrip("/"))
    return out


def _auth_headers() -> dict[str, str]:
    secret = (os.environ.get("INTERNAL_API_SECRET") or "").strip()
    if not secret:
        return {}
    return {"X-Internal-Secret": secret}


async def host_provision_status() -> dict[str, Any]:
    """Статус host-сервиса (для админки)."""
    last_err = ""
    headers = _auth_headers()
    for base in _candidate_urls():
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(f"{base}/v1/status", headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    data["url"] = base
                    data["reachable"] = True
                    return data
                last_err = f"{base} HTTP {r.status_code}"
        except Exception as e:
            last_err = f"{base}: {e}"
    return {
        "reachable": False,
        "playwright": False,
        "telemost_state": False,
        "wbstream_state": False,
        "error": last_err or "unreachable",
        "in_container_playwright": playwright_available(),
    }


async def create_room_via_host(
    provider: str,
    storage_state: dict[str, Any] | None = None,
    *,
    headless: bool = True,
) -> ProvisionResult:
    """Создать комнату на host-сервисе. storage_state опционален — host может взять файл."""
    body: dict[str, Any] = {"provider": provider, "headless": headless}
    if storage_state:
        body["storage_state"] = storage_state
    last_err = ""
    headers = _auth_headers()
    for base in _candidate_urls():
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(f"{base}/v1/create", json=body, headers=headers)
                data = r.json() if r.content else {}
                if r.status_code == 200 and data.get("ok") and data.get("room_id"):
                    return ProvisionResult(
                        ok=True,
                        provider=provider,
                        room_id=str(data["room_id"]),
                        message=f"host:{base}",
                    )
                last_err = str(data.get("message") or data.get("detail") or f"HTTP {r.status_code}")
        except Exception as e:
            last_err = str(e)[:200]
            logger.debug("host provision %s failed: %s", base, e)
    return ProvisionResult(
        ok=False,
        provider=provider,
        message=last_err or "host provision unreachable",
    )


async def push_storage_to_host(provider: str, storage_state: dict[str, Any]) -> bool:
    if not storage_state:
        return False
    headers = _auth_headers()
    for base in _candidate_urls():
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{base}/v1/storage",
                    json={"provider": provider, "storage_state": storage_state},
                    headers=headers,
                )
                if r.status_code == 200:
                    return True
        except Exception:
            continue
    return False


async def create_room_best(
    provider: str,
    storage_state: dict[str, Any] | None,
    *,
    headless: bool = True,
) -> ProvisionResult:
    """Host Playwright (предпочтительно) → fallback in-container."""
    host = await create_room_via_host(provider, storage_state, headless=headless)
    if host.ok:
        return host
    if playwright_available() and storage_state:
        from ai.olcrtc_room_provision import create_room

        local = await create_room(provider, storage_state, headless=headless)
        if local.ok:
            return local
        return ProvisionResult(
            ok=False,
            provider=provider,
            message=f"host: {host.message}; local: {local.message}",
        )
    return ProvisionResult(
        ok=False,
        provider=provider,
        message=host.message
        or "нет host-provision и нет playwright в контейнере — задеплой silent-olcrtc-host-provision",
    )
