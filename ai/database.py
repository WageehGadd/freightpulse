"""SQLAlchemy database setup, session management, and ORM models for FreightPulse AI.

Tables:
- freight_rates : raw scraped rates (source of truth, owned by Backend scrapers)
- rate_trends   : AI-1 daily computed trends (upserted per lane per day)
- rate_alerts   : AI-2 anomaly alerts with multi-day event tracking (P3 #3)
"""
import os
from datetime import datetime
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./freightpulse.db")

engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class FreightRate(Base):
    """Raw daily freight rates per trade lane (scraped by Backend)."""

    __tablename__ = "freight_rates"

    id = Column(Integer, primary_key=True, index=True)
    trade_lane = Column(String, index=True, nullable=False)
    rate_date = Column(Date, index=True, nullable=False)
    rate_usd = Column(Float, nullable=False)


class RateTrend(Base):
    """AI-1 output: daily computed trend per trade lane."""

    __tablename__ = "rate_trends"

    id = Column(Integer, primary_key=True, index=True)
    trade_lane = Column(String, index=True, nullable=False)
    computed_date = Column(Date, index=True, nullable=False)
    avg_7d_usd = Column(Float, nullable=False)
    avg_30d_usd = Column(Float, nullable=False)
    change_7d_pct = Column(Float)
    change_30d_pct = Column(Float)
    trend = Column(String, nullable=False)  # rising | stable | falling | insufficient_data
    slope_per_week = Column(Float)
    r_squared = Column(Float)
    anomaly_flag = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("trade_lane", "computed_date", name="uq_rate_trends_lane_date"),
    )


class RateAlert(Base):
    """AI-2 output: anomaly alerts with multi-day event tracking.

    P3 Enhancement #3: sustained movements (same-direction anomalies on
    consecutive days) are tracked as ONE event — the alert row is extended
    (duration_days, cumulative_magnitude_pct) instead of creating new alerts.
    """

    __tablename__ = "rate_alerts"

    id = Column(Integer, primary_key=True, index=True)
    trade_lane = Column(String, index=True, nullable=False)
    alert_type = Column(String, nullable=False)  # rate_spike | rate_drop
    message = Column(Text, nullable=False)
    magnitude_pct = Column(Float)          # latest day's move
    direction = Column(String)             # up | down
    z_score = Column(Float)
    latest_rate = Column(Float)
    mean_30d = Column(Float)
    is_read = Column(Boolean, default=False, nullable=False)
    # --- P3 Enhancement #3: multi-day event tracking ---
    pattern_type = Column(String, default="one_day", nullable=False)  # one_day | sustained
    duration_days = Column(Integer, default=1, nullable=False)
    cumulative_magnitude_pct = Column(Float)   # total move since event start
    last_event_date = Column(Date)             # date of the latest contributing day
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield a DB session and ensure it is closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Dev convenience — use Alembic migrations in prod."""
    Base.metadata.create_all(bind=engine)