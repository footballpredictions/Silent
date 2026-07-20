"""Admin MFA: trusted devices (like user devices), server-side sessions."""
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, ForeignKey, Text, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AdminTrustedDevice(Base):
    __tablename__ = "admin_trusted_devices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Stable browser id from localStorage (like users.device_fingerprint)
    device_fingerprint: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True, index=True)
    # phone | pc | tablet
    device_type: Mapped[str] = mapped_column(String(32), nullable=False, default="pc")
    # Display: «Телефон», «ПК», or model name
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    user_agent: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sessions: Mapped[list["AdminSession"]] = relationship(back_populates="device", lazy="select")


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_trusted_devices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    token_jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_agent: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    client_platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_mobile: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    device_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    device: Mapped[AdminTrustedDevice | None] = relationship(back_populates="sessions", lazy="select")


class AdminMfaChallenge(Base):
    __tablename__ = "admin_mfa_challenges"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    remember_device: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # JSON: fingerprint, device_type, device_name, platform, mobile
    meta: Mapped[str | None] = mapped_column(Text, nullable=True)
