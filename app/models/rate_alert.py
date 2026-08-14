import uuid
from datetime import datetime
from sqlalchemy import String, Float, Boolean, DateTime, func, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class RateAlert(Base):
    __tablename__ = "rate_alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    trade_lane: Mapped[str] = mapped_column(String, nullable=False)
    alert_type: Mapped[str | None] = mapped_column(String, nullable=True)  # rate_spike|rate_drop|...
    message: Mapped[str] = mapped_column(String, nullable=False)
    magnitude_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        Index("idx_alerts_user_unread", "user_id", "is_read", "created_at"),
        Index("idx_alerts_type", "alert_type", "created_at"),
    )