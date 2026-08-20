from datetime import datetime
from uuid import UUID
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    id: UUID
    email: str
    is_admin: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UsersListResponse(BaseModel):
    users: List[UserResponse]
    total: int
