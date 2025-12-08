"""Team management routes"""

import logging
import re
import uuid
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from app.auth.jwt import get_current_user
from app.config import settings
from app.services.database_service import db_service
from app.services.task_service import task_service

logger = logging.getLogger(__name__)


def get_team_subdomain(slug: str) -> str:
    """Generate team subdomain URL with port if not 443"""
    if settings.port == 443:
        return f"https://{slug}.{settings.domain}"
    return f"https://{slug}.{settings.domain}:{settings.port}"


router = APIRouter()


# Request/Response models
class TeamCreateRequest(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        slug = v.lower().strip()
        if not re.match(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", slug):
            raise ValueError(
                "Slug must be 3-63 characters, lowercase alphanumeric and hyphens, "
                "start and end with alphanumeric"
            )
        # Reserved slugs
        reserved = ["app", "api", "www", "mail", "admin", "portal", "static", "assets"]
        if slug in reserved:
            raise ValueError(f"Slug '{slug}' is reserved")
        return slug


class TeamUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None


class TeamResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    owner_id: str
    status: str
    subdomain: str
    created_at: str
    provisioned_at: Optional[str] = None


class TeamMemberResponse(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: Optional[str] = None
    role: str
    joined_at: str


class AddMemberRequest(BaseModel):
    email: str
    role: str = "member"


# Routes
@router.post("", response_model=dict)
async def create_team(
    request: TeamCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new team.
    This starts an async provisioning process.
    """
    # Check if slug is available
    existing = db_service.get_team_by_slug(request.slug)
    if existing:
        raise HTTPException(status_code=409, detail="Team slug already exists")

    # Create team record
    team_id = str(uuid.uuid4())
    team_data = {
        "id": team_id,
        "slug": request.slug,
        "name": request.name,
        "description": request.description,
        "owner_id": current_user["id"],
        "subdomain": get_team_subdomain(request.slug)
    }

    team = db_service.create_team(team_data)

    # Add creator as owner
    db_service.add_team_member(
        team_id=team_id,
        user_id=current_user["id"],
        role="owner"
    )

    # Start provisioning task
    task_id = await task_service.create_team_provision_task(
        team_id=team_id,
        team_slug=request.slug,
        owner_id=current_user["id"]
    )

    logger.info(f"Team {request.slug} creation started, task: {task_id}")

    return {
        "team": TeamResponse(
            id=team["id"],
            slug=team["slug"],
            name=team["name"],
            description=team.get("description"),
            avatar_url=team.get("avatar_url"),
            owner_id=team["owner_id"],
            status=team["status"],
            subdomain=team["subdomain"],
            created_at=team["created_at"],
            provisioned_at=team.get("provisioned_at")
        ),
        "task_id": task_id,
        "message": "Team provisioning started. You will be notified when it's ready."
    }


@router.get("", response_model=List[TeamResponse])
async def list_teams(
    current_user: dict = Depends(get_current_user)
):
    """Get all teams for current user"""
    teams = db_service.get_user_teams(current_user["id"])

    return [
        TeamResponse(
            id=team["id"],
            slug=team["slug"],
            name=team["name"],
            description=team.get("description"),
            avatar_url=team.get("avatar_url"),
            owner_id=team["owner_id"],
            status=team.get("status", "active"),
            subdomain=team.get("subdomain", get_team_subdomain(team['slug'])),
            created_at=team["created_at"],
            provisioned_at=team.get("provisioned_at")
        )
        for team in teams
    ]


@router.get("/{slug}", response_model=TeamResponse)
async def get_team(
    slug: str,
    current_user: dict = Depends(get_current_user)
):
    """Get team by slug"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check membership
    membership = db_service.get_membership(team["id"], current_user["id"])
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this team")

    return TeamResponse(
        id=team["id"],
        slug=team["slug"],
        name=team["name"],
        description=team.get("description"),
        avatar_url=team.get("avatar_url"),
        owner_id=team["owner_id"],
        status=team.get("status", "active"),
        subdomain=team.get("subdomain", get_team_subdomain(team['slug'])),
        created_at=team["created_at"],
        provisioned_at=team.get("provisioned_at")
    )


@router.put("/{slug}", response_model=TeamResponse)
async def update_team(
    slug: str,
    request: TeamUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    """Update team details"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check if user is admin or owner
    membership = db_service.get_membership(team["id"], current_user["id"])
    if not membership or membership["role"] not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No updates provided")

    updated_team = db_service.update_team(team["id"], update_data)

    return TeamResponse(
        id=updated_team["id"],
        slug=updated_team["slug"],
        name=updated_team["name"],
        description=updated_team.get("description"),
        avatar_url=updated_team.get("avatar_url"),
        owner_id=updated_team["owner_id"],
        status=updated_team.get("status", "active"),
        subdomain=updated_team.get("subdomain"),
        created_at=updated_team["created_at"],
        provisioned_at=updated_team.get("provisioned_at")
    )


@router.delete("/{slug}")
async def delete_team(
    slug: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a team (owner only)"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Only owner can delete
    if team["owner_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Only team owner can delete")

    # Start deletion task
    task_id = await task_service.create_team_delete_task(
        team_id=team["id"],
        team_slug=slug,
        user_id=current_user["id"]
    )

    # Mark as pending deletion
    db_service.update_team(team["id"], {"status": "pending_deletion"})

    return {
        "message": "Team deletion started",
        "task_id": task_id
    }


@router.get("/{slug}/status")
async def get_team_status(
    slug: str,
    current_user: dict = Depends(get_current_user)
):
    """Get team provisioning status"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    return {
        "status": team.get("status", "unknown"),
        "provisioned_at": team.get("provisioned_at")
    }


# Member management
@router.get("/{slug}/members", response_model=List[TeamMemberResponse])
async def list_team_members(
    slug: str,
    current_user: dict = Depends(get_current_user)
):
    """Get all members of a team"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check membership
    membership = db_service.get_membership(team["id"], current_user["id"])
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this team")

    members = db_service.get_team_members(team["id"])

    return [
        TeamMemberResponse(
            id=member["id"],
            email=member["email"],
            display_name=member["display_name"],
            avatar_url=member.get("avatar_url"),
            role=member["role"],
            joined_at=member["joined_at"]
        )
        for member in members
    ]


@router.post("/{slug}/members")
async def add_team_member(
    slug: str,
    request: AddMemberRequest,
    current_user: dict = Depends(get_current_user)
):
    """Add a member to the team"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check if user is admin or owner
    membership = db_service.get_membership(team["id"], current_user["id"])
    if not membership or membership["role"] not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Find user by email
    user = db_service.get_user_by_email(request.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if already a member
    existing = db_service.get_membership(team["id"], user["id"])
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member")

    # Add member
    db_service.add_team_member(
        team_id=team["id"],
        user_id=user["id"],
        role=request.role,
        invited_by=current_user["id"]
    )

    return {"message": f"User {request.email} added to team"}


@router.delete("/{slug}/members/{user_id}")
async def remove_team_member(
    slug: str,
    user_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Remove a member from the team"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check if user is admin or owner
    membership = db_service.get_membership(team["id"], current_user["id"])
    if not membership or membership["role"] not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Can't remove owner
    if user_id == team["owner_id"]:
        raise HTTPException(status_code=400, detail="Cannot remove team owner")

    db_service.remove_team_member(team["id"], user_id)

    return {"message": "Member removed from team"}


class RegisterMemberRequest(BaseModel):
    user_id: str
    role: str = "member"


@router.post("/{slug}/register-member")
async def register_team_member(
    slug: str,
    request: RegisterMemberRequest
):
    """Register a member when they accept an invitation.

    This endpoint is called by team instances when a user accepts an invitation.
    It registers the membership in the portal database so the user can see
    the team in their dashboard.
    """
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check if user exists in portal
    user = db_service.get_user_by_id(request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if already a member
    existing = db_service.get_membership(team["id"], request.user_id)
    if existing:
        # Already a member, just return success
        return {"message": "User is already a member", "already_member": True}

    # Add member
    db_service.add_team_member(
        team_id=team["id"],
        user_id=request.user_id,
        role=request.role,
        invited_by=None  # Invited via team invitation
    )

    logger.info(f"Registered user {request.user_id} as member of team {slug}")

    return {"message": "Member registered successfully", "already_member": False}
