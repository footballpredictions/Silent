"""Админка: сессии устройств пользователя (без WG-ключей)."""
from __future__ import annotations


def device_public_dict(device) -> dict:
    name = (getattr(device, "device_name", None) or "").strip()
    dtype = (getattr(device, "device_type", None) or "").strip() or "device"
    return {
        "id": str(device.id),
        "device_name": name or dtype,
        "device_type": dtype,
        "last_ip": getattr(device, "last_ip", None) or None,
        "last_connected": getattr(device, "last_connected", None),
        "created_at": getattr(device, "created_at", None),
        "is_connected": bool(getattr(device, "is_connected", False)),
        "preferred_server": getattr(device, "preferred_server", None) or "queen",
    }


BOOTSTRAP_EMAIL = "__bootstrap__@silent.local"


async def _get_user(db, user_id: str):
    from uuid import UUID

    from fastapi import HTTPException
    from sqlalchemy import select

    from app.models import User

    try:
        uid = UUID(str(user_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный id пользователя")
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user or user.email == BOOTSTRAP_EMAIL:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


async def list_user_devices(db, user_id: str) -> dict:
    from sqlalchemy import select

    from app.models import Device

    user = await _get_user(db, user_id)
    result = await db.execute(
        select(Device)
        .where(Device.user_id == user.id)
        .order_by(Device.last_connected.desc().nullslast(), Device.created_at.desc())
    )
    devices = list(result.scalars().all())
    return {
        "user": {
            "id": str(user.id),
            "display_id": user.display_id,
            "email": user.email,
        },
        "devices": [device_public_dict(d) for d in devices],
    }


async def delete_user_device(db, user_id: str, device_id: str) -> dict:
    from uuid import UUID

    from fastapi import HTTPException
    from sqlalchemy import select

    from app.models import Device

    user = await _get_user(db, user_id)
    try:
        did = UUID(str(device_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный id устройства")
    result = await db.execute(
        select(Device).where(Device.id == did, Device.user_id == user.id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Устройство не найдено")
    await db.delete(device)
    await db.commit()
    return {"ok": True, "deleted": 1}


async def delete_all_user_devices(db, user_id: str) -> dict:
    from sqlalchemy import select

    from app.models import Device

    user = await _get_user(db, user_id)
    result = await db.execute(select(Device).where(Device.user_id == user.id))
    devices = list(result.scalars().all())
    for device in devices:
        await db.delete(device)
    await db.commit()
    return {"ok": True, "deleted": len(devices)}
