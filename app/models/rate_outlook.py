"""Grounded narration artifact. Legacy RateTrend AI fields are not authoritative."""
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class RateOutlook(Base):
    __tablename__ = "rate_outlooks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trend_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rate_trends.id"), nullable=False)
    forecast_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rate_forecasts.id"), nullable=False)
    forecast_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    # T06 upserts mutate an artifact in place: linkage alone cannot preserve evidence.
    evidence_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", server_default="pending")
    outlook_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failure_code: Mapped[str | None] = mapped_column(String, nullable=True)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Actual context sent to Azure; retained separately from read-time current state.
    narration_input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("trend_id", "forecast_id", "forecast_generated_at", "prompt_version", name="uq_rate_outlook_generation"),
        Index("idx_outlook_trend", "trend_id"),
        Index("idx_outlook_forecast", "forecast_id"),
    )
