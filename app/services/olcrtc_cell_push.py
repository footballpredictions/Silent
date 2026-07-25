"""Пуш yaml комнат на соты через cell-agent /v1/olcrtc/apply."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hive_cell import HiveCell
from app.services.olcrtc_rooms_db import list_rooms, render_unit_yaml
from app.services.olcrtc_settings import load_olcrtc_settings
from app.services.hive_service import ensure_queen_cell

logger = logging.getLogger(__name__)


async def _cell_secret(cell: HiveCell) -> str:
    if not cell.api_secret_enc:
        return ""
    try:
        from app.core.security import decrypt_value

        return decrypt_value(cell.api_secret_enc) or ""
    except Exception:
        return ""


async def push_room_to_cell(db: AsyncSession, room_id) -> dict[str, Any]:
    from uuid import UUID

    from app.models.olcrtc_room import OlcrtcRoom

    if isinstance(room_id, str):
        room_id = UUID(room_id)
    room = await db.get(OlcrtcRoom, room_id)
    if not room:
        return {"ok": False, "detail": "room not found"}
    if not room.cell_id:
        return {"ok": True, "detail": "queen room — use apply_olcrtc_units_from_db on hive"}
    cell = await db.get(HiveCell, room.cell_id)
    if not cell or not cell.api_url:
        return {"ok": False, "detail": "cell has no api_url"}
    secret = await _cell_secret(cell)
    if not secret:
        return {"ok": False, "detail": "cell secret missing"}
    settings = await load_olcrtc_settings(db)
    yaml_text = render_unit_yaml(settings, room)
    url = cell.api_url.rstrip("/") + "/v1/olcrtc/apply"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                json={
                    "unit_name": room.unit_name,
                    "yaml_text": yaml_text,
                    "restart": True,
                },
                headers={"X-Cell-Agent-Secret": secret},
            )
        if resp.status_code >= 400:
            room.last_error = (resp.text or "")[:300]
            room.status = "error"
            await db.commit()
            return {"ok": False, "detail": resp.text[:300]}
        room.status = "active"
        room.last_error = None
        await db.commit()
        return {"ok": True, "unit": room.unit_name, "cell": str(cell.id)}
    except Exception as e:
        logger.exception("push olcrtc to cell failed")
        room.last_error = str(e)[:300]
        room.status = "error"
        await db.commit()
        return {"ok": False, "detail": str(e)[:300]}


async def push_all_cell_rooms(db: AsyncSession) -> dict[str, Any]:
    queen = await ensure_queen_cell(db)
    rooms = await list_rooms(db)
    results = []
    for r in rooms:
        if r.status not in ("active", "provisioning"):
            continue
        if r.cell_id is None or r.cell_id == queen.id:
            continue
        results.append(await push_room_to_cell(db, r.id))
    return {"ok": True, "pushed": len(results), "results": results}
