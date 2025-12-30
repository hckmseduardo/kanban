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
    badge: Optional[str] = None


class TeamResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    badge: Optional[str] = None
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
        owner_id=current_user["id"],
        owner_email=current_user.get("email"),
        owner_name=current_user.get("display_name")
    )

    logger.info(f"Team {request.slug} creation started, task: {task_id}")

    return {
        "team": TeamResponse(
            id=team["id"],
            slug=team["slug"],
            name=team["name"],
            description=team.get("description"),
            avatar_url=team.get("avatar_url"),
            badge=team.get("badge"),
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

    # Filter out teams being deleted (worker will clean them up)
    active_teams = [t for t in teams if t.get("status") != "pending_deletion"]

    return [
        TeamResponse(
            id=team["id"],
            slug=team["slug"],
            name=team["name"],
            description=team.get("description"),
            avatar_url=team.get("avatar_url"),
            badge=team.get("badge"),
            owner_id=team["owner_id"],
            status=team.get("status", "active"),
            subdomain=team.get("subdomain", get_team_subdomain(team['slug'])),
            created_at=team["created_at"],
            provisioned_at=team.get("provisioned_at")
        )
        for team in active_teams
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
        badge=team.get("badge"),
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
        badge=updated_team.get("badge"),
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


class RestartTeamRequest(BaseModel):
    rebuild: bool = False


@router.post("/{slug}/restart")
async def restart_team(
    slug: str,
    request: RestartTeamRequest = RestartTeamRequest(),
    current_user: dict = Depends(get_current_user)
):
    """Restart or rebuild a team's containers.

    Args:
        rebuild: If True, removes images and rebuilds from scratch.
                 If False (default), just restarts the containers.
    """
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check if user is admin or owner
    membership = db_service.get_membership(team["id"], current_user["id"])
    if not membership or membership["role"] not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Update status to restarting
    db_service.update_team(team["id"], {"status": "restarting"})

    # Create restart task
    task_id = await task_service.create_team_restart_task(
        team_id=team["id"],
        team_slug=slug,
        user_id=current_user["id"],
        rebuild=request.rebuild
    )

    action = "rebuild" if request.rebuild else "restart"
    logger.info(f"Team {slug} {action} started, task: {task_id}")

    return {
        "message": f"Team {action} started",
        "task_id": task_id
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


class SyncSettingsRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    badge: Optional[str] = None


@router.post("/{slug}/sync-settings")
async def sync_team_settings(
    slug: str,
    request: SyncSettingsRequest
):
    """Sync team settings from team instance.

    This endpoint is called by team instances when settings are updated.
    It syncs name, description, and badge to the portal database.
    """
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        return {"message": "No updates provided"}

    db_service.update_team(team["id"], update_data)

    logger.info(f"Synced settings for team {slug}: {update_data}")

    return {"message": "Settings synced successfully", "updated": list(update_data.keys())}


class UnregisterMemberRequest(BaseModel):
    user_id: str


@router.post("/{slug}/unregister-member")
async def unregister_team_member(
    slug: str,
    request: UnregisterMemberRequest
):
    """Unregister a member when they are removed from a team.

    This endpoint is called by team instances when a member is removed.
    It removes the membership from the portal database so the user no longer
    sees the team in their dashboard.
    """
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check if user is a member
    existing = db_service.get_membership(team["id"], request.user_id)
    if not existing:
        # Not a member, just return success
        return {"message": "User is not a member", "was_member": False}

    # Can't remove owner via this endpoint
    if request.user_id == team["owner_id"]:
        raise HTTPException(status_code=400, detail="Cannot remove team owner")

    # Remove member
    db_service.remove_team_member(team["id"], request.user_id)

    logger.info(f"Unregistered user {request.user_id} from team {slug}")

    return {"message": "Member unregistered successfully", "was_member": True}


# =============================================================================
# API Token Management
# =============================================================================

import secrets
import hashlib


def generate_api_token() -> tuple[str, str]:
    """Generate a secure API token and its hash.
    Returns (plaintext_token, token_hash)
    """
    # Generate a secure random token
    token = secrets.token_urlsafe(32)  # 256 bits of randomness
    # Hash it for storage
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return token, token_hash


def hash_token(token: str) -> str:
    """Hash a token for lookup"""
    return hashlib.sha256(token.encode()).hexdigest()


class ApiTokenCreateRequest(BaseModel):
    name: str
    scopes: Optional[List[str]] = None
    expires_in_days: Optional[int] = None  # None = never expires


class ApiTokenResponse(BaseModel):
    id: str
    team_id: str
    name: str
    scopes: List[str]
    created_by: str
    created_at: str
    expires_at: Optional[str]
    last_used_at: Optional[str]
    is_active: bool


class ApiTokenCreateResponse(BaseModel):
    token: ApiTokenResponse
    plaintext_token: str  # Only shown once at creation


@router.post("/{slug}/api-tokens", response_model=ApiTokenCreateResponse)
async def create_api_token(
    slug: str,
    request: ApiTokenCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """Create a new API token for the team.

    The plaintext token is only shown once. Store it securely.
    """
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check if user is admin or owner
    membership = db_service.get_membership(team["id"], current_user["id"])
    if not membership or membership["role"] not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Generate token
    plaintext_token, token_hash = generate_api_token()

    # Calculate expiry
    expires_at = None
    if request.expires_in_days:
        from datetime import datetime, timedelta
        expires_at = (datetime.utcnow() + timedelta(days=request.expires_in_days)).isoformat()

    # Create token record
    token_data = db_service.create_api_token(
        team_id=team["id"],
        name=request.name,
        token_hash=token_hash,
        created_by=current_user["id"],
        scopes=request.scopes,
        expires_at=expires_at
    )

    logger.info(f"API token '{request.name}' created for team {slug} by {current_user['id']}")

    return ApiTokenCreateResponse(
        token=ApiTokenResponse(
            id=token_data["id"],
            team_id=token_data["team_id"],
            name=token_data["name"],
            scopes=token_data["scopes"],
            created_by=token_data["created_by"],
            created_at=token_data["created_at"],
            expires_at=token_data.get("expires_at"),
            last_used_at=token_data.get("last_used_at"),
            is_active=token_data["is_active"]
        ),
        plaintext_token=plaintext_token
    )


@router.get("/{slug}/api-tokens", response_model=List[ApiTokenResponse])
async def list_api_tokens(
    slug: str,
    current_user: dict = Depends(get_current_user)
):
    """List all API tokens for a team"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check membership (any member can view tokens)
    membership = db_service.get_membership(team["id"], current_user["id"])
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this team")

    tokens = db_service.get_team_api_tokens(team["id"])

    return [
        ApiTokenResponse(
            id=t["id"],
            team_id=t["team_id"],
            name=t["name"],
            scopes=t["scopes"],
            created_by=t["created_by"],
            created_at=t["created_at"],
            expires_at=t.get("expires_at"),
            last_used_at=t.get("last_used_at"),
            is_active=t["is_active"]
        )
        for t in tokens
    ]


@router.delete("/{slug}/api-tokens/{token_id}")
async def delete_api_token(
    slug: str,
    token_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete (revoke) an API token"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Check if user is admin or owner
    membership = db_service.get_membership(team["id"], current_user["id"])
    if not membership or membership["role"] not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Verify token belongs to this team
    token = db_service.get_api_token_by_id(token_id)
    if not token or token["team_id"] != team["id"]:
        raise HTTPException(status_code=404, detail="Token not found")

    db_service.delete_api_token(token_id)

    logger.info(f"API token '{token_id}' deleted from team {slug} by {current_user['id']}")

    return {"message": "Token deleted"}


@router.post("/validate-api-token")
async def validate_api_token(
    token: str = Query(..., description="The API token to validate")
):
    """Validate an API token and return team info.

    This endpoint is called by team instances to validate incoming API tokens.
    """
    token_hash = hash_token(token)
    token_data = db_service.get_api_token_by_hash(token_hash)

    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Check expiry
    if token_data.get("expires_at"):
        from datetime import datetime
        if datetime.fromisoformat(token_data["expires_at"]) < datetime.utcnow():
            raise HTTPException(status_code=401, detail="Token expired")

    # Get team info
    team = db_service.get_team_by_id(token_data["team_id"])
    if not team:
        raise HTTPException(status_code=401, detail="Team not found")

    # Update last used
    db_service.update_api_token_last_used(token_data["id"])

    return {
        "valid": True,
        "team_id": team["id"],
        "team_slug": team["slug"],
        "scopes": token_data["scopes"],
        "token_name": token_data["name"]
    }
