import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, func, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class VkHash(Base):
    """VK Call hash managed by AI assistant for VPN tunnels."""
    __tablename__ = "vk_hashes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    hash_value: Mapped[str] = mapped_column(String(255), nullable=False)
    call_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 0, 1, 2 (up to 3 hashes)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_failed: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class VkCredentials(Base):
    """Encrypted VK account credentials for AI assistant."""
    __tablename__ = "vk_credentials"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    login_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_configured: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AppSetting(Base):
    """Key-value store for app settings (theme, config, etc.)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
