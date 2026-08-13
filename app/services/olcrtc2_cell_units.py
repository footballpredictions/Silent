"""Apply / teardown per-session olcrtc2@unit on Hive cell via cell-agent."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hive_cell import HiveCell
from app.models.olcrtc2_room import Olcrtc2Room
from app.services.olcrtc2_settings import DEFAULT_CELL_IP, QUEEN_IP, cell_ip_for_provider, load_olcrtc2_settings

logger = logging.getLogger(__name__)

SETTLE_AFTER_APPLY_SEC = 8


async def _cell_secret(cell: HiveCell) -> str:
    if not cell.api_secret_enc:
        return ""
    try:
        from app.core.security import decrypt_value

        return decrypt_value(cell.api_secret_enc) or ""
    except Exception:
        return ""


async def _resolve_cell(
    db: AsyncSession,
    room: Olcrtc2Room | None = None,
    *,
    provider: str | None = None,
) -> HiveCell | None:
    cell = None
    if room and room.cell_id:
        cell = await db.get(HiveCell, room.cell_id)
    if not cell:
        prov = provider or (room.provider if room else None)
        cell = await resolve_olcrtc2_cell(db, provider=prov)
    return cell


async def resolve_olcrtc2_cell(
    db: AsyncSession,
    *,
    provider: str | None = None,
) -> HiveCell | None:
    settings = await load_olcrtc2_settings(db)
    cell_ip = cell_ip_for_provider(settings, provider)
    if cell_ip == QUEEN_IP:
        return None
    row = (
        await db.execute(select(HiveCell).where(HiveCell.public_ip == cell_ip))
    ).scalar_one_or_none()
    if row is None:
        logger.warning(
            "olcrtc2 cell %s (provider=%s) not in hive_cells",
            cell_ip,
            provider or settings.get("provider"),
        )
    return row


async def probe_olcrtc2_unit(db: AsyncSession, room: Olcrtc2Room) -> dict[str, Any]:
    """Check systemd unit is active on cell (needs cell-agent /v1/olcrtc2/status)."""
    cell = await _resolve_cell(db, room)
    if not cell or not cell.api_url:
        return {"ok": False, "active": False, "message": "cell missing"}
    if (cell.public_ip or "") == QUEEN_IP:
        return {"ok": False, "active": False, "message": "refuse queen"}
    secret = await _cell_secret(cell)
    if not secret:
        return {"ok": False, "active": False, "message": "secret missing"}
    if not room.unit_name:
        return {"ok": False, "active": False, "message": "no unit"}
    url = cell.api_url.rstrip("/") + "/v1/olcrtc2/status"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                json={"unit_name": room.unit_name},
                headers={"X-Cell-Agent-Secret": secret},
            )
        if resp.status_code == 404:
            # Старый cell-agent без /status — считаем unknown (не валим assign).
            return {"ok": True, "active": True, "unknown": True}
        if resp.status_code >= 400:
            return {"ok": False, "active": False, "message": (resp.text or "")[:200]}
        data = resp.json() if resp.content else {}
        return {
            "ok": True,
            "active": bool(data.get("active")),
            "has_env": bool(data.get("has_env")),
            "state": data.get("state"),
            **{k: v for k, v in data.items() if k not in ("ok", "active")},
        }
    except Exception as e:
        logger.warning("probe_olcrtc2_unit: %s", e)
        # Сеть к соте ≠ мёртвый unit — иначе warm heal рвёт живые комнаты.
        return {"ok": False, "active": False, "unknown": True, "message": str(e)[:160]}


async def apply_olcrtc2_unit(db: AsyncSession, room: Olcrtc2Room) -> dict[str, Any]:
    cell = await _resolve_cell(db, room)
    if not cell or not cell.api_url:
        return {"ok": False, "message": "olcrtc2 cell missing api_url"}
    if (cell.public_ip or "") == QUEEN_IP:
        return {"ok": False, "message": "refuse: olcrtc2 on queen"}
    secret = await _cell_secret(cell)
    if not secret:
        return {"ok": False, "message": "cell agent secret missing"}

    auth_token = (room.auth_token or "").strip()
    if (room.provider or "") == "wbstream":
        # Host JWT must be fresh — иначе guest: «гости не могут создать комнату»
        if not auth_token.startswith("eyJ"):
            try:
                from app.services.olcrtc_room_accounts import (
                    resolve_wbstream_access_token,
                    sync_wbstream_auth_token_to_settings,
                )

                auth_token = (
                    await sync_wbstream_auth_token_to_settings(db)
                    or await resolve_wbstream_access_token(db)
                    or ""
                ).strip()
            except Exception:
                logger.debug("wb token refresh for apply failed", exc_info=True)
            if auth_token.startswith("eyJ"):
                room.auth_token = auth_token
                await db.commit()
        if not auth_token.startswith("eyJ"):
            return {
                "ok": False,
                "message": "wbstream apply: no account JWT (auth.token) — sync WB cookies",
            }

    url = cell.api_url.rstrip("/") + "/v1/olcrtc2/apply"
    body = {
        "unit_name": room.unit_name,
        "room": room.room_url,
        "crypto_key": room.crypto_key,
        "provider": room.provider,
        "auth_token": auth_token if (room.provider or "") == "wbstream" else "",
        "restart": True,
    }
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                url, json=body, headers={"X-Cell-Agent-Secret": secret}
            )
        if resp.status_code >= 400:
            return {"ok": False, "message": (resp.text or "")[:300]}
        data = resp.json() if resp.content else {}
        return {"ok": True, "unit": room.unit_name, "cell": cell.public_ip, **data}
    except Exception as e:
        logger.exception("apply_olcrtc2_unit")
        return {"ok": False, "message": str(e)[:200]}


async def ensure_unit_ready(db: AsyncSession, room: Olcrtc2Room) -> bool:
    """Probe; if dead — re-apply + settle. False = комната непригодна."""
    probe = await probe_olcrtc2_unit(db, room)
    if probe.get("active") and probe.get("has_env", True):
        return True
    if probe.get("unknown"):
        return True
    logger.warning(
        "olcrtc2 unit not ready unit=%s state=%s — re-apply",
        room.unit_name,
        probe.get("state") or probe.get("message"),
    )
    applied = await apply_olcrtc2_unit(db, room)
    if not applied.get("ok"):
        logger.warning("olcrtc2 re-apply fail unit=%s: %s", room.unit_name, applied.get("message"))
        return False
    await asyncio.sleep(SETTLE_AFTER_APPLY_SEC)
    probe2 = await probe_olcrtc2_unit(db, room)
    if probe2.get("unknown"):
        return True
    ok = bool(probe2.get("active"))
    if not ok:
        logger.warning("olcrtc2 unit still dead after re-apply unit=%s", room.unit_name)
    return ok


async def teardown_olcrtc2_unit(db: AsyncSession, room: Olcrtc2Room) -> dict[str, Any]:
    cell = await _resolve_cell(db, room)
    if not cell or not cell.api_url:
        return {"ok": False, "message": "cell missing"}
    secret = await _cell_secret(cell)
    if not secret:
        return {"ok": False, "message": "cell secret missing"}
    url = cell.api_url.rstrip("/") + "/v1/olcrtc2/teardown"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                json={"unit_name": room.unit_name},
                headers={"X-Cell-Agent-Secret": secret},
            )
        if resp.status_code >= 400:
            return {"ok": False, "message": (resp.text or "")[:300]}
        return {"ok": True, "unit": room.unit_name}
    except Exception as e:
        return {"ok": False, "message": str(e)[:200]}
