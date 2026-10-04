"""Separate append-only evaluation evidence; no RateForecast foreign key."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import (String, Integer, Date, DateTime, Numeric, Float, Boolean,
    ForeignKey, UniqueConstraint, Index, CheckConstraint, event, func, text)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class EvaluationRun(Base):
    __tablename__ = 'forecast_evaluation_runs'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String, nullable=False)
    trade_lane: Mapped[str] = mapped_column(String, nullable=False)
    container_type: Mapped[str] = mapped_column(String, nullable=False)
    dataset_cutoff: Mapped[date | None] = mapped_column(Date, nullable=True)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dataset_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_version: Mapped[str] = mapped_column(String, nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    initial_train_size: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_inner_evaluation_points: Mapped[int] = mapped_column(Integer, nullable=False)
    forecast_horizon: Mapped[int] = mapped_column(Integer, nullable=False)
    selection_evaluation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    outer_evaluation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    final_champion: Mapped[str | None] = mapped_column(String, nullable=True)
    selection_status: Mapped[str] = mapped_column(String, nullable=False)
    outer_status: Mapped[str] = mapped_column(String, nullable=False)
    winner_switch_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provenance: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint('source', 'trade_lane', 'container_type', 'dataset_fingerprint',
            'evaluation_version', 'configuration_fingerprint', name='uq_evaluation_identity'),
        Index('idx_evaluation_series_cutoff', 'source', 'trade_lane', 'container_type', 'dataset_cutoff'),
    )


class EvaluationObservation(Base):
    __tablename__ = 'forecast_evaluation_observations'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('forecast_evaluation_runs.id', ondelete='CASCADE'), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    __table_args__ = (
        UniqueConstraint('run_id', 'ordinal', name='uq_evaluation_observation_ordinal'),
        UniqueConstraint('run_id', 'observation_date', name='uq_evaluation_observation_date'),
        CheckConstraint("rate::text NOT IN ('NaN', 'Infinity', '-Infinity')", name='ck_evaluation_rate_finite'),
    )


class EvaluationPoint(Base):
    __tablename__ = 'forecast_evaluation_points'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('forecast_evaluation_runs.id', ondelete='CASCADE'), nullable=False)
    protocol_phase: Mapped[str] = mapped_column(String, nullable=False)
    target_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    candidate_name: Mapped[str] = mapped_column(String, nullable=False)
    training_observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    inner_evaluation_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_actual: Mapped[float] = mapped_column(Float(53), nullable=False)
    actual: Mapped[float] = mapped_column(Float(53), nullable=False)
    prediction: Mapped[float] = mapped_column(Float(53), nullable=False)
    signed_residual: Mapped[float] = mapped_column(Float(53), nullable=False)
    absolute_error: Mapped[float] = mapped_column(Float(53), nullable=False)
    squared_error: Mapped[float] = mapped_column(Float(53), nullable=False)
    smape_component: Mapped[float] = mapped_column(Float(53), nullable=False)
    predicted_direction: Mapped[str] = mapped_column(String, nullable=False)
    actual_direction: Mapped[str] = mapped_column(String, nullable=False)
    direction_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    direction_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    __table_args__ = (
        UniqueConstraint('run_id', 'protocol_phase', 'target_ordinal', 'candidate_name', name='uq_evaluation_point'),
        Index('uq_evaluation_outer_target', 'run_id', 'target_ordinal', unique=True,
            postgresql_where=text("protocol_phase = 'NESTED_OUTER'")),
        CheckConstraint("protocol_phase IN ('SELECTION_WINDOW', 'NESTED_OUTER')", name='ck_evaluation_phase'),
        CheckConstraint(' AND '.join(f"{n}::text NOT IN ('NaN', 'Infinity', '-Infinity')" for n in (
            'previous_actual', 'actual', 'prediction', 'signed_residual', 'absolute_error', 'squared_error', 'smape_component')),
            name='ck_evaluation_point_finite'),
    )


def _immutable(mapper, connection, target):
    raise ValueError('Completed evaluation evidence is append-only')


for _model in (EvaluationRun, EvaluationObservation, EvaluationPoint):
    event.listen(_model, 'before_update', _immutable)
    event.listen(_model, 'before_delete', _immutable)
