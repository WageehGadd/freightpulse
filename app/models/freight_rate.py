import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FreightRate(Base):
    __tablename__ = "freight_rates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
        UniqueConstraint("source", "trade_lane", "container_type", "rate_date", name="uq_freight_rate"),
    )