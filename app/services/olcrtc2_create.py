"""Create Telemost/WB rooms for olcrtc2 — never Playwright on WDTT queen.

Telemost: POST to cell provision :9101 (Playwright on cell) or cell-agent /v1/olcrtc2/create.
WB: HTTP API from queen (no browser).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ai.olcrtc_room_provision import ProvisionResult
from app.services.olcrtc2_settings import (
    QUEEN_IP,
    cell_ip_for_provider,
    cell_provision_url_for_provider,
    load_olcrtc2_settings,
)

logger = logging.getLogger(__name__)


def _auth_headers() -> dict[str, str]:
    import os

    secret = (os.environ.get("INTERNAL_API_SECRET") or "").strip()
    if not secret:
        return {}
    return {"X-Internal-Secret": secret}


async def create_olcrtc2_room(
    db: AsyncSession,
    *,
    provider: str,
    storage_state: dict[str, Any] | None = None,
    access_token: str = "",
) -> ProvisionResult:
    prov = (provider or "telemost").strip().lower()
    if prov == "wbstream":
        return await _create_wb(db, access_token=access_token, storage_state=storage_state)
    return await _create_telemost_on_cell(db, storage_state=storage_state)


async def _create_wb(
    db: AsyncSession,
    *,
    access_token: str,
    storage_state: dict[str, Any] | None,
) -> ProvisionResult:
    tok = (access_token or "").strip()
    if not tok.startswith("eyJ") and storage_state:
        try:
            from app.services.olcrtc_room_accounts import resolve_wbstream_access_token

            tok = await resolve_wbstream_access_token(db) or tok
        except Exception:
            pass
    if not tok.startswith("eyJ"):
        return ProvisionResult(ok=False, provider="wbstream", message="wb: no access_token")
    from ai.olcrtc_wb_api import create_wbstream_room_api

    return await create_wbstream_room_api(tok)


async def _create_telemost_on_cell(
    db: AsyncSession,
    *,
    storage_state: dict[str, Any] | None,
) -> ProvisionResult:
    settings = await load_olcrtc2_settings(db)
    base = cell_provision_url_for_provider(settings, "telemost").rstrip("/")
    cell_ip = cell_ip_for_provider(settings, "telemost")
    if not base or QUEEN_IP in base:
        return ProvisionResult(
            ok=False,
            provider="telemost",
            message="telemost create: cell_provision_url must be on cell (not queen)",
        )

    # 1) cell host-provision :9101 (Playwright on cell)
    if storage_state:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(
                    f"{base}/v1/create",
                    json={"provider": "telemost", "storage_state": storage_state, "headless": True},
                    headers=_auth_headers(),
                )
            if r.status_code == 200:
                data = r.json() if r.content else {}
                room_id = str(data.get("room_id") or data.get("room") or "").strip()
                if data.get("ok") and room_id:
                    return ProvisionResult(
                        ok=True, provider="telemost", room_id=room_id, message=data.get("message") or "ok"
                    )
                msg = str(data.get("message") or data.get("detail") or r.text or "")[:200]
                logger.warning("cell provision create: %s", msg)
            else:
                logger.warning("cell provision HTTP %s: %s", r.status_code, (r.text or "")[:160])
        except Exception as e:
            logger.warning("cell provision unreachable %s: %s", cell_ip, e)

    # 2) cell-agent /v1/olcrtc2/create
    try:
        from app.services.olcrtc2_cell_units import resolve_olcrtc2_cell, _cell_secret

        cell = await resolve_olcrtc2_cell(db, provider="telemost")
        if cell and cell.api_url:
            secret = await _cell_secret(cell)
            if secret:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    r = await client.post(
                        cell.api_url.rstrip("/") + "/v1/olcrtc2/create",
                        json={
                            "provider": "telemost",
                            "storage_state": storage_state or {},
                        },
                        headers={"X-Cell-Agent-Secret": secret},
                    )
                if r.status_code == 200:
                    data = r.json() if r.content else {}
                    room_id = str(data.get("room_id") or data.get("room") or "").strip()
                    if data.get("ok") and room_id:
                        return ProvisionResult(
                            ok=True,
                            provider="telemost",
                            room_id=room_id,
                            message=data.get("message") or "cell-agent create",
                        )
                    return ProvisionResult(
                        ok=False,
                        provider="telemost",
                        message=str(data.get("message") or data.get("detail") or "create failed")[:200],
                    )
                return ProvisionResult(
                    ok=False,
                    provider="telemost",
                    message=f"cell-agent create HTTP {r.status_code}: {(r.text or '')[:160]}",
                )
    except Exception as e:
        logger.exception("olcrtc2 telemost create")
        return ProvisionResult(ok=False, provider="telemost", message=str(e)[:200])

    return ProvisionResult(
        ok=False,
        provider="telemost",
        message=(
            "Нет create на соте: поднимите silent-olcrtc-host-provision на cell:9101 "
            "или cell-agent /v1/olcrtc2/create (Playwright). На Улей не ставить."
        ),
    )
