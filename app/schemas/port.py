from datetime import datetime

from pydantic import BaseModel


class PortCongestionResponse(BaseModel):
    port_code: str
    port_name: str
    congestion_index: float | None
    avg_dwell_days: float | None
    vessels_waiting: int | None
    severity: str | None
    advisory_text: str | None
    measured_at: datetime


class PortMapEntry(BaseModel):
    port_code: str
    port_name: str
    latitude: float | None
    longitude: float | None
    congestion_index: float | None
    severity: str | None


class PortCongestionMapResponse(BaseModel):
    ports: list[PortMapEntry]