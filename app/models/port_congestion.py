import uuid
from datetime import datetime
from sqlalchemy import String, Float, Integer, DateTime, func, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PortCongestion(Base):
    __tablename__ = "port_congestion"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    port_code: Mapped[str] = mapped_column(String, nullable=False)  # 'EGPSD' | 'AEJEA' | 'CNSHA'
    port_name: Mapped[str] = mapped_column(String, nullable=False)
    congestion_index: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-100
    avg_dwell_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    vessels_waiting: Mapped[int | None] = mapped_column(Integer, nullable=True)
    advisory_text: Mapped[str | None] = mapped_column(String, nullable=True)
    severity: Mapped[str | None] = mapped_column(String, nullable=True)  # normal|elevated|critical
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        Index("idx_port_code_time", "port_code", "measured_at"),
    )