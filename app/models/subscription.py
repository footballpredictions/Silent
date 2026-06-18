import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, func, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    plan_type: Mapped[str] = mapped_column(String(50), nullable=False)  # monthly, quarterly, yearly
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")  # active, expired, cancelled
    amount_paid: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    promo_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="subscriptions")

    @property
    def is_active(self) -> bool:
        return self.status == "active" and self.expires_at > datetime.utcnow()

    @property
    def days_left(self) -> int:
        if not self.is_active:
            return 0
        delta = self.expires_at - datetime.utcnow()
        return max(0, delta.days)
