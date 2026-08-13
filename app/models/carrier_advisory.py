import uuid
from datetime import date, datetime
from sqlalchemy import String, DateTime, Date, ARRAY, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class CarrierAdvisory(Base):
    __tablename__ = "carrier_advisories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    carrier: Mapped[str] = mapped_column(String, nullable=False)  # MSC | Maersk | CMACGM
    advisory_type: Mapped[str] = mapped_column(String, nullable=False)  # surcharge|route_suspension|...
    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    affected_lanes: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())