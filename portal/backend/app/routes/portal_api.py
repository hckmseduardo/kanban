"""Portal API routes - Portal API token management

Portal API tokens (pk_*) allow programmatic access to portal endpoints:
- /api/teams/* - Team management and Team API (boards, columns, cards)

Token management requires JWT authentication (logged-in user).
"""

import hashlib
import secrets
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.jwt import get_current_user
from app.services.database_service import db_service

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


# =============================================================================
# Helper Functions
# =============================================================================

def generate_portal_api_token() -> tuple[str, str]:
    """Generate a new portal API token and its hash"""
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return f"pk_{token}", token_hash  # pk_ prefix for portal keys


# =============================================================================
# Portal API Token Management (requires JWT auth)
# =============================================================================

@router.post("/tokens", response_model=PortalApiTokenCreateResponse)
async def create_portal_token(
    data: PortalApiTokenCreate,
    user: dict = Depends(get_current_user)
):
    """Create a new Portal API token.

    Portal API tokens can be used to access portal endpoints programmatically.
    The token acts on behalf of the user who created it.

    Available scopes:

    Team Management (/api/teams):
    - teams:read - List and view teams
    - teams:write - Create, update, delete teams
    - members:read - List team members
    - members:write - Add/remove team members

    Team Data (/api/teams/{slug}/boards, /cards, etc.):
    - boards:read - List and view boards, columns, labels
    - boards:write - Create, update, delete boards and columns
    - cards:read - List and view cards
    - cards:write - Create, update, delete, move, archive cards

    Wildcard:
    - * - Full access (all scopes)
    """
    token, token_hash = generate_portal_api_token()

    token_data = db_service.create_portal_api_token(
        name=data.name,
        token_hash=token_hash,
        created_by=user["id"],
        scopes=data.scopes
    )

    logger.info(f"Portal API token '{data.name}' created by user {user['id']}")

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
    logger.info(f"Portal API token '{token_id}' deleted by user {user['id']}")
    return {"message": "Token deleted"}


# =============================================================================
# Portal API Token Validation (for team APIs)
# =============================================================================

@router.post("/validate-token")
async def validate_portal_token(
    token: str,
    team_slug: Optional[str] = None
):
    """Validate a Portal API token.

    This endpoint is called by team APIs to validate Portal API tokens (pk_*).
    No authentication required as this is used for token validation.

    Args:
        token: The Portal API token (pk_*)
        team_slug: Optional team slug to verify membership

    Returns:
        Token info including user, scopes, and team membership if requested
    """
    if not token.startswith("pk_"):
        return {"valid": False, "detail": "Not a Portal API token"}

    # Strip pk_ prefix before hashing
    raw_token = token[3:]
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token_data = db_service.get_portal_api_token_by_hash(token_hash)

    if not token_data:
        return {"valid": False, "detail": "Token not found"}

    if not token_data.get("is_active", True):
        return {"valid": False, "detail": "Token is inactive"}

    # Check expiration
    from datetime import datetime
    if token_data.get("expires_at"):
        expires = datetime.fromisoformat(token_data["expires_at"])
        if datetime.utcnow() > expires:
            return {"valid": False, "detail": "Token expired"}

    # Get user info
    user = db_service.get_user_by_id(token_data["created_by"])
    if not user:
        return {"valid": False, "detail": "Token creator not found"}

    # If team_slug provided, verify membership
    member_role = None
    if team_slug:
        team = db_service.get_team_by_slug(team_slug)
        if team:
            membership = db_service.get_membership(team["id"], user["id"])
            if membership:
                member_role = membership.get("role")

    # Update last used
    db_service.update_portal_api_token_last_used(token_data["id"])

    return {
        "valid": True,
        "user_id": user["id"],
        "user_email": user.get("email"),
        "user_display_name": user.get("display_name"),
        "token_name": token_data["name"],
        "scopes": token_data.get("scopes", []),
        "team_member_role": member_role
    }
