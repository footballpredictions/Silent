import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HiveLoadSample(Base):
    """Снимок нагрузки ноды Улья для расчёта адаптивной ёмкости."""

    __tablename__ = "hive_load_samples"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cell_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hive_cells.id", ondelete="CASCADE"),
        index=True,
    )
    sampled_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        index=True,
    )
    online_count: Mapped[int] = mapped_column(Integer, default=0)
    cpu_percent: Mapped[float] = mapped_column(Float, default=0.0)
    memory_percent: Mapped[float] = mapped_column(Float, default=0.0)
    network_mbps: Mapped[float] = mapped_column(Float, default=0.0)
    network_util_percent: Mapped[float] = mapped_column(Float, default=0.0)
    link_capacity_mbps: Mapped[float] = mapped_column(Float, default=1000.0)
    cpu_cores: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_total_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
