import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, Float, Index, Integer,
    Numeric, String, Text, UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RateForecast(Base):
    """
    Persisted baseline forecast artifact produced by the T04 engine.

    A forecast is NEVER just a number. Every row captures:
      - SERIES IDENTITY:    source / trade_lane / container_type
      - FORECAST:           forecast_for_date + predicted_rate + model_name + horizon
      - INPUT PROVENANCE:   latest_observation_date + latest_actual_rate + history_observations
      - BACKTEST EVIDENCE:  evaluation_points + MAE + RMSE + sMAPE + directional_accuracy
      - DATA QUALITY:       data_readiness
      - FRESHNESS:          input_freshness (derived from source observation, NOT generated_at)
      - SAFETY:             live_decision_eligible + warning

    Idempotency policy:
      Unique on (source, trade_lane, container_type, latest_observation_date, forecast_for_date, model_name, model_version).
      When the same source evidence is re-run, the row is upserted (updated in place) rather than duplicated.
      When a NEW source observation arrives (new latest_observation_date), a NEW row is inserted,
      preserving historical auditability across observation epochs.
    """
    __tablename__ = "rate_forecasts"

    # ── Identity ─────────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source: Mapped[str] = mapped_column(String, nullable=False)          # e.g. 'SCFI'
    trade_lane: Mapped[str] = mapped_column(String, nullable=False)      # e.g. 'Egypt-China'
    container_type: Mapped[str] = mapped_column(String, nullable=False)  # '20ft' | '40ft'

    # ── Forecast ─────────────────────────────────────────────────────────────
    forecast_for_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Numeric(12, 2): same cent scale, wider range than FreightRate Numeric(10, 2)
    predicted_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)      # e.g. 'MA(3)', 'MA(4)'
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    forecast_horizon: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # ── Input Provenance ─────────────────────────────────────────────────────
    latest_observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    latest_actual_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    history_observations: Mapped[int] = mapped_column(Integer, nullable=False)

    # ── Backtest Evidence Snapshot ────────────────────────────────────────────
    # Captured at generation time — must NOT be recomputed from future data.
    evaluation_points: Mapped[int] = mapped_column(Integer, nullable=False)
    backtest_mae: Mapped[float] = mapped_column(Float, nullable=False)
    backtest_rmse: Mapped[float] = mapped_column(Float, nullable=False)
    backtest_smape: Mapped[float] = mapped_column(Float, nullable=False)
    backtest_directional_accuracy: Mapped[float] = mapped_column(Float, nullable=False)

    # ── Data Quality ─────────────────────────────────────────────────────────
    data_readiness: Mapped[str] = mapped_column(String, nullable=False)  # 'MINIMAL' etc.

    # ── Freshness & Safety ────────────────────────────────────────────────────
    # input_freshness is derived from the SOURCE OBSERVATION DATE, not generated_at.
    # Regenerating a forecast today from stale source data must NOT become 'fresh'.
    input_freshness: Mapped[str] = mapped_column(String, nullable=False)   # 'fresh' | 'aging' | 'stale'
    live_decision_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Audit ─────────────────────────────────────────────────────────────────
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Constraints & Indexes ─────────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint(
            "source", "trade_lane", "container_type",
            "latest_observation_date", "forecast_for_date", "model_name", "model_version",
            name="uq_rate_forecast_epoch"
        ),
        Index("idx_forecast_series", "source", "trade_lane", "container_type"),
        Index("idx_forecast_obs_date", "latest_observation_date"),
        Index("idx_forecast_for_date", "forecast_for_date"),
    )
