"""Модель ноды SOCKS/прокси-флота (отдельно от VPN-сот Улья)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProxyNode(Base):
    __tablename__ = "proxy_nodes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # dedicated = чистый proxy-VPS; attached = VPS с другими сервисами — safe provision
    role: Mapped[str] = mapped_column(String(32), default="dedicated", index=True)
    public_ip: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    socks_port: Mapped[int] = mapped_column(Integer, default=1080)
    socks_user: Mapped[str] = mapped_column(String(128), default="")
    socks_pass_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    agent_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SSH пароль только на время provision; после success можно очистить
    ssh_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending|provisioning|active|degraded|blocked|error|draining
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON snapshot обнаруженного старого прокси (порт/юзер) — для cutover
    previous_proxy_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
