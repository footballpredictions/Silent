"""Пул комнат olcrtc (вариант 2) — N rooms / N srv, placement на Улей/соты."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OlcrtcRoom(Base):
    __tablename__ = "olcrtc_rooms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    room_url: Mapped[str] = mapped_column(String(512), nullable=False)
    slot_label: Mapped[str] = mapped_column(String(64), nullable=False, default="pc", index=True)
    # JSON-ish list stored as postgres ARRAY; fallback Text in migrate
    device_types: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    cell_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hive_cells.id", ondelete="SET NULL"), nullable=True, index=True
    )
    unit_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    data_dir: Mapped[str] = mapped_column(String(128), nullable=False, default="data")
    # active | draining | offline | provisioning | error
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    max_clients: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    online_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_healthy_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class OlcrtcRoomSticky(Base):
    """Sticky fingerprint → room (как device.cell_id для WDTT)."""

    __tablename__ = "olcrtc_room_sticky"
    __table_args__ = (
        UniqueConstraint(
            "fingerprint", "provider", "device_type", name="uq_olcrtc_sticky_fp_prov_dt"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    device_type: Mapped[str] = mapped_column(String(32), nullable=False, default="pc")
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("olcrtc_rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
