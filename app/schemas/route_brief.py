from datetime import datetime
from uuid import UUID
from typing import Optional
from pydantic import BaseModel


class RouteBriefCreateRequest(BaseModel):
    origin: str
    destination: str
    carrier: Optional[str] = None
    cargo_type: Optional[str] = "40ft"


class RouteBriefResponse(BaseModel):
    id: UUID
    user_id: UUID
    origin: str
    destination: str
    carrier: Optional[str] = None
    cargo_type: str = "40ft"
    brief_markdown: Optional[str] = None
    recommendation: Optional[str] = None
    risk_level: Optional[str] = None
    pdf_path: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RouteBriefStatusResponse(BaseModel):
    id: UUID
    status: str
    error_message: Optional[str] = None
