"""Admin API — управление кластером «Улей / Соты»."""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.models import HiveCell
from app.core.deps import get_admin_credentials
from app.config import settings
from app.schemas.hive import (
    HiveCellAutoConnect,
    HiveCellCreateManual,
    HiveCellCreateAgent,
    HiveCellUpdate,
    HiveCellSshRepair,
)
from app.services import hive_service
from app.services import hive_provision_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/hive", tags=["admin-hive"])

_FORCE_DELETE_STATUSES = frozenset({"provisioning", "error", "pending", "offline"})


async def _next_cell_name(db: AsyncSession) -> str:
    n = (await db.execute(select(func.count(HiveCell.id)).where(HiveCell.is_queen == False))).scalar_one()  # noqa: E712
    return f"Сота {int(n) + 1}"


async def _sweep_stale_provisioning(db: AsyncSession) -> None:
    """Зависшие «Настройка…» → ошибка (обрыв HTTP / таймаут nginx)."""
    cutoff = datetime.utcnow() - timedelta(minutes=settings.HIVE_PROVISION_STALE_MINUTES)
    result = await db.execute(
        select(HiveCell).where(
            HiveCell.status == "provisioning",
            HiveCell.is_queen == False,  # noqa: E712
            HiveCell.updated_at < cutoff,
        )
    )
    stale = result.scalars().all()
    for cell in stale:
        cell.status = "error"
        cell.last_error = (
            "Настройка прервана (таймаут). Удалите соту и подключите снова."
        )
        cell.updated_at = datetime.utcnow()
    if stale:
        await db.commit()


async def _provision_cell_background(
    cell_id: uuid.UUID,
    host: str,
    ssh_password: str,
    agent_secret: str,
    hive_api: str,
    wdtt_pass: str,
) -> None:
    async with AsyncSessionLocal() as db:
        cell = await hive_service.get_cell_by_id(db, cell_id)
        if not cell or cell.status != "provisioning":
            return
        try:
            result = await asyncio.to_thread(
                hive_provision_service.provision_cell_via_ssh,
                host,
                ssh_password,
                cell_agent_secret=agent_secret,
                hive_public_ip=settings.VPN_SERVER_IP,
                hive_api_base=hive_api,
                wdtt_master_password=wdtt_pass,
                cell_id=str(cell_id),
            )
            cell = await hive_service.get_cell_by_id(db, cell_id)
            if not cell:
                return
            cell.public_ip = result["public_ip"]
            cell.wg_public_key = result["wg_public_key"]
            cell.wdtt_port = int(result.get("wdtt_port") or settings.VPN_SERVER_PORT)
            cell.wg_port = int(result.get("wg_port") or settings.WG_PORT)
            cell.api_url = result.get("api_url")
            cell.tunnel_api_url = result.get("tunnel_api_url")
            cell.status = "active"
            cell.last_error = None
            cell.last_seen_at = datetime.utcnow()
            cell.updated_at = datetime.utcnow()
            await db.commit()
            logger.info("Hive: сота %s (%s) active", cell.name, host)
        except Exception as e:
            cell = await hive_service.get_cell_by_id(db, cell_id)
            if cell:
                cell.status = "error"
                cell.last_error = str(e)[:500]
                cell.updated_at = datetime.utcnow()
                await db.commit()
            logger.exception("Hive provision failed for %s: %s", host, e)


@router.get("/cells")
async def list_hive_cells(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    await hive_service.ensure_queen_cell(db)
    await _sweep_stale_provisioning(db)
    await hive_service.rebalance_overloaded_cells(db)
    return await hive_service.list_cells_with_stats(db)


@router.post("/cells/auto")
async def auto_connect_cell(
    req: HiveCellAutoConnect,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Автоподключение в фоне: сразу «Настройка…», UI опрашивает список."""
    await hive_service.ensure_queen_cell(db)
    host = req.host.strip()
    name = (req.name or "").strip() or await _next_cell_name(db)
    agent_secret = hive_provision_service.generate_cell_agent_secret()
    cell_id = uuid.uuid4()

    wdtt_pass = (settings.WDTT_MASTER_PASSWORD or "").strip()
    if not wdtt_pass:
        raise HTTPException(status_code=400, detail="WDTT_MASTER_PASSWORD не задан на Улье")
    if not (settings.VPN_SERVER_IP or "").strip():
        raise HTTPException(status_code=400, detail="VPN_SERVER_IP не задан на Улье")

    hive_api = (settings.FRONTEND_URL or f"https://{settings.VPN_SERVER_IP}").strip()

    cell = HiveCell(
        id=cell_id,
        name=name,
        is_queen=False,
        public_ip=host,
        wdtt_port=settings.VPN_SERVER_PORT,
        wg_port=settings.WG_PORT,
        max_clients=0,
        link_capacity_mbps=float(settings.HIVE_CELL_DEFAULT_LINK_CAPACITY_MBPS),
        priority=100,
        status="provisioning",
        last_seen_at=datetime.utcnow(),
    )
    hive_service.store_cell_secret(cell, agent_secret)
    db.add(cell)
    await db.commit()
    await db.refresh(cell)

    asyncio.create_task(
        _provision_cell_background(
            cell_id,
            host,
            req.password,
            agent_secret,
            hive_api,
            wdtt_pass,
        )
    )

    online = await hive_service.count_online_on_cell(db, cell.id)
    assigned = await hive_service.count_assigned_on_cell(db, cell.id)
    resp = hive_service.cell_to_response(cell, online_count=online, assigned_devices=assigned)
    resp["message"] = "Настройка соты запущена в фоне"
    return resp


@router.post("/cells/manual")
async def add_cell_manual(
    req: HiveCellCreateManual,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    cell = HiveCell(
        name=req.name.strip(),
        is_queen=False,
        public_ip=req.public_ip.strip(),
        wdtt_port=req.wdtt_port,
        wg_port=req.wg_port,
        wg_public_key=req.wg_public_key.strip(),
        max_clients=req.max_clients,
        link_capacity_mbps=float(settings.HIVE_CELL_DEFAULT_LINK_CAPACITY_MBPS),
        priority=req.priority,
        tunnel_api_url=(req.tunnel_api_url or "").strip() or None,
        status="active",
        last_seen_at=datetime.utcnow(),
    )
    db.add(cell)
    await db.commit()
    await db.refresh(cell)
    online = await hive_service.count_online_on_cell(db, cell.id)
    assigned = await hive_service.count_assigned_on_cell(db, cell.id)
    return hive_service.cell_to_response(cell, online_count=online, assigned_devices=assigned)


@router.post("/cells/connect")
async def connect_cell_agent(
    req: HiveCellCreateAgent,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Подключить уже настроенную соту через cell-agent (API + пароль)."""
    try:
        api_url = hive_service._validate_outbound_url(req.api_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        data = await hive_service.cell_agent_handshake(api_url, req.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"cell-agent недоступен: {e}") from e

    pub_ip = (data.get("public_ip") or "").strip()
    wg_key = (data.get("wg_public_key") or "").strip()
    if not pub_ip or not wg_key:
        raise HTTPException(
            status_code=400,
            detail="cell-agent не вернул public_ip или wg_public_key",
        )

    cell = HiveCell(
        name=req.name.strip(),
        is_queen=False,
        public_ip=pub_ip,
        wdtt_port=int(data.get("wdtt_port") or settings.VPN_SERVER_PORT),
        wg_port=int(data.get("wg_port") or settings.WG_PORT),
        wg_public_key=wg_key,
        api_url=api_url,
        max_clients=req.max_clients,
        link_capacity_mbps=float(settings.HIVE_CELL_DEFAULT_LINK_CAPACITY_MBPS),
        priority=req.priority,
        status="pending",
    )
    hive_service.store_cell_secret(cell, req.password)
    await hive_service.apply_agent_handshake_to_cell(cell, data)
    db.add(cell)
    await db.commit()
    await db.refresh(cell)
    online = await hive_service.count_online_on_cell(db, cell.id)
    assigned = await hive_service.count_assigned_on_cell(db, cell.id)
    return hive_service.cell_to_response(cell, online_count=online, assigned_devices=assigned)


@router.post("/cells/{cell_id}/probe")
async def probe_cell(
    cell_id: uuid.UUID,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    cell = await hive_service.get_cell_by_id(db, cell_id)
    if not cell:
        raise HTTPException(status_code=404, detail="Сота не найдена")
    if cell.is_queen:
        cell.last_seen_at = datetime.utcnow()
        cell.last_error = None
        await db.commit()
        online = await hive_service.count_online_on_cell(db, cell.id)
        assigned = await hive_service.count_assigned_on_cell(db, cell.id)
        return hive_service.cell_to_response(cell, online_count=online, assigned_devices=assigned)
    if not cell.api_url:
        raise HTTPException(status_code=400, detail="У соты нет cell-agent")
    try:
        data = await hive_service.probe_cell_agent(cell)
        await hive_service.apply_agent_handshake_to_cell(cell, data)
        await db.commit()
        await db.refresh(cell)
    except ValueError as e:
        cell.last_error = str(e)[:500]
        cell.status = "error"
        await db.commit()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        cell.last_error = str(e)[:500]
        cell.status = "error"
        await db.commit()
        raise HTTPException(status_code=502, detail=str(e)) from e
    online = await hive_service.count_online_on_cell(db, cell.id)
    assigned = await hive_service.count_assigned_on_cell(db, cell.id)
    return hive_service.cell_to_response(cell, online_count=online, assigned_devices=assigned)


@router.patch("/cells/{cell_id}")
async def update_cell(
    cell_id: uuid.UUID,
    req: HiveCellUpdate,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    cell = await hive_service.get_cell_by_id(db, cell_id)
    if not cell:
        raise HTTPException(status_code=404, detail="Сота не найдена")
    if cell.is_queen and req.status == "offline":
        raise HTTPException(status_code=400, detail="Соту-Улей нельзя отключить")
    if req.name is not None:
        cell.name = req.name.strip()
    if req.max_clients is not None:
        cell.max_clients = req.max_clients
    if req.priority is not None:
        cell.priority = req.priority
    if req.status is not None:
        cell.status = req.status
    if req.wg_public_key is not None and not cell.is_queen:
        cell.wg_public_key = req.wg_public_key.strip()
    if req.public_ip is not None and not cell.is_queen:
        cell.public_ip = req.public_ip.strip()
    if req.link_capacity_mbps is not None and not cell.is_queen:
        cell.link_capacity_mbps = float(req.link_capacity_mbps) if req.link_capacity_mbps > 0 else None
    cell.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(cell)
    online = await hive_service.count_online_on_cell(db, cell.id)
    assigned = await hive_service.count_assigned_on_cell(db, cell.id)
    return hive_service.cell_to_response(cell, online_count=online, assigned_devices=assigned)


@router.delete("/cells/{cell_id}")
async def delete_cell(
    cell_id: uuid.UUID,
    force: bool = Query(False, description="Удалить соту в настройке/ошибке без проверок"),
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    cell = await hive_service.get_cell_by_id(db, cell_id)
    if not cell:
        raise HTTPException(status_code=404, detail="Сота не найдена")
    if cell.is_queen:
        raise HTTPException(status_code=400, detail="Соту-Улей нельзя удалить")

    skip_checks = force or cell.status in _FORCE_DELETE_STATUSES
    if not skip_checks:
        assigned = await hive_service.count_assigned_on_cell(db, cell.id)
        if assigned > 0:
            raise HTTPException(
                status_code=409,
                detail=f"На соте {assigned} устройств — сначала включите draining",
            )
        online = await hive_service.count_online_on_cell(db, cell.id)
        if online > 0:
            raise HTTPException(status_code=409, detail="На соте есть активные VPN-подключения")

    await db.delete(cell)
    await db.commit()
    return {"ok": True, "message": "Сота удалена"}


@router.post("/cells/{cell_id}/upgrade-agent")
async def upgrade_cell_agent(
    cell_id: uuid.UUID,
    req: HiveCellSshRepair,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Обновить cell-agent на соте (CPU/RAM) — нужен SSH root-пароль."""
    cell = await hive_service.get_cell_by_id(db, cell_id)
    if not cell:
        raise HTTPException(status_code=404, detail="Сота не найдена")
    if cell.is_queen:
        raise HTTPException(status_code=400, detail="Улей обновляется с деплоем backend")
    host = (cell.public_ip or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="У соты нет public_ip")
    try:
        await asyncio.to_thread(
            hive_provision_service.upgrade_cell_agent_via_ssh,
            host,
            req.password,
            link_capacity_mbps=float(cell.link_capacity_mbps or settings.HIVE_CELL_DEFAULT_LINK_CAPACITY_MBPS),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"ok": True, "message": "cell-agent обновлён — обновите страницу через несколько секунд"}


@router.get("/summary")
async def hive_summary(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    await hive_service.ensure_queen_cell(db)
    rebalance = await hive_service.rebalance_overloaded_cells(db)
    cells = await hive_service.list_cells_with_stats(db)
    extra = await hive_service.get_hive_summary_extra(db)
    queen = await hive_service.get_queen_cell(db)
    queen_capacity = None
    if queen:
        from app.services.hive_capacity import get_capacity_profile

        queen_capacity = (
            await get_capacity_profile(db, queen, load=extra.get("queen_load"))
        ).to_dict()
    return {
        "cells_total": len(cells),
        "cells_active": sum(1 for c in cells if c["status"] == "active"),
        "total_online_vpn": extra["total_online_vpn"],
        "worker_cells": extra["worker_cells"],
        "queen_load": extra["queen_load"],
        "queen_accepting_vpn": extra["queen_accepting_vpn"],
        "cpu_threshold": extra["cpu_threshold"],
        "mem_threshold": extra["mem_threshold"],
        "bandwidth_threshold": extra["bandwidth_threshold"],
        "total_capacity_online": extra["total_capacity_online"],
        "all_cells_full": extra["all_cells_full"],
        "full_cells": extra["full_cells"],
        "rebalanced_moved": rebalance["moved"],
        "rebalanced_blocked": rebalance["blocked"],
        "queen_capacity": queen_capacity,
    }
