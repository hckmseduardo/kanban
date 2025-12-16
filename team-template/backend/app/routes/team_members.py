"""
Team Members API

Manages team-level membership and invitations.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Literal
from datetime import datetime, timedelta
from pathlib import Path
import os
import uuid
import secrets
import httpx
from ..services.database import Database, Q
from ..services.email import send_invitation_email

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")
TEAM_SLUG = os.getenv("TEAM_SLUG", "team")
DOMAIN = os.getenv("DOMAIN", "localhost")
TEAM_BASE_URL = os.getenv("TEAM_BASE_URL")
TEAM_NAME = os.getenv("TEAM_NAME", TEAM_SLUG)

# Portal API URL for token validation
PORTAL_API_URL = os.getenv("PORTAL_API_URL", f"https://{DOMAIN}/api")


def build_invite_link(token: str) -> str:
    """Construct a user-facing invite link for the email body."""
    base = TEAM_BASE_URL or f"https://{TEAM_SLUG}.{DOMAIN}"
    return f"{base.rstrip('/')}/join?token={token}"


class TeamMemberCreate(BaseModel):
    email: str
    name: Optional[str] = None
    role: Literal["owner", "admin", "member", "viewer"] = "member"


class TeamMemberUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[Literal["owner", "admin", "member", "viewer"]] = None
    is_active: Optional[bool] = None


class InvitationCreate(BaseModel):
    email: str
    role: Literal["admin", "member", "viewer"] = "member"
    message: Optional[str] = None


# ============== Team Members ==============

@router.get("/team/members")
async def list_team_members(
    include_inactive: bool = False,
    role: Optional[str] = None
):
    """List all team members."""
    db.initialize()

    members = db.members.all()

    if not include_inactive:
        members = [m for m in members if m.get("is_active", True)]

    if role:
        members = [m for m in members if m.get("role") == role]

    # Sort by role priority then name
    role_order = {"owner": 0, "admin": 1, "member": 2, "viewer": 3}
    members.sort(key=lambda x: (role_order.get(x.get("role", "member"), 99), x.get("name", "")))

    return {
        "members": members,
        "count": len(members),
        "by_role": {
            "owners": sum(1 for m in members if m.get("role") == "owner"),
            "admins": sum(1 for m in members if m.get("role") == "admin"),
            "members": sum(1 for m in members if m.get("role") == "member"),
            "viewers": sum(1 for m in members if m.get("role") == "viewer")
        }
    }


@router.get("/team/members/{member_id}")
async def get_team_member(member_id: str):
    """Get a specific team member."""
    db.initialize()

    member = db.members.get(Q.id == member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # Get boards this member has access to
    board_memberships = db.board_members.search(Q.user_id == member_id)
    boards_access = []
    for bm in board_memberships:
        board = db.boards.get(Q.id == bm.get("board_id"))
        if board:
            boards_access.append({
                "board_id": board["id"],
                "board_name": board.get("name"),
                "role": bm.get("role")
            })

    return {
        **member,
        "boards_access": boards_access
    }


@router.post("/team/members")
async def add_team_member(member_data: TeamMemberCreate):
    """Add a new team member directly."""
    db.initialize()

    # Check if email already exists
    existing = db.members.get(Q.email == member_data.email)
    if existing:
        raise HTTPException(status_code=400, detail="A member with this email already exists")

    new_member = {
        "id": str(uuid.uuid4()),
        "email": member_data.email,
        "name": member_data.name or member_data.email.split("@")[0],
        "role": member_data.role,
        "is_active": True,
        "avatar_url": None,
        "created_at": db.timestamp(),
        "last_seen": None
    }

    db.members.insert(new_member)

    return new_member


@router.patch("/team/members/{member_id}")
async def update_team_member(member_id: str, updates: TeamMemberUpdate):
    """Update a team member's info or role."""
    db.initialize()

    member = db.members.get(Q.id == member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # Don't allow changing role of last owner
    if updates.role and updates.role != "owner" and member.get("role") == "owner":
        owners = db.members.search(Q.role == "owner")
        if len(owners) <= 1:
            raise HTTPException(status_code=400, detail="Cannot change role of the last owner")

    update_data = {"updated_at": db.timestamp()}

    if updates.name is not None:
        update_data["name"] = updates.name
    if updates.role is not None:
        update_data["role"] = updates.role
    if updates.is_active is not None:
        update_data["is_active"] = updates.is_active

    db.members.update(update_data, Q.id == member_id)

    return {**member, **update_data}


@router.delete("/team/members/{member_id}")
async def remove_team_member(member_id: str, soft_delete: bool = True):
    """Remove a team member from the team."""
    db.initialize()

    member = db.members.get(Q.id == member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # Don't allow removing last owner
    if member.get("role") == "owner":
        owners = db.members.search(Q.role == "owner")
        if len(owners) <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last owner")

    if soft_delete:
        db.members.update({
            "is_active": False,
            "deactivated_at": db.timestamp()
        }, Q.id == member_id)
        message = "Member deactivated"
    else:
        # Remove from all boards
        db.board_members.remove(Q.user_id == member_id)
        # Remove member
        db.members.remove(Q.id == member_id)
        message = "Member permanently removed"

    return {"message": message, "member_id": member_id}


# ============== Invitations ==============

@router.get("/team/invitations")
async def list_invitations(status: Optional[str] = None):
    """List all team invitations."""
    db.initialize()

    # Ensure invitations table exists
    invitations = db.db.table("invitations").all()

    if status:
        invitations = [i for i in invitations if i.get("status") == status]

    return {
        "invitations": invitations,
        "count": len(invitations)
    }


@router.post("/team/invitations")
async def create_invitation(invitation: InvitationCreate, invited_by: str = None):
    """Create a new invitation to join the team."""
    db.initialize()

    # Check if already a member
    existing_member = db.members.get(Q.email == invitation.email)
    if existing_member and existing_member.get("is_active", True):
        raise HTTPException(status_code=400, detail="This email is already a team member")

    # Check for pending invitation
    invitations_table = db.db.table("invitations")
    pending = invitations_table.get(
        (Q.email == invitation.email) & (Q.status == "pending")
    )
    if pending:
        raise HTTPException(status_code=400, detail="An invitation is already pending for this email")

    # Generate invitation token
    token = secrets.token_urlsafe(32)

    new_invitation = {
        "id": db.generate_id(),
        "email": invitation.email,
        "role": invitation.role,
        "message": invitation.message,
        "token": token,
        "status": "pending",
        "invited_by": invited_by,
        "created_at": db.timestamp(),
        "expires_at": (datetime.utcnow() + timedelta(days=7)).isoformat()
    }

    invitations_table.insert(new_invitation)

    invite_link = build_invite_link(token)

    email_result = send_invitation_email(
        to_email=invitation.email,
        invite_link=invite_link,
        team_name=TEAM_NAME,
        invited_by=invited_by,
        message=invitation.message
    )

    if email_result.get("sent"):
        invitations_table.update({"email_sent_at": db.timestamp()}, Q.id == new_invitation["id"])
    else:
        invitations_table.update({"email_error": email_result.get("error")}, Q.id == new_invitation["id"])

    return {
        **new_invitation,
        "invite_link": invite_link,
        "email_sent": email_result.get("sent", False),
        "email_error": email_result.get("error")
    }


@router.post("/team/invitations/{invitation_id}/resend")
async def resend_invitation(invitation_id: str):
    """Resend an invitation email."""
    db.initialize()

    invitations_table = db.db.table("invitations")
    invitation = invitations_table.get(Q.id == invitation_id)

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invitation.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Can only resend pending invitations")

    # Generate new token and extend expiry
    new_token = secrets.token_urlsafe(32)
    invitations_table.update({
        "token": new_token,
        "expires_at": (datetime.utcnow() + timedelta(days=7)).isoformat(),
        "resent_at": db.timestamp()
    }, Q.id == invitation_id)

    invite_link = build_invite_link(new_token)

    email_result = send_invitation_email(
        to_email=invitation["email"],
        invite_link=invite_link,
        team_name=TEAM_NAME,
        invited_by=invitation.get("invited_by"),
        message=invitation.get("message")
    )

    if email_result.get("sent"):
        invitations_table.update({"email_sent_at": db.timestamp()}, Q.id == invitation_id)
    else:
        invitations_table.update({"email_error": email_result.get("error")}, Q.id == invitation_id)

    return {
        "message": "Invitation resent",
        "invite_link": invite_link,
        "email_sent": email_result.get("sent", False),
        "email_error": email_result.get("error")
    }


@router.delete("/team/invitations/{invitation_id}")
async def cancel_invitation(invitation_id: str):
    """Cancel a pending invitation."""
    db.initialize()

    invitations_table = db.db.table("invitations")
    invitation = invitations_table.get(Q.id == invitation_id)

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    invitations_table.update({
        "status": "cancelled",
        "cancelled_at": db.timestamp()
    }, Q.id == invitation_id)

    return {"message": "Invitation cancelled"}


@router.get("/team/invitations/by-token")
async def get_invitation_by_token(token: str):
    """Get invitation details by token (public endpoint for JoinTeam page)."""
    db.initialize()

    invitations_table = db.db.table("invitations")
    invitation = invitations_table.get(Q.token == token)

    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid invitation token")

    # Check expiry
    expires_at = datetime.fromisoformat(invitation["expires_at"])
    if datetime.utcnow() > expires_at:
        invitations_table.update({"status": "expired"}, Q.token == token)
        raise HTTPException(status_code=400, detail="This invitation has expired")

    if invitation.get("status") != "pending":
        raise HTTPException(status_code=400, detail="This invitation is no longer valid")

    # Return invitation details (without sensitive data)
    return {
        "email": invitation["email"],
        "role": invitation["role"],
        "message": invitation.get("message"),
        "invited_by": invitation.get("invited_by"),
        "team_name": TEAM_NAME,
        "team_slug": TEAM_SLUG,
        "expires_at": invitation["expires_at"]
    }


@router.post("/auth/exchange")
async def exchange_portal_token(token: str):
    """Exchange portal token for user info by validating with portal API."""
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(
                f"{PORTAL_API_URL}/users/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )

            if response.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid or expired token")

            if response.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to validate token with portal")

            user_data = response.json()
            return {
                "user": {
                    "id": user_data["id"],
                    "email": user_data["email"],
                    "display_name": user_data.get("display_name"),
                    "avatar_url": user_data.get("avatar_url")
                }
            }
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not connect to portal: {str(e)}")


@router.post("/team/join")
async def accept_invitation(token: str, user_id: str = None, user_name: str = None, user_email: str = None):
    """Accept an invitation and join the team.

    If user_id/user_email are provided (authenticated user), link the portal user to this team.
    Otherwise, create a new member based on the invitation email.
    """
    db.initialize()

    invitations_table = db.db.table("invitations")
    invitation = invitations_table.get(Q.token == token)

    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid invitation token")

    if invitation.get("status") != "pending":
        raise HTTPException(status_code=400, detail="This invitation is no longer valid")

    # Check expiry
    expires_at = datetime.fromisoformat(invitation["expires_at"])
    if datetime.utcnow() > expires_at:
        invitations_table.update({"status": "expired"}, Q.token == token)
        raise HTTPException(status_code=400, detail="This invitation has expired")

    # Use the authenticated user's email if provided, otherwise use invitation email
    member_email = user_email or invitation["email"]
    member_id = user_id or str(uuid.uuid4())
    member_name = user_name or member_email.split("@")[0]

    # Check if member already exists (by ID or email)
    existing_by_id = db.members.get(Q.id == member_id) if user_id else None
    existing_by_email = db.members.get(Q.email == member_email)

    if existing_by_id and existing_by_id.get("is_active", True):
        raise HTTPException(status_code=400, detail="You are already a member of this team")

    if existing_by_email and existing_by_email.get("is_active", True):
        raise HTTPException(status_code=400, detail="A member with this email already exists")

    if existing_by_id:
        # Reactivate the existing member
        db.members.update({
            "is_active": True,
            "role": invitation["role"],
            "reactivated_at": db.timestamp()
        }, Q.id == member_id)
        new_member = {**existing_by_id, "is_active": True, "role": invitation["role"]}
    elif existing_by_email:
        # Reactivate existing member by email
        db.members.update({
            "is_active": True,
            "role": invitation["role"],
            "reactivated_at": db.timestamp()
        }, Q.email == member_email)
        new_member = {**existing_by_email, "is_active": True, "role": invitation["role"]}
    else:
        # Create new member
        new_member = {
            "id": member_id,
            "email": member_email,
            "name": member_name,
            "role": invitation["role"],
            "is_active": True,
            "avatar_url": None,
            "created_at": db.timestamp(),
            "invited_by": invitation.get("invited_by")
        }
        db.members.insert(new_member)

    # Update invitation status
    invitations_table.update({
        "status": "accepted",
        "accepted_at": db.timestamp(),
        "member_id": new_member["id"],
        "accepted_by_email": member_email
    }, Q.token == token)

    # Register membership in portal so user can see the team in their dashboard
    if user_id:
        try:
            async with httpx.AsyncClient(verify=False) as client:
                await client.post(
                    f"{PORTAL_API_URL}/teams/{TEAM_SLUG}/register-member",
                    json={"user_id": user_id, "role": invitation["role"]},
                    timeout=10.0
                )
        except Exception as e:
            # Log but don't fail - local membership is already created
            import logging
            logging.warning(f"Failed to register membership in portal: {e}")

    return {
        "message": "Welcome to the team!",
        "member": new_member
    }


# ============== Team Settings ==============

@router.get("/team/settings")
async def get_team_settings():
    """Get team settings."""
    db.initialize()

    settings_table = db.db.table("team_settings")
    settings = settings_table.get(Q.id == "settings")

    if not settings:
        # Return defaults
        return {
            "id": "settings",
            "name": os.getenv("TEAM_SLUG", "Team"),
            "badge": None,
            "allow_member_invites": False,
            "default_board_visibility": "team",
            "require_2fa": False
        }

    return settings


class TeamSettingsUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    badge: Optional[str] = None
    allow_member_invites: Optional[bool] = None
    default_board_visibility: Optional[str] = None


@router.patch("/team/settings")
async def update_team_settings(updates: TeamSettingsUpdate):
    """Update team settings (admin/owner only)."""
    db.initialize()

    settings_table = db.db.table("team_settings")
    existing = settings_table.get(Q.id == "settings")

    update_data = {"updated_at": db.timestamp()}
    portal_update = {}

    if updates.name is not None:
        update_data["name"] = updates.name
        portal_update["name"] = updates.name
    if updates.description is not None:
        update_data["description"] = updates.description
        portal_update["description"] = updates.description
    if updates.badge is not None:
        update_data["badge"] = updates.badge
        portal_update["badge"] = updates.badge
    if updates.allow_member_invites is not None:
        update_data["allow_member_invites"] = updates.allow_member_invites
    if updates.default_board_visibility is not None:
        update_data["default_board_visibility"] = updates.default_board_visibility

    if existing:
        settings_table.update(update_data, Q.id == "settings")
        result = {**existing, **update_data}
    else:
        result = {
            "id": "settings",
            "name": updates.name or os.getenv("TEAM_SLUG", "Team"),
            "description": updates.description,
            "badge": updates.badge,
            "allow_member_invites": updates.allow_member_invites or False,
            "default_board_visibility": updates.default_board_visibility or "team",
            **update_data
        }
        settings_table.insert(result)

    # Sync name, description, badge to portal if changed
    if portal_update:
        try:
            async with httpx.AsyncClient(verify=False) as client:
                await client.post(
                    f"{PORTAL_API_URL}/teams/{TEAM_SLUG}/sync-settings",
                    json=portal_update,
                    timeout=10.0
                )
        except Exception as e:
            import logging
            logging.warning(f"Failed to sync settings to portal: {e}")

    return result
