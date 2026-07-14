"""Admin API прокси-флота. Улей только управляет — сайты цепляются к primary proxy, не к VPN-сотам."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.deps import get_admin_credentials
from app.config import settings
from app.models.proxy_node import ProxyNode
from app.schemas.proxy import ProxyNodeConnect, ProxyNodePatch
from app.services import proxy_provision_service, proxy_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/proxy", tags=["admin-proxy"])


async def _next_name(db: AsyncSession, role: str) -> str:
    nodes = await proxy_service.list_nodes(db)
    n = len(nodes) + 1
    prefix = "proxy" if role == "dedicated" else "site"
    return f"{prefix}-{n}"


def _primary_endpoint_dict(primary: ProxyNode) -> dict:
    """Данные primary для привязки сайтов (HTTP + SOCKS)."""
    host = (primary.public_ip or "").strip()
    socks_user = primary.socks_user or "silent"
    socks_pwd = proxy_service.socks_pass(primary)
    socks_port = int(primary.socks_port or 1080)
    http_port = int(getattr(settings, "PROXY_HTTP_PORT", 3128) or 3128)
    http_user = (getattr(settings, "PROXY_HTTP_USER", None) or "top10proxy").strip()
    http_pass = (getattr(settings, "PROXY_HTTP_PASS", None) or "").strip()
    meta = {}
    if primary.previous_proxy_json:
        try:
            meta = json.loads(primary.previous_proxy_json)
        except Exception:
            meta = {}
    if not http_pass:
        http_pass = (meta.get("http_pass") or "").strip()
    if meta.get("http_port"):
        http_port = int(meta["http_port"])
    if meta.get("http_user"):
        http_user = str(meta["http_user"])
    socks_url = f"socks5://{socks_user}:{socks_pwd}@{host}:{socks_port}" if socks_pwd else ""
    http_url = f"http://{http_user}:{http_pass}@{host}:{http_port}" if http_pass else ""
    # если в БД нет HTTP-пароля — возьмём с agent primary
    if (not http_url) and primary.agent_url:
        try:
            import httpx

            secret = proxy_service.agent_secret(primary)
            with httpx.Client(timeout=8.0) as client:
                r = client.get(
                    f"{primary.agent_url.rstrip('/')}/v1/endpoint",
                    headers={"X-Proxy-Agent-Secret": secret},
                )
                if r.status_code == 200:
                    ep = r.json()
                    if ep.get("http_url"):
                        http_url = ep["http_url"]
                        http_user = ep.get("http_user") or http_user
                        http_pass = ep.get("http_password") or http_pass
                        http_port = int(ep.get("http_port") or http_port)
                    if ep.get("socks_url") or ep.get("url"):
                        socks_url = ep.get("socks_url") or ep.get("url") or socks_url
        except Exception as e:
            logger.warning("primary agent endpoint fetch failed: %s", e)
    return {
        "public_ip": host,
        "socks_port": socks_port,
        "socks_user": socks_user,
        "socks_url": socks_url,
        "http_port": http_port,
        "http_user": http_user,
        "http_pass": http_pass,
        "http_url": http_url,
        "agent_url": primary.agent_url,
    }


async def _provision_background(
    node_id: uuid.UUID,
    host: str,
    password: str,
    ssh_port: int,
    role: str,
    socks_port: int,
    socks_user: str,
    socks_pass: str,
    agent_secret: str,
    primary_payload: dict | None,
) -> None:
    from app.database import AsyncSessionLocal

    try:
        result = await asyncio.to_thread(
            proxy_provision_service.provision_proxy_node,
            host=host,
            password=password,
            ssh_port=ssh_port,
            role=role,
            socks_port=socks_port,
            socks_user=socks_user,
            socks_pass=socks_pass,
            agent_secret=agent_secret,
            public_ip=host,
            primary=primary_payload,
            http_user=getattr(settings, "PROXY_HTTP_USER", None) or "top10proxy",
            http_pass=(getattr(settings, "PROXY_HTTP_PASS", None) or "") or None,
        )
        async with AsyncSessionLocal() as db:
            node = await proxy_service.get_node(db, node_id)
            if not node:
                return
            node.public_ip = result.get("public_ip") or host
            if result.get("socks_port"):
                node.socks_port = int(result["socks_port"])
            if result.get("socks_user"):
                node.socks_user = result["socks_user"]
            node.agent_url = result.get("agent_url")
            if result.get("ssh_port_used"):
                node.ssh_port = int(result["ssh_port_used"])
            # для dedicated сохраняем http meta в previous_proxy_json рядом со snapshot
            prev = result.get("previous_proxy") or {}
            if role == "dedicated":
                prev["http_port"] = result.get("http_port")
                prev["http_user"] = result.get("http_user")
                prev["http_pass"] = result.get("http_pass")
                prev["http_url"] = result.get("http_url")
                prev["mtproto_port"] = result.get("mtproto_port")
                prev["mtproto_secret"] = result.get("mtproto_secret")
                prev["telegram_link"] = result.get("telegram_link")
            if role == "attached":
                prev["bound_to"] = result.get("bound_to")
                prev["http_url"] = result.get("http_url")
                prev["socks_url"] = result.get("socks_url")
                prev["env_updated"] = result.get("env_updated")
            node.previous_proxy_json = json.dumps(prev)[:8000]
            node.status = "active"
            node.last_error = None
            node.last_seen_at = datetime.utcnow()
            proxy_service.clear_ssh_password(node)
            await db.commit()
            if node.agent_url:
                try:
                    await proxy_service.probe_agent(node)
                    await proxy_service.mark_seen(db, node, ok=True)
                except Exception as e:
                    await proxy_service.mark_seen(
                        db, node, ok=False, error=proxy_provision_service._format_exc(e)
                    )
    except Exception as e:
        logger.exception("proxy provision failed %s", node_id)
        err = proxy_provision_service._format_exc(e)
        async with AsyncSessionLocal() as db:
            node = await proxy_service.get_node(db, node_id)
            if node:
                node.status = "error"
                node.last_error = err
                await db.commit()


@router.get("/nodes")
async def list_nodes(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    nodes = await proxy_service.list_nodes(db)
    return {"nodes": [proxy_service.node_to_response(n) for n in nodes]}


@router.get("/nodes/active")
async def list_active(
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Healthy endpoints primary-прокси для сайтов/клиентов (с паролями — только admin)."""
    nodes = await proxy_service.list_nodes(db)
    active = [n for n in nodes if n.status in ("active", "degraded") and n.role == "dedicated"]
    active.sort(key=lambda n: (not n.is_primary, n.priority, n.name))
    return {
        "nodes": [proxy_service.node_to_response(n, include_secrets=True) for n in active],
    }


@router.post("/nodes/connect")
async def connect_node(
    req: ProxyNodeConnect,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """
    dedicated — поднять HTTP+SOCKS+MTProto на чистом proxy-VPS.
    attached — SSH на сайт, снести старый proxy, прописать env на primary (не Улей).
    """
    host = req.host.strip()
    role = (req.role or "attached").strip().lower()
    if role not in ("dedicated", "attached"):
        raise HTTPException(400, "role must be dedicated|attached")
    name = (req.name or "").strip() or await _next_name(db, role)
    node_id = uuid.uuid4()
    agent_secret = proxy_provision_service.generate_agent_secret()
    socks_user = (settings.PROXY_SOCKS_USER or "silent").strip() or "silent"
    socks_pass = proxy_provision_service.generate_socks_password()
    socks_port = int(req.prefer_socks_port or settings.PROXY_SOCKS_PORT or 1080)

    primary_payload = None
    if role == "attached":
        existing = await proxy_service.list_nodes(db)
        primary = next((n for n in existing if n.is_primary and n.status in ("active", "degraded", "provisioning")), None)
        if not primary:
            primary = next((n for n in existing if n.role == "dedicated" and n.status in ("active", "degraded")), None)
        if not primary:
            raise HTTPException(
                400,
                "Сначала подключите чистый proxy-VPS (тип dedicated). "
                "Сайты привязываются к нему, не к Улью.",
            )
        primary_payload = _primary_endpoint_dict(primary)
        if not primary_payload.get("http_url") and not primary_payload.get("socks_url"):
            raise HTTPException(400, "У primary нет HTTP/SOCKS endpoint — проверьте ноду")
        # attached не генерит свой socks — копируем отображение primary
        socks_user = primary.socks_user or socks_user
        socks_pass = proxy_service.socks_pass(primary) or socks_pass
        socks_port = int(primary.socks_port or socks_port)

    node = ProxyNode(
        id=node_id,
        name=name,
        role=role,
        public_ip=host,
        ssh_port=int(req.ssh_port or 22),
        socks_port=socks_port,
        socks_user=socks_user,
        agent_url=None,
        status="provisioning",
        is_primary=False,
        priority=100,
        last_seen_at=datetime.utcnow(),
    )
    existing = await proxy_service.list_nodes(db)
    if role == "dedicated" and not any(n.is_primary for n in existing):
        node.is_primary = True

    proxy_service.store_socks_pass(node, socks_pass)
    proxy_service.store_agent_secret(node, agent_secret)
    proxy_service.store_ssh_password(node, req.password)
    db.add(node)
    await db.commit()
    await db.refresh(node)

    asyncio.create_task(
        _provision_background(
            node_id,
            host,
            req.password,
            int(req.ssh_port or 22),
            role,
            socks_port,
            socks_user,
            socks_pass,
            agent_secret,
            primary_payload,
        )
    )
    resp = proxy_service.node_to_response(node)
    if role == "attached":
        resp["message"] = "Привязка сайта к primary-прокси запущена (старый proxy снимается, env → primary)"
    else:
        resp["message"] = "Установка HTTP+SOCKS5+MTProto на proxy-VPS запущена"
    return resp


@router.post("/nodes/{node_id}/probe")
async def probe_node(
    node_id: uuid.UUID,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    node = await proxy_service.get_node(db, node_id)
    if not node:
        raise HTTPException(404, "node not found")
    if node.role == "attached":
        return {
            "ok": True,
            "note": "Сайт-нода без agent — probe не нужен. Проверьте primary.",
            "node": proxy_service.node_to_response(node),
        }
    try:
        data = await proxy_service.probe_agent(node)
        await proxy_service.mark_seen(db, node, ok=True)
        return {"ok": True, "agent": data, "node": proxy_service.node_to_response(node)}
    except Exception as e:
        await proxy_service.mark_seen(db, node, ok=False, error=str(e))
        return {"ok": False, "error": str(e), "node": proxy_service.node_to_response(node)}


@router.patch("/nodes/{node_id}")
async def patch_node(
    node_id: uuid.UUID,
    req: ProxyNodePatch,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    node = await proxy_service.get_node(db, node_id)
    if not node:
        raise HTTPException(404, "node not found")
    if req.name is not None:
        node.name = req.name.strip()
    if req.status is not None:
        node.status = req.status.strip()
    if req.priority is not None:
        node.priority = req.priority
    if req.is_primary is not None:
        if req.is_primary:
            nodes = await proxy_service.list_nodes(db)
            for n in nodes:
                if n.id != node.id and n.is_primary:
                    n.is_primary = False
        node.is_primary = req.is_primary
    await db.commit()
    await db.refresh(node)
    return proxy_service.node_to_response(node)


@router.delete("/nodes/{node_id}")
async def delete_node(
    node_id: uuid.UUID,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Только запись в БД Улья — на VPS ничего не удаляет (сайт не трогаем)."""
    node = await proxy_service.get_node(db, node_id)
    if not node:
        raise HTTPException(404, "node not found")
    await db.delete(node)
    await db.commit()
    return {"ok": True}


@router.get("/nodes/{node_id}/endpoint")
async def node_endpoint(
    node_id: uuid.UUID,
    _: bool = Depends(get_admin_credentials),
    db: AsyncSession = Depends(get_db),
):
    node = await proxy_service.get_node(db, node_id)
    if not node:
        raise HTTPException(404, "node not found")
    data = proxy_service.node_to_response(node, include_secrets=True)
    # дополним HTTP/MTProto из meta primary
    if node.role == "dedicated" and node.previous_proxy_json:
        try:
            meta = json.loads(node.previous_proxy_json)
            if meta.get("http_url"):
                data["http_url"] = meta["http_url"]
            if meta.get("telegram_link"):
                data["telegram_link"] = meta["telegram_link"]
        except Exception:
            pass
    if node.role == "attached" and node.previous_proxy_json:
        try:
            meta = json.loads(node.previous_proxy_json)
            data["bound_to"] = meta.get("bound_to")
            data["http_url"] = meta.get("http_url")
        except Exception:
            pass
    return data
