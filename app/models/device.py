import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Boolean, func, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    device_type: Mapped[str] = mapped_column(String(50), nullable=False)  # android, ios, pc
    device_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    wg_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    wg_private_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    wg_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    wdtt_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    last_connected: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    cell_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hive_cells.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="devices")
    cell: Mapped["HiveCell | None"] = relationship(back_populates="devices")
