from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.auth.security import get_current_user
from app.schemas.user import UserResponse, UsersListResponse

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=List[UserResponse])
async def get_all_users(
    is_admin: Optional[bool] = Query(default=None, description="Filter by admin status"),
    limit: int = Query(default=100, ge=1, le=500, description="Max number of users to return"),
    offset: int = Query(default=0, ge=0, description="Number of users to skip"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve all registered users with optional filtering and pagination.
    Requires authentication via X-API-Key header.
    """
    stmt = select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)

    if is_admin is not None:
        stmt = stmt.where(User.is_admin == is_admin)

    result = await db.execute(stmt)
    users = result.scalars().all()
    return users


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve profile details of the currently authenticated user.
    """
    return current_user


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_by_id(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve user details by user ID.
    """
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found",
        )
    return user
