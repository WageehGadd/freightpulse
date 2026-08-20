"""SQLAlchemy database setup, session management, and ORM models for FreightPulse AI.

Tables:
- freight_rates : raw scraped rates (source of truth, owned by Backend scrapers)
- rate_trends   : AI-1 daily computed trends (upserted per lane per day)
- rate_alerts   : AI-2 anomaly alerts with multi-day event tracking (P3 #3)
"""
import os
import uuid
from datetime import date, datetime
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    create_engine,
    func,
    Index
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker, Mapped, mapped_column

load_dotenv()

raw_url = os.getenv("AI_DATABASE_URL")
if not raw_url:
    raw_url = os.getenv("DATABASE_URL", "sqlite:///./freightpulse.db")
    if raw_url.startswith("postgresql+asyncpg://"):
        raw_url = raw_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

DATABASE_URL = raw_url

engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()



class FreightRate(Base):
    """Raw daily freight rates per trade lane (scraped by Backend)."""

    __tablename__ = "freight_rates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String, nullable=False)  # 'SCFI' | 'FBX'
    trade_lane: Mapped[str] = mapped_column(String, nullable=False)
    origin_port: Mapped[str] = mapped_column(String, nullable=False)
    dest_region: Mapped[str] = mapped_column(String, nullable=False)
    container_type: Mapped[str] = mapped_column(String, nullable=False)  # '20ft' | '40ft'
    rate_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    week_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "source",
            "trade_lane",
            "container_type",
            "rate_date",
            name="uq_freight_rate",
        ),
        Index("idx_rates_lane", "trade_lane", "rate_date"),
        Index("idx_rates_date", "rate_date"),
        Index("idx_rates_source", "source", "rate_date"),
    )


class RateTrend(Base):
    """AI-1 output: daily computed trend per trade lane."""

    __tablename__ = "rate_trends"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trade_lane: Mapped[str] = mapped_column(String, nullable=False)
    computed_date: Mapped[date] = mapped_column(Date, nullable=False)
    avg_7d_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    avg_30d_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    change_7d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_30d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend: Mapped[str | None] = mapped_column(String, nullable=True)  # rising|stable|falling
    slope_per_week: Mapped[float | None] = mapped_column(Float, nullable=True)
    anomaly_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # --- AI specific fields for analysis (requires backend migration later) ---
    r_squared: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "trade_lane",
            "computed_date",
            name="uq_rate_trend",
        ),
        Index("idx_trends_lane_date", "trade_lane", "computed_date"),
    )


class RateAlert(Base):
    """AI-2 output: anomaly alerts with multi-day event tracking."""

    __tablename__ = "rate_alerts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    trade_lane: Mapped[str] = mapped_column(String, nullable=False)
    alert_type: Mapped[str | None] = mapped_column(String, nullable=True)  # rate_spike|rate_drop|...
    message: Mapped[str] = mapped_column(String, nullable=False)
    magnitude_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- AI specific fields for multi-day anomaly tracking (requires backend migration later) ---
    direction: Mapped[str | None] = mapped_column(String, nullable=True)
    z_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_30d: Mapped[float | None] = mapped_column(Float, nullable=True)
    pattern_type: Mapped[str] = mapped_column(String, default="one_day", nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cumulative_magnitude_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_alerts_user_unread", "user_id", "is_read", "created_at"),
        Index("idx_alerts_type", "alert_type", "created_at"),
    )


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield a DB session and ensure it is closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Dev convenience."""
    Base.metadata.create_all(bind=engine)