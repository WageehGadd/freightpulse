from datetime import datetime
from uuid import UUID
from typing import Optional, Any
from pydantic import BaseModel, model_validator


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
    brief_id: UUID
    id: Optional[UUID] = None
    status: str
    brief_markdown: Optional[str] = None
    recommendation: Optional[str] = None
    risk_level: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def populate_ids(cls, data: Any) -> Any:
        if isinstance(data, dict):
            bid = data.get("brief_id") or data.get("id")
            if bid is not None:
                if "brief_id" not in data or data["brief_id"] is None:
                    data["brief_id"] = bid
                if "id" not in data or data["id"] is None:
                    data["id"] = bid
            return data
        elif hasattr(data, "id"):
            bid = getattr(data, "id")
            return {
                "brief_id": getattr(data, "brief_id", bid),
                "id": bid,
                "status": getattr(data, "status", None),
                "brief_markdown": getattr(data, "brief_markdown", None),
                "recommendation": getattr(data, "recommendation", None),
                "risk_level": getattr(data, "risk_level", None),
                "error_message": getattr(data, "error_message", None),
                "created_at": getattr(data, "created_at", None),
            }
        return data

    class Config:
        from_attributes = True


