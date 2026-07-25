"""CRUD / sync / yaml для OlcrtcRoom (пул 1000+)."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.olcrtc_room import OlcrtcRoom
from app.services.olcrtc_settings import (
    DEFAULT_TRANSPORTS,
    OlcrtcSettings,
    PROVIDERS,
    is_placeholder_room,
    load_olcrtc_settings,
    normalize_room_id,
    write_server_yaml_file,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def room_to_dict(r: OlcrtcRoom) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "provider": r.provider,
        "room_url": r.room_url,
        "slot_label": r.slot_label,
        "device_types": list(r.device_types or []),
        "cell_id": str(r.cell_id) if r.cell_id else None,
        "unit_name": r.unit_name,
        "data_dir": r.data_dir,
        "status": r.status,
        "max_clients": r.max_clients,
        "online_count": r.online_count,
        "last_healthy_at": r.last_healthy_at.isoformat() if r.last_healthy_at else None,
        "last_error": r.last_error or "",
        "headroom": max(0, int(r.max_clients) - int(r.online_count or 0)),
    }


def _slug_unit(slot: str, provider: str, suffix: str = "") -> str:
    base = f"{slot}-{provider}"
    if suffix:
        base = f"{base}-{suffix}"
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", base).strip("-")[:120]


async def list_rooms(
    db: AsyncSession,
    *,
    provider: str | None = None,
    status: str | None = None,
) -> list[OlcrtcRoom]:
    q = select(OlcrtcRoom).order_by(OlcrtcRoom.provider, OlcrtcRoom.slot_label, OlcrtcRoom.unit_name)
    if provider:
        q = q.where(OlcrtcRoom.provider == provider)
    if status:
        q = q.where(OlcrtcRoom.status == status)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_room(db: AsyncSession, room_id: uuid.UUID) -> OlcrtcRoom | None:
    return await db.get(OlcrtcRoom, room_id)


async def sync_rooms_from_settings_json(db: AsyncSession, settings: OlcrtcSettings | None = None) -> int:
    """Одноразовая/идемпотентная миграция JSON rooms[] → olcrtc_rooms."""
    settings = settings or await load_olcrtc_settings(db)
    existing = await list_rooms(db)
    by_key = {(r.provider, r.room_url.strip()): r for r in existing}
    by_unit = {r.unit_name: r for r in existing}
    created = 0
    for name in PROVIDERS:
        p = settings.providers.get(name)
        if not p:
            continue
        for slot in p.effective_rooms():
            url = normalize_room_id(name, slot.url)
            if is_placeholder_room(url) or not url:
                continue
            key = (name, url)
            if key in by_key:
                continue
            unit = _slug_unit(slot.id or "r", name)
            n = 2
            while unit in by_unit:
                unit = _slug_unit(slot.id or "r", name, str(n))
                n += 1
            dts = list(slot.device_types) or ([slot.id] if slot.id in ("pc", "android") else [])
            row = OlcrtcRoom(
                provider=name,
                room_url=url,
                slot_label=(slot.id or "pc").strip() or "pc",
                device_types=dts,
                cell_id=None,
                unit_name=unit,
                data_dir=f"data-{unit}",
                status="active" if p.enabled else "offline",
                max_clients=max(1, int(slot.max_clients or 12)),
                online_count=0,
                last_healthy_at=_now(),
            )
            db.add(row)
            by_key[key] = row
            by_unit[unit] = row
            created += 1
    if created:
        await db.commit()
    return created


async def ensure_rooms_synced(db: AsyncSession) -> None:
    n = await db.scalar(select(func.count()).select_from(OlcrtcRoom))
    if not n:
        await sync_rooms_from_settings_json(db)


async def set_room_status(
    db: AsyncSession,
    room_id: uuid.UUID,
    status: str,
    *,
    error: str | None = None,
) -> OlcrtcRoom | None:
    room = await get_room(db, room_id)
    if not room:
        return None
    room.status = status
    if error is not None:
        room.last_error = error[:500]
    if status == "active":
        room.last_healthy_at = _now()
        room.last_error = None
    await db.commit()
    await db.refresh(room)
    return room


async def create_room_row(
    db: AsyncSession,
    *,
    provider: str,
    room_url: str,
    slot_label: str = "pc",
    device_types: list[str] | None = None,
    max_clients: int = 12,
    cell_id: uuid.UUID | None = None,
    status: str = "active",
) -> OlcrtcRoom:
    url = normalize_room_id(provider, room_url)
    if not url or is_placeholder_room(url):
        raise ValueError("invalid room_url")
    existing = await list_rooms(db)
    by_unit = {r.unit_name for r in existing}
    unit = _slug_unit(slot_label, provider)
    n = 2
    while unit in by_unit:
        unit = _slug_unit(slot_label, provider, str(n))
        n += 1
    dts = device_types or [slot_label]
    row = OlcrtcRoom(
        provider=provider,
        room_url=url,
        slot_label=slot_label,
        device_types=dts,
        cell_id=cell_id,
        unit_name=unit,
        data_dir=f"data-{unit}",
        status=status,
        max_clients=max(1, max_clients),
        online_count=0,
        last_healthy_at=_now(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def render_unit_yaml(settings: OlcrtcSettings, room: OlcrtcRoom) -> str:
    if not settings.crypto_key or len(settings.crypto_key) != 64:
        raise ValueError("crypto_key must be 64 hex characters")
    transport = (
        settings.providers.get(room.provider).transport
        if settings.providers.get(room.provider)
        else DEFAULT_TRANSPORTS.get(room.provider, "datachannel")
    )
    return "\n".join(
        [
            "mode: srv",
            "crypto:",
            f'  key: "{settings.crypto_key}"',
            "net:",
            '  dns: "8.8.8.8:53"',
            f"data: {room.data_dir}",
            "profiles:",
            f"  - name: {room.unit_name}",
            "    auth:",
            f"      provider: {room.provider}",
            "    room:",
            f'      id: "{room.room_url}"',
            "    net:",
            f"      transport: {transport}",
            '      dns: "8.8.8.8:53"',
            "failover:",
            "  retry_delay: 2s",
            "  max_cycles: 0",
            "",
        ]
    )


async def write_all_unit_yaml_from_db(db: AsyncSession) -> dict[str, str]:
    """unit_name → yaml path content. Только active/provisioning."""
    settings = await load_olcrtc_settings(db)
    await ensure_rooms_synced(db)
    rooms = await list_rooms(db)
    out: dict[str, str] = {}
    for r in rooms:
        if r.status not in ("active", "provisioning"):
            continue
        if is_placeholder_room(r.room_url):
            continue
        text = render_unit_yaml(settings, r)
        out[r.unit_name] = text
        write_server_yaml_file(text, filename=f"server-{r.unit_name}.yaml")
    # legacy aliases
    for prefer in ("pc-jitsi", "pc-telemost", "android-jitsi", "android-telemost"):
        if prefer in out:
            if prefer.startswith("pc-"):
                write_server_yaml_file(out[prefer], filename="server-pc.yaml")
                write_server_yaml_file(out[prefer], filename="server.yaml")
            if prefer.startswith("android-"):
                write_server_yaml_file(out[prefer], filename="server-android.yaml")
            break
    return out


async def pool_metrics(db: AsyncSession) -> dict[str, Any]:
    rooms = await list_rooms(db)
    active = [r for r in rooms if r.status == "active"]
    draining = [r for r in rooms if r.status == "draining"]
    online = sum(int(r.online_count or 0) for r in rooms)
    capacity = sum(int(r.max_clients or 0) for r in active)
    free = sum(max(0, int(r.max_clients) - int(r.online_count or 0)) for r in active)
    by_provider: dict[str, Any] = {}
    for name in PROVIDERS:
        pr = [r for r in active if r.provider == name]
        by_provider[name] = {
            "rooms": len(pr),
            "online": sum(int(r.online_count or 0) for r in pr),
            "capacity": sum(int(r.max_clients or 0) for r in pr),
            "free": sum(max(0, int(r.max_clients) - int(r.online_count or 0)) for r in pr),
        }
    return {
        "rooms_total": len(rooms),
        "rooms_active": len(active),
        "rooms_draining": len(draining),
        "online_total": online,
        "capacity_total": capacity,
        "free_slots": free,
        "fill_ratio": round(online / capacity, 3) if capacity else 0.0,
        "target_free_ratio": 0.10,
        "target_capacity_hint": 1100,
        "by_provider": by_provider,
        "denied_hint": free <= 0,
        "ready_for_1000": capacity >= 1100,
    }
