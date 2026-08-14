import uuid
from datetime import date
from sqlalchemy import String, Numeric, Float, Boolean, Date, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class RateTrend(Base):
    __tablename__ = "rate_trends"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trade_lane: Mapped[str] = mapped_column(String, nullable=False)
    computed_date: Mapped[date] = mapped_column(Date, nullable=False)
    avg_7d_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    avg_30d_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    change_7d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_30d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend: Mapped[str | None] = mapped_column(String, nullable=True)  # rising|stable|falling
    slope_per_week: Mapped[float | None] = mapped_column(Float, nullable=True)
    anomaly_flag: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint(
            "trade_lane",
            "computed_date",
            name="uq_rate_trend",
        ),
        Index("idx_trends_lane_date", "trade_lane", "computed_date"),
    )