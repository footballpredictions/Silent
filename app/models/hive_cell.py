import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Boolean, Integer, Float, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class HiveCell(Base):
    """VPN-нода «сота» в кластере «Улей». Улей (queen) — is_queen=True."""

    __tablename__ = "hive_cells"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_queen: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Публичный IP/хост для клиентов (WDTT)
    public_ip: Mapped[str] = mapped_column(String(255), nullable=False)
    wdtt_port: Mapped[int] = mapped_column(Integer, default=56000)
    wg_port: Mapped[int] = mapped_column(Integer, default=56001)
    wg_public_key: Mapped[str] = mapped_column(Text, default="")
    # Cell-agent (опционально): URL и зашифрованный пароль для handshake
    api_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SSH root для provision / обновления cell-agent (Fernet)
    ssh_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Tunnel API на соте (если проксирует на улей) — для документации/health
    tunnel_api_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    max_clients: Mapped[int] = mapped_column(Integer, default=0)
    # NULL / 0 = авто (1 Гбит, первая сота — 10 Гбит); иначе явное значение в Мбит/с
    link_capacity_mbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    # pending | active | draining | offline | error
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    # False: сота под olcrtc2 (Сота 1/2) — WDTT-баланс на неё не льём.
    accepts_wdtt: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    devices: Mapped[list["Device"]] = relationship(back_populates="cell")
