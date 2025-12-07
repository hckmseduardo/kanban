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
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


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

    return {
        **new_invitation,
        "invite_link": f"/join?token={token}"  # Frontend would construct full URL
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

    return {
        "message": "Invitation resent",
        "invite_link": f"/join?token={new_token}"
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


@router.post("/team/join")
async def accept_invitation(token: str, user_id: str = None, user_name: str = None):
    """Accept an invitation and join the team."""
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

    # Create member
    new_member = {
        "id": user_id or str(uuid.uuid4()),
        "email": invitation["email"],
        "name": user_name or invitation["email"].split("@")[0],
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
        "member_id": new_member["id"]
    }, Q.token == token)

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
            "allow_member_invites": False,
            "default_board_visibility": "team",
            "require_2fa": False
        }

    return settings


@router.patch("/team/settings")
async def update_team_settings(
    name: Optional[str] = None,
    allow_member_invites: Optional[bool] = None,
    default_board_visibility: Optional[str] = None
):
    """Update team settings (admin/owner only)."""
    db.initialize()

    settings_table = db.db.table("team_settings")
    existing = settings_table.get(Q.id == "settings")

    update_data = {"updated_at": db.timestamp()}

    if name is not None:
        update_data["name"] = name
    if allow_member_invites is not None:
        update_data["allow_member_invites"] = allow_member_invites
    if default_board_visibility is not None:
        update_data["default_board_visibility"] = default_board_visibility

    if existing:
        settings_table.update(update_data, Q.id == "settings")
        return {**existing, **update_data}
    else:
        new_settings = {
            "id": "settings",
            "name": name or os.getenv("TEAM_SLUG", "Team"),
            "allow_member_invites": allow_member_invites or False,
            "default_board_visibility": default_board_visibility or "team",
            **update_data
        }
        settings_table.insert(new_settings)
        return new_settings
