import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BunkerRate(Base):
    __tablename__ = "bunker_rates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    port_name: Mapped[str] = mapped_column(String, nullable=False)
    fuel_type: Mapped[str] = mapped_column(String, nullable=False)
    price_usd: Mapped[float] = mapped_column(Float, nullable=False)
    observed_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("port_name", "fuel_type", "observed_date", name="uq_bunker_rate"),
        Index("idx_bunker_rates_date", "observed_date"),
        Index("idx_bunker_rates_port", "port_name"),
    )
