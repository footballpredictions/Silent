"""Улей — управление VPN-сотами и балансировка нагрузки."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
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
from app.services.hive_incidents import push_incident
from app.services.hive_load import (
    is_vpn_overloaded,
    load_stress_score,
    queen_accepting_new_vpn,
    queen_vpn_has_headroom,
    queen_vpn_spill_threshold,
)

logger = logging.getLogger(__name__)

CELL_STATUSES_ACTIVE = frozenset({"active"})
CELL_STATUSES_ASSIGNABLE = frozenset({"active"})
BOOTSTRAP_USER_EMAIL = "__bootstrap__@silent.local"
_CELL_NUM_RE = re.compile(r"(\d+)", re.IGNORECASE)


def cell_name_number(name: str) -> int | None:
    m = _CELL_NUM_RE.search(name or "")
    return int(m.group(1)) if m else None


def cell_list_sort_key(cell: HiveCell) -> tuple:
    """Улей → соты по номеру в имени (Сота 1, Сота 2…), не по дате создания."""
    if cell.is_queen:
        return (0, 0, "")
    num = cell_name_number(cell.name)
    return (1, cell.priority, num if num is not None else 9999, cell.name or "")


def link_capacity_mbps_for_cell(cell: HiveCell) -> float:
    """«Сота 1» — 10 Гбит/с, остальные worker — 1 Гбит/с (если в БД не задано иное)."""
    if cell.link_capacity_mbps and float(cell.link_capacity_mbps) > 0:
        return float(cell.link_capacity_mbps)
    num = cell_name_number(cell.name)
    if num == 1:
        return float(settings.HIVE_CELL_FIRST_LINK_CAPACITY_MBPS)
    return float(settings.HIVE_CELL_DEFAULT_LINK_CAPACITY_MBPS)


async def link_capacity_mbps_for_new_cell(name: str) -> float:
    num = cell_name_number(name)
    if num == 1:
        return float(settings.HIVE_CELL_FIRST_LINK_CAPACITY_MBPS)
    return float(settings.HIVE_CELL_DEFAULT_LINK_CAPACITY_MBPS)


def display_link_capacity_mbps(cell: HiveCell, agent_data: dict) -> float | None:
    """Канал для UI: sysfs с соты → значение в БД → env агента."""
    sysfs = float(agent_data.get("network_link_sysfs_mbps") or 0)
    if sysfs > 0:
        return round(sysfs, 1)
    if cell.link_capacity_mbps and float(cell.link_capacity_mbps) > 0:
        return float(cell.link_capacity_mbps)
    raw = float(agent_data.get("network_link_capacity_mbps") or 0)
    if raw > 0:
        return round(raw, 1)
    return None


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


async def olcrtc_exit_cell_ips(db: AsyncSession) -> set[str]:
    """IP сот, занятых olcrtc2 (Телемост/WB) — не WDTT-балансир."""
    from app.services.olcrtc2_settings import cell_ip_for_provider, load_olcrtc2_settings

    s = await load_olcrtc2_settings(db)
    ips = {
        (cell_ip_for_provider(s, "telemost") or "").strip(),
        (cell_ip_for_provider(s, "wbstream") or "").strip(),
    }
    return {ip for ip in ips if ip}


def cell_accepts_wdtt_spill(cell: HiveCell, olcrtc_ips: set[str]) -> bool:
    """Улей — да. Сота olcrtc2 — нет. Остальные (3, 4, …) — да."""
    if cell.is_queen:
        return True
    if getattr(cell, "accepts_wdtt", True) is False:
        return False
    ip = (cell.public_ip or "").strip()
    return ip not in olcrtc_ips


async def list_wdtt_spill_workers(db: AsyncSession) -> list[HiveCell]:
    reserved = await olcrtc_exit_cell_ips(db)
    return [
        c
        for c in await _list_assignable_cells(db)
        if not c.is_queen and cell_accepts_wdtt_spill(c, reserved)
    ]


async def sync_olcrtc_cells_no_wdtt_spill(db: AsyncSession) -> int:
    """Пометить Сота 1/2 (olcrtc2 exit) как не-WDTT, чтобы баланс шёл на 3+."""
    reserved = await olcrtc_exit_cell_ips(db)
    if not reserved:
        return 0
    rows = (await db.execute(select(HiveCell).where(HiveCell.is_queen.is_(False)))).scalars().all()
    n = 0
    for cell in rows:
        ip = (cell.public_ip or "").strip()
        want = ip not in reserved
        if bool(getattr(cell, "accepts_wdtt", True)) != want:
            cell.accepts_wdtt = want
            n += 1
    if n:
        await db.commit()
        logger.info("Hive: marked %s olcrtc cell(s) accepts_wdtt=false", n)
    return n


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
    - если HIVE_WORKER_ROUTING_ENABLED и лимит онлайн на Улье заполнен (≥85%) или CPU/RAM перегружены при заполнении — сота.
    """
    queen = await ensure_queen_cell(db)
    if not settings.HIVE_WORKER_ROUTING_ENABLED:
        return queen
    if user is not None and user.email == BOOTSTRAP_USER_EMAIL:
        return queen

    accepting, load_info = queen_accepting_new_vpn()
    queen_online = await count_online_on_cell(db, queen.id)
    queen_cap = await max_online_for_cell(db, queen, load=load_info)
    if queen_vpn_has_headroom(queen_online, queen_cap):
        logger.debug(
            "Hive pick: queen VPN headroom online=%s cap=%s threshold=%s",
            queen_online,
            queen_cap,
            queen_vpn_spill_threshold(queen_cap),
        )
        return queen

    if accepting:
        logger.debug(
            "Hive pick: queen OK cpu=%s mem=%s build=%s",
            load_info.get("cpu_percent"),
            load_info.get("memory_percent"),
            load_info.get("build_running"),
        )
        return queen

    await sync_olcrtc_cells_no_wdtt_spill(db)
    workers = await list_wdtt_spill_workers(db)
    if not workers:
        logger.warning(
            "Hive: queen overloaded (cpu=%s mem=%s), WDTT-сот нет (1/2 заняты olcrtc) — остаёмся на Улье",
            load_info.get("cpu_percent"),
            load_info.get("memory_percent"),
        )
        return queen

    candidates: list[tuple[HiveCell, int, int, float]] = []
    for cell in workers:
        wload = await fetch_worker_cell_load(cell)
        if wload and is_vpn_overloaded(wload):
            continue
        online = await count_online_on_cell(db, cell.id)
        cap = await max_online_for_cell(db, cell, load=wload)
        if online < cap:
            candidates.append((cell, online, cap, load_stress_score(wload)))
    if not candidates:
        logger.warning("Hive: все соты заполнены или перегружены, оставляем новое устройство на Улье")
        return queen

    best, best_online, best_cap, _ = min(
        candidates,
        key=lambda item: (item[3], item[1], -item[2]),
    )

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
                if cell.is_queen:
                    _, cell_load = queen_accepting_new_vpn()
                else:
                    cell_load = await fetch_worker_cell_load(cell)
                online = await count_online_on_cell(db, cell.id)
                cap = await max_online_for_cell(db, cell, load=cell_load)
                relocate = online >= cap
                if relocate and queen_vpn_has_headroom(online, cap):
                    relocate = False
                if settings.HIVE_REBALANCE_ON_HARDWARE and cell_load and is_vpn_overloaded(cell_load):
                    if not queen_vpn_has_headroom(online, cap):
                        relocate = True
                if relocate:
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
            push_incident(
                source="cell-agent.status",
                severity="warning",
                cell_name=cell.name,
                cell_ip=cell.public_ip,
                message=f"/v1/status HTTP {resp.status_code}",
                details=resp.text[:220],
            )
            return None
        data = resp.json()
        if not isinstance(data, dict):
            return None
        link_display = display_link_capacity_mbps(cell, data)
        sysfs = float(data.get("network_link_sysfs_mbps") or 0)
        return {
            "cpu_percent": round(float(data.get("cpu_percent") or 0), 1),
            "memory_percent": round(float(data.get("memory_percent") or 0), 1),
            "network_interface": (data.get("network_interface") or None),
            "network_mbps_rx": round(float(data.get("network_mbps_rx") or 0), 1),
            "network_mbps_tx": round(float(data.get("network_mbps_tx") or 0), 1),
            "network_util_percent": round(float(data.get("network_util_percent") or 0), 1),
            "network_link_capacity_mbps": link_display,
            "network_link_sysfs_mbps": round(sysfs, 1) if sysfs > 0 else None,
            "cpu_cores": int(data.get("cpu_cores") or 0) or None,
            "memory_total_gb": round(float(data.get("memory_total_gb") or 0), 1) or None,
            "wdtt_active": bool(data.get("wdtt_active")),
            "agent_build_id": (data.get("agent_build_id") or None),
        }
    except Exception as e:
        logger.debug("Hive: load %s failed: %s", cell.name, e)
        push_incident(
            source="cell-agent.status",
            severity="warning",
            cell_name=cell.name,
            cell_ip=cell.public_ip,
            message=f"/v1/status failed: {e}",
        )
        return None


def store_cell_secret(cell: HiveCell, password: str) -> None:
    cell.api_secret_enc = encrypt_value(password)


def store_ssh_password(cell: HiveCell, password: str) -> None:
    cell.ssh_password_enc = encrypt_value(password)


def resolve_ssh_password(cell: HiveCell) -> str | None:
    if not cell.ssh_password_enc:
        return None
    try:
        return decrypt_value(cell.ssh_password_enc)
    except Exception:
        return None


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
        "has_ssh_password": bool(cell.ssh_password_enc),
        "tunnel_api_url": cell.tunnel_api_url,
        "max_clients": cell.max_clients,
        "link_capacity_mbps": float(cell.link_capacity_mbps) if cell.link_capacity_mbps else None,
        "max_online": capacity["max_online"] if capacity else 0,
        "capacity": capacity,
        "online_count": online_count,
        "assigned_devices": assigned_devices,
        "status": cell.status,
        "priority": cell.priority,
        "accepts_wdtt": bool(cell.is_queen or getattr(cell, "accepts_wdtt", True)),
        "last_seen_at": cell.last_seen_at,
        "last_error": cell.last_error,
        "created_at": cell.created_at,
    }
    if load:
        out["load"] = load
    return out


async def list_cells_with_stats(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(HiveCell).order_by(
            HiveCell.is_queen.desc(),
            HiveCell.priority.asc(),
            HiveCell.created_at.asc(),
        )
    )
    cells = list(result.scalars().all())
    cells.sort(key=cell_list_sort_key)
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
        capacity = (await get_capacity_profile(db, cell, load=load, online_count=online)).to_dict()
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
    await sync_olcrtc_cells_no_wdtt_spill(db)
    accepting, queen_load = queen_accepting_new_vpn()
    all_workers = [c for c in await _list_assignable_cells(db) if not c.is_queen]
    spill_workers = await list_wdtt_spill_workers(db)
    assignable = await _list_assignable_cells(db)
    reserved = await olcrtc_exit_cell_ips(db)
    total_online = 0
    total_capacity = 0
    full_cells = 0
    for cell in assignable:
        if not cell.is_queen and not cell_accepts_wdtt_spill(cell, reserved):
            continue
        online = await count_online_on_cell(db, cell.id)
        cell_load = queen_load if cell.is_queen else None
        cap = await max_online_for_cell(db, cell, load=cell_load)
        total_online += online
        total_capacity += cap
        if online >= cap:
            full_cells += 1
    wdtt_nodes = 1 + len(spill_workers)  # queen + spill
    return {
        "queen_load": queen_load,
        "queen_accepting_vpn": accepting,
        "worker_cells": len(spill_workers),
        "olcrtc_cells": len(all_workers) - len(spill_workers),
        "total_online_vpn": total_online,
        "total_capacity_online": total_capacity,
        "full_cells": full_cells,
        "all_cells_full": wdtt_nodes > 0 and full_cells >= wdtt_nodes,
        "cpu_threshold": settings.HIVE_CPU_PERCENT_THRESHOLD,
        "mem_threshold": settings.HIVE_MEM_PERCENT_THRESHOLD,
        "bandwidth_threshold": settings.HIVE_BANDWIDTH_PERCENT_THRESHOLD,
    }


async def _pop_offline_device(db: AsyncSession, cell_id: uuid.UUID) -> Device | None:
    q = await db.execute(
        select(Device)
        .where(
            Device.cell_id == cell_id,
            Device.is_active == True,  # noqa: E712
            Device.is_connected == False,  # noqa: E712
        )
        .order_by(Device.last_connected.asc().nullsfirst(), Device.created_at.asc())
        .limit(1)
    )
    return q.scalar_one_or_none()


def _pick_least_loaded_worker(
    workers: list[HiveCell],
    worker_loads: dict[uuid.UUID, dict | None],
    states: dict[uuid.UUID, dict],
) -> HiveCell | None:
    best: HiveCell | None = None
    best_score = float("inf")
    for cell in workers:
        if cell.status != "active":
            continue
        st = states.get(cell.id, {})
        if st.get("online", 0) >= st.get("cap", 0):
            continue
        load = worker_loads.get(cell.id)
        if load and is_vpn_overloaded(load):
            continue
        score = load_stress_score(load) + st.get("online", 0) * 0.01
        if score < best_score:
            best_score = score
            best = cell
    return best


async def rebalance_overloaded_cells(db: AsyncSession) -> dict:
    empty = {"moved": 0, "blocked": 0, "hardware": 0, "returned": 0}
    if not settings.HIVE_REBALANCE_EXISTING_DEVICES:
        return empty
    if not settings.HIVE_WORKER_ROUTING_ENABLED:
        return {**empty, "routing_off": True}

    await sync_olcrtc_cells_no_wdtt_spill(db)
    reserved = await olcrtc_exit_cell_ips(db)
    cells = await _list_assignable_cells(db)
    queen = await ensure_queen_cell(db)
    _, queen_load = queen_accepting_new_vpn()
    all_workers = [c for c in cells if not c.is_queen]
    workers = [c for c in all_workers if cell_accepts_wdtt_spill(c, reserved)]

    worker_loads: dict[uuid.UUID, dict | None] = {}
    for w in all_workers:
        worker_loads[w.id] = await fetch_worker_cell_load(w)

    states: dict[uuid.UUID, dict] = {}
    for cell in cells:
        online = await count_online_on_cell(db, cell.id)
        load = queen_load if cell.is_queen else worker_loads.get(cell.id)
        cap = await max_online_for_cell(db, cell, load=load)
        states[cell.id] = {"cell": cell, "online": online, "cap": cap, "load": load}

    moved = blocked = hardware = returned = 0

    def _wdtt_targets(src_id):
        found = [
            st
            for st in states.values()
            if st["cell"].id != src_id
            and st["online"] < st["cap"]
            and st["cell"].status == "active"
            and (st["cell"].is_queen or cell_accepts_wdtt_spill(st["cell"], reserved))
        ]
        found.sort(key=lambda st: (load_stress_score(st.get("load")), st["online"]))
        return found

    for src in cells:
        src_state = states[src.id]
        overload = src_state["online"] - src_state["cap"]
        if overload <= 0:
            continue
        free_targets = _wdtt_targets(src.id)
        free_targets.sort(key=lambda st: (load_stress_score(st.get("load")), st["online"]))
        for _ in range(overload):
            if not free_targets:
                blocked += 1
                break
            target = free_targets[0]
            candidate = await _pop_offline_device(db, src.id)
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
                free_targets.sort(key=lambda st: (load_stress_score(st.get("load")), st["online"]))

    if settings.HIVE_REBALANCE_ON_HARDWARE:
        batch = max(1, int(settings.HIVE_REBALANCE_HARDWARE_BATCH))
        for src in cells:
            src_load = states[src.id].get("load")
            if not src_load or not is_vpn_overloaded(src_load):
                continue
            if src.is_queen and queen_vpn_has_headroom(
                states[src.id]["online"], states[src.id]["cap"]
            ):
                continue
            for _ in range(batch):
                if src.is_queen:
                    target = _pick_least_loaded_worker(workers, worker_loads, states)
                else:
                    queen_st = states[queen.id]
                    queen_ok = queen_load and not is_vpn_overloaded(queen_load)
                    if queen_ok and queen_st["online"] < queen_st["cap"]:
                        target = queen
                    else:
                        others = [w for w in workers if w.id != src.id]
                        target = _pick_least_loaded_worker(others, worker_loads, states)
                if not target:
                    blocked += 1
                    break
                candidate = await _pop_offline_device(db, src.id)
                if not candidate:
                    break
                candidate.cell_id = target.id
                moved += 1
                hardware += 1

    if workers and queen_load and not is_vpn_overloaded(queen_load):
        batch = max(1, int(settings.HIVE_REBALANCE_RETURN_BATCH))
        queen_st = states[queen.id]
        if queen_vpn_has_headroom(queen_st["online"], queen_st["cap"]):
            for w in workers:
                for _ in range(batch):
                    candidate = await _pop_offline_device(db, w.id)
                    if not candidate:
                        break
                    candidate.cell_id = queen.id
                    moved += 1
                    returned += 1

    # WDTT-клиенты не должны сидеть на olcrtc-сотах 1/2.
    for src in all_workers:
        if cell_accepts_wdtt_spill(src, reserved):
            continue
        while True:
            candidate = await _pop_offline_device(db, src.id)
            if not candidate:
                break
            candidate.cell_id = queen.id
            moved += 1
            returned += 1

    if moved > 0:
        await db.commit()
    return {"moved": moved, "blocked": blocked, "hardware": hardware, "returned": returned}
