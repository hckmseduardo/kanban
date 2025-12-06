"""User routes"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.auth.jwt import get_current_user
from app.services.database_service import db_service

logger = logging.getLogger(__name__)
router = APIRouter()


# Request/Response models
class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: Optional[str] = None
    created_at: str
    last_login_at: Optional[str] = None


class TeamSummary(BaseModel):
    id: str
    slug: str
    name: str
    role: str
    status: str


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: dict = Depends(get_current_user)
):
    """Get current user's profile"""
    return UserResponse(
        id=current_user["id"],
        email=current_user["email"],
        display_name=current_user["display_name"],
        avatar_url=current_user.get("avatar_url"),
        created_at=current_user["created_at"],
        last_login_at=current_user.get("last_login_at")
    )


@router.put("/me", response_model=UserResponse)
async def update_current_user_profile(
    updates: UserUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    """Update current user's profile"""
    update_data = updates.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=400, detail="No updates provided")

    updated_user = db_service.update_user(current_user["id"], update_data)

    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserResponse(
        id=updated_user["id"],
        email=updated_user["email"],
        display_name=updated_user["display_name"],
        avatar_url=updated_user.get("avatar_url"),
        created_at=updated_user["created_at"],
        last_login_at=updated_user.get("last_login_at")
    )


@router.get("/me/teams", response_model=list[TeamSummary])
async def get_current_user_teams(
    current_user: dict = Depends(get_current_user)
):
    """Get all teams the current user belongs to"""
    teams = db_service.get_user_teams(current_user["id"])

    return [
        TeamSummary(
            id=team["id"],
            slug=team["slug"],
            name=team["name"],
            role=team.get("role", "member"),
            status=team.get("status", "active")
        )
        for team in teams
    ]
