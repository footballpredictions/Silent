import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, func, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    plan_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    wallet: Mapped[str] = mapped_column(String(50), nullable=False)
    yumoney_label: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, completed, failed, expired
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # YuMoney operation_id — уникален для идемпотентности повторных нотификаций
    operation_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    # Фактически зачисленная сумма (withdraw_amount/amount из нотификации) — для аудита комиссии
    paid_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Промокод, применённый на момент создания платёжного намерения (use_count инкрементится при завершении)
    promo_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Код для поддержки в письме (если подписка не активировалась после оплаты)
    support_code: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True, index=True)
    # True после успешной авто/ручной выдачи подписки по этому платежу
    subscription_applied: Mapped[bool] = mapped_column(default=False)
    manual_activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="payments")


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    discount_percent: Mapped[int] = mapped_column(default=0)
    extra_days: Mapped[int] = mapped_column(default=0)
    max_uses: Mapped[int] = mapped_column(default=1)
    use_count: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
