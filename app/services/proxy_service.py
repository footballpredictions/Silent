"""Сервис прокси-флота (отдельно от hive VPN)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import decrypt_value, encrypt_value
from app.models.proxy_node import ProxyNode

logger = logging.getLogger(__name__)


def store_socks_pass(node: ProxyNode, password: str) -> None:
    node.socks_pass_enc = encrypt_value(password)


def store_agent_secret(node: ProxyNode, secret: str) -> None:
    node.agent_secret_enc = encrypt_value(secret)


def store_ssh_password(node: ProxyNode, password: str) -> None:
    node.ssh_password_enc = encrypt_value(password)


def clear_ssh_password(node: ProxyNode) -> None:
    node.ssh_password_enc = None


def socks_pass(node: ProxyNode) -> str:
    if not node.socks_pass_enc:
        return ""
    return decrypt_value(node.socks_pass_enc)


def agent_secret(node: ProxyNode) -> str:
    if not node.agent_secret_enc:
        return ""
    return decrypt_value(node.agent_secret_enc)


def node_to_response(node: ProxyNode, *, include_secrets: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(node.id),
        "name": node.name,
        "role": node.role,
        "public_ip": node.public_ip,
        "ssh_port": node.ssh_port,
        "socks_port": node.socks_port,
        "socks_user": node.socks_user,
        "agent_url": node.agent_url,
        "status": node.status,
        "is_primary": node.is_primary,
        "priority": node.priority,
        "last_seen_at": node.last_seen_at.isoformat() if node.last_seen_at else None,
        "last_error": node.last_error,
        "created_at": node.created_at.isoformat() if node.created_at else None,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
        "endpoint": None,
    }
    if node.status in ("active", "degraded") and node.public_ip and node.socks_user:
        host = node.public_ip
        port = node.socks_port
        user = node.socks_user
        if include_secrets:
            pwd = socks_pass(node)
            data["socks_password"] = pwd
            data["endpoint"] = f"socks5://{user}:{pwd}@{host}:{port}"
        else:
            data["endpoint"] = f"socks5://{user}:***@{host}:{port}"
    return data


async def list_nodes(db: AsyncSession) -> list[ProxyNode]:
    r = await db.execute(select(ProxyNode).order_by(ProxyNode.is_primary.desc(), ProxyNode.priority, ProxyNode.created_at))
    return list(r.scalars().all())


async def get_node(db: AsyncSession, node_id: uuid.UUID) -> ProxyNode | None:
    return await db.get(ProxyNode, node_id)


async def probe_agent(node: ProxyNode) -> dict[str, Any]:
    url = (node.agent_url or "").rstrip("/")
    if not url:
        raise ValueError("agent_url пуст")
    secret = agent_secret(node)
    timeout = settings.PROXY_AGENT_HTTP_TIMEOUT_SEC
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(f"{url}/v1/status", headers={"X-Proxy-Agent-Secret": secret})
        r.raise_for_status()
        return r.json()


async def mark_seen(db: AsyncSession, node: ProxyNode, *, ok: bool, error: str | None = None) -> None:
    node.last_seen_at = datetime.utcnow()
    if ok:
        if node.status in ("provisioning", "pending", "error", "degraded", "blocked"):
            node.status = "active"
        node.last_error = None
    else:
        node.last_error = (error or "probe failed")[:2000]
        if node.status == "active":
            node.status = "degraded"
    await db.commit()
