"""olcrtc 2.0 rooms — session-mode (1 fingerprint = 1 room), exit on Hive cell only."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Olcrtc2Room(Base):
    __tablename__ = "olcrtc2_rooms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # telemost|wbstream
    room_url: Mapped[str] = mapped_column(String(512), nullable=False)
    crypto_key: Mapped[str] = mapped_column(String(64), nullable=False)
    slot_label: Mapped[str] = mapped_column(String(64), nullable=False, default="pc", index=True)
    device_type: Mapped[str] = mapped_column(String(32), nullable=False, default="pc", index=True)
    cell_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hive_cells.id", ondelete="SET NULL"), nullable=True, index=True
    )
    unit_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # active | draining | offline | provisioning | error
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="provisioning", index=True)
    max_clients: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    online_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_healthy_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_token: Mapped[str | None] = mapped_column(Text, nullable=True)  # WB JWT if any
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Olcrtc2Sticky(Base):
    __tablename__ = "olcrtc2_sticky"
    __table_args__ = (
        UniqueConstraint(
            "fingerprint", "provider", "device_type", name="uq_olcrtc2_sticky_fp_prov_dt"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    device_type: Mapped[str] = mapped_column(String(32), nullable=False, default="pc")
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("olcrtc2_rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
