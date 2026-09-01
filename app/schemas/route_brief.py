from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RouteBriefCreateRequest(BaseModel):
    origin: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=1, max_length=100)
    carrier: str = Field(min_length=1, max_length=100)
    cargo_type: str = Field(min_length=1, max_length=100)


class RouteBriefCreateResponse(BaseModel):
    id: str
    status: Literal["pending", "generating", "completed", "failed"]


class RouteBriefResponse(BaseModel):
    id: str
    origin: str
    destination: str
    carrier: str | None
    cargo_type: str
    status: Literal["pending", "generating", "completed", "failed"]
    brief_markdown: str | None
    recommendation: str | None
    risk_level: str | None
    error_message: str | None
    created_at: datetime | None
    pdf_available: bool
