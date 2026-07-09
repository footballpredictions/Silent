import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, BigInteger, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_test_user: Mapped[bool] = mapped_column(Boolean, default=False)
    test_mode_personal: Mapped[bool] = mapped_column(Boolean, default=False)
    test_mode_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reset_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vk_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    vk_linked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    vk_config_published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bootstrap_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    referral_code: Mapped[str | None] = mapped_column(String(16), unique=True, nullable=True, index=True)
    referred_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    pending_promo_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="user", lazy="select")
    devices: Mapped[list["Device"]] = relationship(back_populates="user", lazy="select")
    payments: Mapped[list["Payment"]] = relationship(back_populates="user", lazy="select")

    @property
    def display_id(self) -> str:
        return str(self.id)[:8].upper()
