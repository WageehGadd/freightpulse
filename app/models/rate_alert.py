import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Numeric, String, UniqueConstraint, func, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RateAlertRule(Base):
    __tablename__ = "rate_alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    trade_lane: Mapped[str] = mapped_column(String, nullable=False)
    alert_type: Mapped[str] = mapped_column(String, nullable=False)
    magnitude_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_rules_user_active", "user_id", "is_active"),
        Index("idx_alert_rules_lane", "trade_lane"),
    )


class RateAlert(Base):
    __tablename__ = "rate_alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rate_alert_rules.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    trade_lane: Mapped[str] = mapped_column(String, nullable=False)
    alert_type: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str] = mapped_column(String, nullable=False)
    magnitude_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    evaluation_date: Mapped[date] = mapped_column(Date, nullable=False)
    
    direction: Mapped[str | None] = mapped_column(String, nullable=True)
    z_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_30d: Mapped[float | None] = mapped_column(Float, nullable=True)
    pattern_type: Mapped[str] = mapped_column(String, default="one_day", nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cumulative_magnitude_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("rule_id", "evaluation_date", name="uq_alert_rule_eval_date"),
        Index("idx_alerts_type", "alert_type", "created_at"),
        Index("idx_alerts_user_unread", "user_id", "is_read", "created_at"),
    )