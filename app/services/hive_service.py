"""Улей — управление VPN-сотами и балансировка нагрузки."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import secrets
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
import uuid

import httpx
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import encrypt_value, decrypt_value
from app.models import Device, HiveCell, User
from app.services.hive_capacity import get_capacity_profile, max_online_for_cell
from app.services.hive_load import queen_accepting_new_vpn

logger = logging.getLogger(__name__)

CELL_STATUSES_ACTIVE = frozenset({"active"})
CELL_STATUSES_ASSIGNABLE = frozenset({"active"})
BOOTSTRAP_USER_EMAIL = "__bootstrap__@silent.local"


def _validate_outbound_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("api_url: только http или https")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("api_url: не указан хост")
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise ValueError("api_url: localhost запрещён")
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise ValueError("api_url: приватные адреса запрещены")
    except ValueError as e:
        if "does not appear to be an IPv4 or IPv6 address" not in str(e):
            raise
    return url.strip().rstrip("/")


async def ensure_queen_cell(db: AsyncSession) -> HiveCell:
    result = await db.execute(select(HiveCell).where(HiveCell.is_queen == True))  # noqa: E712
    queen = result.scalar_one_or_none()
    pub_ip = (settings.VPN_SERVER_IP or "").strip()
    wg_key = (settings.WG_SERVER_PUBLIC_KEY or "").strip()

    if queen is None:
        if not pub_ip:
            logger.warning("Hive: VPN_SERVER_IP не задан — сота-Улей не создана")
            raise RuntimeError("VPN_SERVER_IP required for queen cell")
        queen = HiveCell(
            name="Улей",
            is_queen=True,
            public_ip=pub_ip,
            wdtt_port=settings.VPN_SERVER_PORT,
            wg_port=settings.WG_PORT,
            wg_public_key=wg_key,
            max_clients=0,
            status="active",
            priority=0,
            last_seen_at=datetime.utcnow(),
        )
        db.add(queen)
        await db.commit()
        await db.refresh(queen)
        return queen

    changed = False
    if pub_ip and queen.public_ip != pub_ip:
        queen.public_ip = pub_ip
        changed = True
    if wg_key and queen.wg_public_key != wg_key:
        queen.wg_public_key = wg_key
        changed = True
    if queen.wdtt_port != settings.VPN_SERVER_PORT:
        queen.wdtt_port = settings.VPN_SERVER_PORT
        changed = True
    if queen.status != "active":
        queen.status = "active"
        changed = True
    if changed:
        queen.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(queen)
    return queen


async def get_queen_cell(db: AsyncSession) -> Optional[HiveCell]:
    result = await db.execute(select(HiveCell).where(HiveCell.is_queen == True))  # noqa: E712
    return result.scalar_one_or_none()


async def get_cell_by_id(db: AsyncSession, cell_id: uuid.UUID) -> Optional[HiveCell]:
    result = await db.execute(select(HiveCell).where(HiveCell.id == cell_id))
    return result.scalar_one_or_none()


async def count_online_on_cell(db: AsyncSession, cell_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(Device.id)).where(
            Device.cell_id == cell_id,
            Device.is_active == True,
            Device.is_connected == True,
        )
    )
    return int(result.scalar_one())


async def count_assigned_on_cell(db: AsyncSession, cell_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(Device.id)).where(
            Device.cell_id == cell_id,
            Device.is_active == True,
        )
    )
    return int(result.scalar_one())


async def count_rebalance_candidates_on_cell(db: AsyncSession, cell_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(Device.id)).where(
            Device.cell_id == cell_id,
            Device.is_active == True,
            Device.is_connected == False,
        )
    )
    return int(result.scalar_one())


async def refresh_cell_load(db: AsyncSession, cell: HiveCell) -> None:
    cell.last_seen_at = datetime.utcnow()
    cell.updated_at = datetime.utcnow()


async def _list_assignable_cells(db: AsyncSession) -> list[HiveCell]:
    result = await db.execute(
        select(HiveCell)
        .where(HiveCell.status.in_(CELL_STATUSES_ASSIGNABLE))
        .order_by(HiveCell.priority.asc(), HiveCell.created_at.asc())
    )
    return list(result.scalars().all())


async def migrate_devices_to_queen(db: AsyncSession) -> int:
    """Вернуть всех клиентов на Улей (после отключения worker-routing)."""
    queen = await ensure_queen_cell(db)
    result = await db.execute(
        select(func.count(Device.id)).where(
            Device.is_active == True,
            Device.cell_id != queen.id,
        )
    )
    n = int(result.scalar_one())
    if n <= 0:
        return 0
    await db.execute(
        update(Device)
        .where(Device.is_active == True, Device.cell_id != queen.id)
        .values(cell_id=queen.id)
    )
    await db.commit()
    logger.warning("Hive: migrated %s device(s) back to queen", n)
    return n


async def pick_cell_for_new_device(
    db: AsyncSession,
    *,
    user: User | None = None,
) -> HiveCell:
    """
    Новое устройство:
    - по умолчанию Улей;
    - bootstrap всегда Улей;
    - если HIVE_WORKER_ROUTING_ENABLED и CPU/RAM перегружены — сота с минимумом онлайн VPN.
    """
    queen = await ensure_queen_cell(db)
    if not settings.HIVE_WORKER_ROUTING_ENABLED:
        return queen
    if user is not None and user.email == BOOTSTRAP_USER_EMAIL:
        return queen

    accepting, load_info = queen_accepting_new_vpn()
    if accepting:
        logger.debug(
            "Hive pick: queen OK cpu=%s mem=%s build=%s",
            load_info.get("cpu_percent"),
            load_info.get("memory_percent"),
            load_info.get("build_running"),
        )
        return queen

    workers = [c for c in await _list_assignable_cells(db) if not c.is_queen]
    if not workers:
        logger.warning(
            "Hive: queen overloaded (cpu=%s mem=%s), сот нет — остаёмся на Улье",
            load_info.get("cpu_percent"),
            load_info.get("memory_percent"),
        )
        return queen

    candidates: list[tuple[HiveCell, int, int]] = []
    for cell in workers:
        online = await count_online_on_cell(db, cell.id)
        cap = await max_online_for_cell(db, cell)
        if online < cap:
            candidates.append((cell, online, cap))
    if not candidates:
        logger.warning("Hive: все соты заполнены, оставляем новое устройство на Улье")
        return queen

    best, best_online, best_cap = candidates[0]
    for cell, online, cap in candidates[1:]:
        if online < best_online:
            best, best_online, best_cap = cell, online, cap
        elif online == best_online and cap > best_cap:
            best, best_online, best_cap = cell, online, cap

    logger.info(
        "Hive pick: queen overloaded → %s (online=%s/%s), queen cpu=%s mem=%s net=%s",
        best.name,
        best_online,
        best_cap,
        load_info.get("cpu_percent"),
        load_info.get("memory_percent"),
        load_info.get("network_util_percent"),
    )
    return best


async def resolve_cell_for_device(
    db: AsyncSession,
    device: Device,
    *,
    force_queen: bool = False,
) -> HiveCell:
    """Липкое назначение; перераспределение только для новых устройств."""
    queen = await ensure_queen_cell(db)
    if force_queen or not settings.HIVE_WORKER_ROUTING_ENABLED:
        if device.cell_id != queen.id:
            device.cell_id = queen.id
            await db.commit()
        return queen

    if device.cell_id:
        cell = await get_cell_by_id(db, device.cell_id)
        if cell and cell.status in CELL_STATUSES_ASSIGNABLE:
            if settings.HIVE_REBALANCE_EXISTING_DEVICES:
                online = await count_online_on_cell(db, cell.id)
                if online >= await max_online_for_cell(db, cell):
                    cell = await pick_cell_for_new_device(db)
                    if device.cell_id != cell.id:
                        device.cell_id = cell.id
                        await db.commit()
            return cell
        if cell and cell.status == "draining":
            return cell

    cell = await pick_cell_for_new_device(db)
    if device.cell_id != cell.id:
        device.cell_id = cell.id
        await db.commit()
    return cell


async def cell_agent_handshake(
    api_url: str,
    password: str,
    *,
    timeout_sec: float | None = None,
) -> dict:
    base = _validate_outbound_url(api_url)
    timeout = timeout_sec or settings.HIVE_CELL_HTTP_TIMEOUT_SEC
    url = f"{base}/v1/handshake"
    headers = {"X-Cell-Agent-Secret": password}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        resp = await client.post(url, headers=headers, json={})
    if resp.status_code == 401:
        raise ValueError("Неверный пароль cell-agent")
    if resp.status_code >= 400:
        raise ValueError(f"cell-agent HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("cell-agent: неверный ответ")
    return data


async def probe_cell_agent(cell: HiveCell, password: str | None = None) -> dict:
    if not cell.api_url:
        raise ValueError("У соты не задан api_url")
    pwd = password
    if not pwd and cell.api_secret_enc:
        try:
            pwd = decrypt_value(cell.api_secret_enc)
        except Exception as e:
            raise ValueError("Не удалось расшифровать пароль соты") from e
    if not pwd:
        raise ValueError("Пароль cell-agent не задан")
    return await cell_agent_handshake(cell.api_url, pwd)


async def fetch_worker_cell_load(cell: HiveCell) -> dict | None:
    """CPU/RAM соты через cell-agent /v1/status."""
    if cell.is_queen or not cell.api_url or cell.status not in ("active", "draining"):
        return None
    pwd: str | None = None
    if cell.api_secret_enc:
        try:
            pwd = decrypt_value(cell.api_secret_enc)
        except Exception:
            return None
    if not pwd:
        return None
    try:
        base = _validate_outbound_url(cell.api_url)
    except ValueError:
        return None
    url = f"{base}/v1/status"
    headers = {"X-Cell-Agent-Secret": pwd}
    timeout = settings.HIVE_CELL_HTTP_TIMEOUT_SEC
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code >= 400:
            return None
        data = resp.json()
        if not isinstance(data, dict):
            return None
        raw_link = float(data.get("network_link_capacity_mbps") or 0)
        return {
            "cpu_percent": round(float(data.get("cpu_percent") or 0), 1),
            "memory_percent": round(float(data.get("memory_percent") or 0), 1),
            "network_interface": (data.get("network_interface") or None),
            "network_mbps_rx": round(float(data.get("network_mbps_rx") or 0), 1),
            "network_mbps_tx": round(float(data.get("network_mbps_tx") or 0), 1),
            "network_util_percent": round(float(data.get("network_util_percent") or 0), 1),
            "network_link_capacity_mbps": round(raw_link, 1) if raw_link > 0 else None,
            "cpu_cores": int(data.get("cpu_cores") or 0) or None,
            "memory_total_gb": round(float(data.get("memory_total_gb") or 0), 1) or None,
            "wdtt_active": bool(data.get("wdtt_active")),
        }
    except Exception as e:
        logger.debug("Hive: load %s failed: %s", cell.name, e)
        return None


def store_cell_secret(cell: HiveCell, password: str) -> None:
    cell.api_secret_enc = encrypt_value(password)


def cell_to_response(
    cell: HiveCell,
    *,
    online_count: int,
    assigned_devices: int,
    load: dict | None = None,
    capacity: dict | None = None,
) -> dict:
    out = {
        "id": cell.id,
        "name": cell.name,
        "is_queen": cell.is_queen,
        "public_ip": cell.public_ip,
        "wdtt_port": cell.wdtt_port,
        "wg_port": cell.wg_port,
        "wg_public_key": cell.wg_public_key or "",
        "api_url": cell.api_url,
        "has_agent": bool(cell.api_url and cell.api_secret_enc),
        "tunnel_api_url": cell.tunnel_api_url,
        "max_clients": cell.max_clients,
        "link_capacity_mbps": float(cell.link_capacity_mbps) if cell.link_capacity_mbps else None,
        "max_online": capacity["max_online"] if capacity else 0,
        "capacity": capacity,
        "online_count": online_count,
        "assigned_devices": assigned_devices,
        "status": cell.status,
        "priority": cell.priority,
        "last_seen_at": cell.last_seen_at,
        "last_error": cell.last_error,
        "created_at": cell.created_at,
    }
    if load:
        out["load"] = load
    return out


async def list_cells_with_stats(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(HiveCell).order_by(HiveCell.is_queen.desc(), HiveCell.priority.asc())
    )
    cells = result.scalars().all()
    _, queen_load = queen_accepting_new_vpn()

    workers = [c for c in cells if not c.is_queen]
    worker_loads = await asyncio.gather(
        *[fetch_worker_cell_load(c) for c in workers],
        return_exceptions=True,
    )
    worker_load_map: dict[uuid.UUID, dict | None] = {}
    for cell, load in zip(workers, worker_loads):
        worker_load_map[cell.id] = load if isinstance(load, dict) else None

    out = []
    for cell in cells:
        online = await count_online_on_cell(db, cell.id)
        assigned = await count_assigned_on_cell(db, cell.id)
        if cell.is_queen:
            load = queen_load
        else:
            load = worker_load_map.get(cell.id)
        capacity = (await get_capacity_profile(db, cell, load=load)).to_dict()
        out.append(
            cell_to_response(
                cell,
                online_count=online,
                assigned_devices=assigned,
                load=load,
                capacity=capacity,
            )
        )
    return out


async def apply_agent_handshake_to_cell(cell: HiveCell, data: dict) -> None:
    pub_ip = (data.get("public_ip") or "").strip()
    wg_key = (data.get("wg_public_key") or "").strip()
    if pub_ip:
        cell.public_ip = pub_ip
    if wg_key:
        cell.wg_public_key = wg_key
    if data.get("wdtt_port"):
        cell.wdtt_port = int(data["wdtt_port"])
    if data.get("wg_port"):
        cell.wg_port = int(data["wg_port"])
    tunnel = (data.get("tunnel_api_url") or "").strip()
    if tunnel:
        cell.tunnel_api_url = tunnel
    cell.status = "active"
    cell.last_error = None
    cell.last_seen_at = datetime.utcnow()
    cell.updated_at = datetime.utcnow()


async def get_hive_summary_extra(db: AsyncSession) -> dict:
    accepting, load = queen_accepting_new_vpn()
    workers = [c for c in await _list_assignable_cells(db) if not c.is_queen]
    assignable = await _list_assignable_cells(db)
    total_online = 0
    total_capacity = 0
    full_cells = 0
    for cell in assignable:
        online = await count_online_on_cell(db, cell.id)
        load = queen_load if cell.is_queen else None
        cap = await max_online_for_cell(db, cell, load=load)
        total_online += online
        total_capacity += cap
        if online >= cap:
            full_cells += 1
    return {
        "queen_load": load,
        "queen_accepting_vpn": accepting,
        "worker_cells": len(workers),
        "total_online_vpn": total_online,
        "total_capacity_online": total_capacity,
        "full_cells": full_cells,
        "all_cells_full": bool(assignable) and full_cells >= len(assignable),
        "cpu_threshold": settings.HIVE_CPU_PERCENT_THRESHOLD,
        "mem_threshold": settings.HIVE_MEM_PERCENT_THRESHOLD,
        "bandwidth_threshold": settings.HIVE_BANDWIDTH_PERCENT_THRESHOLD,
    }


async def rebalance_overloaded_cells(db: AsyncSession) -> dict:
    if not settings.HIVE_REBALANCE_EXISTING_DEVICES:
        return {"moved": 0, "blocked": 0}
    cells = await _list_assignable_cells(db)
    states: dict[uuid.UUID, dict] = {}
    for cell in cells:
        online = await count_online_on_cell(db, cell.id)
        cap = await max_online_for_cell(db, cell)
        states[cell.id] = {"cell": cell, "online": online, "cap": cap}

    moved = 0
    blocked = 0
    for src in cells:
        src_state = states[src.id]
        overload = src_state["online"] - src_state["cap"]
        if overload <= 0:
            continue
        free_targets = [
            st for st in states.values()
            if st["cell"].id != src.id and st["online"] < st["cap"] and st["cell"].status == "active"
        ]
        free_targets.sort(key=lambda st: st["online"])
        for _ in range(overload):
            if not free_targets:
                blocked += 1
                break
            target = free_targets[0]
            q = await db.execute(
                select(Device)
                .where(
                    Device.cell_id == src.id,
                    Device.is_active == True,
                    Device.is_connected == False,
                )
                .order_by(Device.last_connected.asc().nullsfirst(), Device.created_at.asc())
                .limit(1)
            )
            candidate = q.scalar_one_or_none()
            if not candidate:
                blocked += 1
                break
            candidate.cell_id = target["cell"].id
            moved += 1
            src_state["online"] = max(0, src_state["online"] - 1)
            target["online"] += 1
            if target["online"] >= target["cap"]:
                free_targets.pop(0)
            else:
                free_targets.sort(key=lambda st: st["online"])
    if moved > 0:
        await db.commit()
    return {"moved": moved, "blocked": blocked}
