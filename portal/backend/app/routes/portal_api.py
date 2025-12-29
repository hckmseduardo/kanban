"""Portal API routes - programmatic access to manage teams, boards, and members"""

import hashlib
import secrets
import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from pydantic import BaseModel, Field
import httpx

from app.auth.jwt import get_current_user
from app.services.database_service import db_service
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Pydantic Models
# =============================================================================

class PortalApiTokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: Optional[List[str]] = None


class PortalApiTokenResponse(BaseModel):
    id: str
    name: str
    scopes: List[str]
    created_by: str
    created_at: str
    expires_at: Optional[str]
    last_used_at: Optional[str]
    is_active: bool


class PortalApiTokenCreateResponse(PortalApiTokenResponse):
    token: str  # Only returned on creation


class TeamCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=50, pattern="^[a-z0-9-]+$")
    description: Optional[str] = None
    badge: Optional[str] = None


class TeamResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str]
    badge: Optional[str]
    status: str
    subdomain: str
    owner_id: str
    created_at: str


class BoardCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    template: Optional[str] = "blank"


class BoardResponse(BaseModel):
    id: str
    name: str
    columns: List[dict]
    created_at: str


class MemberAddRequest(BaseModel):
    email: str
    role: str = "member"


class MemberResponse(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    joined_at: str


# =============================================================================
# Portal API Token Authentication
# =============================================================================

def generate_portal_api_token() -> tuple[str, str]:
    """Generate a new portal API token and its hash"""
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return f"pk_{token}", token_hash  # pk_ prefix for portal keys


async def verify_portal_api_token(
    authorization: Optional[str] = Header(None)
) -> dict:
    """Verify portal API token from Authorization header"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header"
        )

    # Extract token from "Bearer <token>" format
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format"
        )

    token = parts[1]

    # Portal API tokens start with pk_
    if not token.startswith("pk_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format"
        )

    # Hash and lookup
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    token_data = db_service.get_portal_api_token_by_hash(token_hash)

    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    # Check expiration
    if token_data.get("expires_at"):
        expires = datetime.fromisoformat(token_data["expires_at"])
        if datetime.utcnow() > expires:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )

    # Update last used
    db_service.update_portal_api_token_last_used(token_data["id"])

    return token_data


def require_scope(required_scope: str):
    """Dependency factory to require specific scope"""
    async def check_scope(token_data: dict = Depends(verify_portal_api_token)):
        scopes = token_data.get("scopes", [])
        # Check for exact match or wildcard
        if required_scope not in scopes and "*" not in scopes:
            # Check for category wildcard (e.g., teams:* covers teams:read)
            category = required_scope.split(":")[0]
            if f"{category}:*" not in scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Token missing required scope: {required_scope}"
                )
        return token_data
    return check_scope


# =============================================================================
# Portal API Token Management (requires user auth)
# =============================================================================

@router.post("/tokens", response_model=PortalApiTokenCreateResponse)
async def create_portal_token(
    data: PortalApiTokenCreate,
    user: dict = Depends(get_current_user)
):
    """Create a new Portal API token"""
    token, token_hash = generate_portal_api_token()

    token_data = db_service.create_portal_api_token(
        name=data.name,
        token_hash=token_hash,
        created_by=user["id"],
        scopes=data.scopes
    )

    return PortalApiTokenCreateResponse(
        id=token_data["id"],
        name=token_data["name"],
        scopes=token_data["scopes"],
        created_by=token_data["created_by"],
        created_at=token_data["created_at"],
        expires_at=token_data.get("expires_at"),
        last_used_at=token_data.get("last_used_at"),
        is_active=token_data["is_active"],
        token=token  # Only returned once!
    )


@router.get("/tokens", response_model=List[PortalApiTokenResponse])
async def list_portal_tokens(user: dict = Depends(get_current_user)):
    """List all Portal API tokens created by the current user"""
    tokens = db_service.get_all_portal_api_tokens(created_by=user["id"])
    return tokens


@router.delete("/tokens/{token_id}")
async def delete_portal_token(
    token_id: str,
    user: dict = Depends(get_current_user)
):
    """Delete a Portal API token"""
    token = db_service.get_portal_api_token_by_id(token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")

    if token["created_by"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized to delete this token")

    db_service.delete_portal_api_token(token_id)
    return {"message": "Token deleted"}


# =============================================================================
# Team Management API (requires portal API token)
# =============================================================================

@router.get("/teams", response_model=List[TeamResponse])
async def api_list_teams(
    token_data: dict = Depends(require_scope("teams:read"))
):
    """List all teams (API access)"""
    db_service.refresh()
    teams = db_service.teams.all()

    result = []
    for team in teams:
        subdomain = f"https://{team['slug']}.{settings.domain}"
        if settings.port != 443:
            subdomain += f":{settings.port}"

        result.append(TeamResponse(
            id=team["id"],
            name=team["name"],
            slug=team["slug"],
            description=team.get("description"),
            badge=team.get("badge"),
            status=team["status"],
            subdomain=subdomain,
            owner_id=team["owner_id"],
            created_at=team["created_at"]
        ))

    return result


@router.post("/teams", response_model=TeamResponse)
async def api_create_team(
    data: TeamCreateRequest,
    owner_id: str = Query(..., description="User ID of the team owner"),
    token_data: dict = Depends(require_scope("teams:write"))
):
    """Create a new team (API access)"""
    from app.services.task_service import task_service
    import uuid

    # Check slug availability
    existing = db_service.get_team_by_slug(data.slug)
    if existing:
        raise HTTPException(status_code=400, detail="Team slug already exists")

    # Verify owner exists
    owner = db_service.get_user_by_id(owner_id)
    if not owner:
        raise HTTPException(status_code=400, detail="Owner user not found")

    # Create team
    team_id = str(uuid.uuid4())
    subdomain = f"https://{data.slug}.{settings.domain}"
    if settings.port != 443:
        subdomain += f":{settings.port}"

    team_data = {
        "id": team_id,
        "name": data.name,
        "slug": data.slug,
        "description": data.description,
        "badge": data.badge,
        "owner_id": owner_id,
        "subdomain": subdomain
    }

    team = db_service.create_team(team_data)
    db_service.add_team_member(team_id, owner_id, role="owner", invited_by=owner_id)

    # Queue provisioning task
    await task_service.create_task(
        task_type="create_team",
        payload={"team_slug": data.slug, "team_id": team_id},
        created_by=owner_id
    )

    return TeamResponse(
        id=team["id"],
        name=team["name"],
        slug=team["slug"],
        description=team.get("description"),
        badge=team.get("badge"),
        status=team["status"],
        subdomain=subdomain,
        owner_id=team["owner_id"],
        created_at=team["created_at"]
    )


@router.get("/teams/{slug}", response_model=TeamResponse)
async def api_get_team(
    slug: str,
    token_data: dict = Depends(require_scope("teams:read"))
):
    """Get team details (API access)"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    subdomain = f"https://{team['slug']}.{settings.domain}"
    if settings.port != 443:
        subdomain += f":{settings.port}"

    return TeamResponse(
        id=team["id"],
        name=team["name"],
        slug=team["slug"],
        description=team.get("description"),
        badge=team.get("badge"),
        status=team["status"],
        subdomain=subdomain,
        owner_id=team["owner_id"],
        created_at=team["created_at"]
    )


@router.delete("/teams/{slug}")
async def api_delete_team(
    slug: str,
    token_data: dict = Depends(require_scope("teams:write"))
):
    """Delete a team (API access)"""
    from app.services.task_service import task_service

    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Mark as pending deletion
    db_service.update_team(team["id"], {"status": "pending_deletion"})

    # Queue deletion task
    await task_service.create_task(
        task_type="delete_team",
        payload={"team_slug": slug, "team_id": team["id"]},
        created_by=token_data["created_by"]
    )

    return {"message": "Team deletion queued", "team_slug": slug}


# =============================================================================
# Team Members Management API (requires portal API token)
# =============================================================================

@router.get("/teams/{slug}/members", response_model=List[MemberResponse])
async def api_list_team_members(
    slug: str,
    token_data: dict = Depends(require_scope("members:read"))
):
    """List team members (API access)"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    members = db_service.get_team_members(team["id"])
    return [
        MemberResponse(
            id=m["id"],
            email=m["email"],
            display_name=m["display_name"],
            role=m["role"],
            joined_at=m["joined_at"]
        )
        for m in members
    ]


@router.post("/teams/{slug}/members", response_model=MemberResponse)
async def api_add_team_member(
    slug: str,
    data: MemberAddRequest,
    token_data: dict = Depends(require_scope("members:write"))
):
    """Add a member to team (API access)"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Find user by email
    user = db_service.get_user_by_email(data.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if already member
    existing = db_service.get_membership(team["id"], user["id"])
    if existing:
        raise HTTPException(status_code=400, detail="User is already a team member")

    # Add member
    membership = db_service.add_team_member(
        team_id=team["id"],
        user_id=user["id"],
        role=data.role,
        invited_by=token_data["created_by"]
    )

    return MemberResponse(
        id=user["id"],
        email=user["email"],
        display_name=user["display_name"],
        role=membership["role"],
        joined_at=membership["joined_at"]
    )


@router.delete("/teams/{slug}/members/{user_id}")
async def api_remove_team_member(
    slug: str,
    user_id: str,
    token_data: dict = Depends(require_scope("members:write"))
):
    """Remove a member from team (API access)"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    membership = db_service.get_membership(team["id"], user_id)
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")

    # Prevent removing owner
    if membership["role"] == "owner":
        raise HTTPException(status_code=400, detail="Cannot remove team owner")

    db_service.remove_team_member(team["id"], user_id)
    return {"message": "Member removed"}


# =============================================================================
# Team Boards Management API (requires portal API token)
# =============================================================================

@router.get("/teams/{slug}/boards")
async def api_list_team_boards(
    slug: str,
    token_data: dict = Depends(require_scope("boards:read"))
):
    """List boards in a team (API access) - proxies to team API"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    if team["status"] != "active":
        raise HTTPException(status_code=400, detail="Team is not active")

    # Get a team API token for this team
    team_tokens = db_service.get_team_api_tokens(team["id"])
    active_token = next((t for t in team_tokens if t.get("is_active")), None)

    if not active_token:
        raise HTTPException(
            status_code=400,
            detail="No active API token for this team. Create one first."
        )

    # We need to call the team API to get boards
    # For this we need the actual token, which we don't store
    # Instead, return info that boards should be accessed via team API
    return {
        "message": "Board management requires direct team API access",
        "team_api_url": f"{team.get('subdomain', '')}/api",
        "docs": f"{team.get('subdomain', '')}/api/docs"
    }


@router.post("/teams/{slug}/boards")
async def api_create_team_board(
    slug: str,
    data: BoardCreateRequest,
    token_data: dict = Depends(require_scope("boards:write"))
):
    """Create a board in a team (API access)"""
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    if team["status"] != "active":
        raise HTTPException(status_code=400, detail="Team is not active")

    return {
        "message": "Board creation requires direct team API access",
        "team_api_url": f"{team.get('subdomain', '')}/api",
        "docs": f"{team.get('subdomain', '')}/api/docs",
        "hint": "Use POST /api/boards with a team API token"
    }
