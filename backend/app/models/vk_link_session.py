import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, BigInteger, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class VkLinkSession(Base):
    __tablename__ = "vk_link_sessions"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    vk_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bootstrap_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
