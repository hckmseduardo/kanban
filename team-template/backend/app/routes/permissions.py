"""
Board Permissions API

Manage user access levels for boards.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Literal, List
from pathlib import Path
import os
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


# Permission levels
ROLES = {
    "owner": {
        "description": "Full access, can delete board and manage permissions",
        "level": 100
    },
    "admin": {
        "description": "Can manage board settings, columns, and members",
        "level": 80
    },
    "member": {
        "description": "Can create, edit, and move cards",
        "level": 50
    },
    "viewer": {
        "description": "Can view board and cards only",
        "level": 10
    }
}


class BoardMemberAdd(BaseModel):
    user_id: str
    role: Literal["admin", "member", "viewer"]


class BoardMemberUpdate(BaseModel):
    role: Literal["admin", "member", "viewer"]


@router.get("/boards/{board_id}/members")
async def list_board_members(board_id: str):
    """List all members with access to a board."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    board_members = db.board_members.search(Q.board_id == board_id)

    # Enrich with user details
    enriched = []
    for bm in board_members:
        member = db.members.get(Q.id == bm["user_id"])
        enriched.append({
            "id": bm["id"],
            "user_id": bm["user_id"],
            "name": member.get("name") if member else "Unknown",
            "email": member.get("email") if member else None,
            "role": bm["role"],
            "role_description": ROLES.get(bm["role"], {}).get("description"),
            "added_at": bm.get("added_at")
        })

    # Sort by role level
    enriched.sort(key=lambda x: ROLES.get(x["role"], {}).get("level", 0), reverse=True)

    return {
        "board_id": board_id,
        "members": enriched,
        "count": len(enriched)
    }


@router.post("/boards/{board_id}/members")
async def add_board_member(board_id: str, member: BoardMemberAdd):
    """Add a member to a board."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Check if user exists
    user = db.members.get(Q.id == member.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if already a member
    existing = db.board_members.get(
        (Q.board_id == board_id) & (Q.user_id == member.user_id)
    )
    if existing:
        raise HTTPException(status_code=400, detail="User is already a board member")

    new_member = {
        "id": db.generate_id(),
        "board_id": board_id,
        "user_id": member.user_id,
        "role": member.role,
        "added_at": db.timestamp()
    }

    db.board_members.insert(new_member)

    return {
        **new_member,
        "name": user.get("name"),
        "email": user.get("email"),
        "role_description": ROLES.get(member.role, {}).get("description")
    }


@router.patch("/boards/{board_id}/members/{member_id}")
async def update_board_member(board_id: str, member_id: str, update: BoardMemberUpdate):
    """Update a member's role on a board."""
    db.initialize()

    board_member = db.board_members.get(
        (Q.id == member_id) & (Q.board_id == board_id)
    )

    if not board_member:
        raise HTTPException(status_code=404, detail="Board member not found")

    # Cannot change owner role
    if board_member.get("role") == "owner":
        raise HTTPException(status_code=400, detail="Cannot change owner role")

    db.board_members.update({
        "role": update.role,
        "updated_at": db.timestamp()
    }, Q.id == member_id)

    return {
        "id": member_id,
        "role": update.role,
        "role_description": ROLES.get(update.role, {}).get("description")
    }


@router.delete("/boards/{board_id}/members/{member_id}")
async def remove_board_member(board_id: str, member_id: str):
    """Remove a member from a board."""
    db.initialize()

    board_member = db.board_members.get(
        (Q.id == member_id) & (Q.board_id == board_id)
    )

    if not board_member:
        raise HTTPException(status_code=404, detail="Board member not found")

    # Cannot remove owner
    if board_member.get("role") == "owner":
        raise HTTPException(status_code=400, detail="Cannot remove board owner")

    db.board_members.remove(Q.id == member_id)

    return {"message": "Member removed from board"}


@router.get("/boards/{board_id}/members/{user_id}/permissions")
async def get_user_permissions(board_id: str, user_id: str):
    """Get permissions for a specific user on a board."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    board_member = db.board_members.get(
        (Q.board_id == board_id) & (Q.user_id == user_id)
    )

    if not board_member:
        return {
            "user_id": user_id,
            "board_id": board_id,
            "has_access": False,
            "role": None,
            "permissions": {}
        }

    role = board_member.get("role", "viewer")
    role_level = ROLES.get(role, {}).get("level", 0)

    permissions = {
        "can_view": role_level >= 10,
        "can_create_cards": role_level >= 50,
        "can_edit_cards": role_level >= 50,
        "can_move_cards": role_level >= 50,
        "can_delete_cards": role_level >= 50,
        "can_manage_columns": role_level >= 80,
        "can_manage_labels": role_level >= 80,
        "can_manage_settings": role_level >= 80,
        "can_manage_members": role_level >= 80,
        "can_delete_board": role_level >= 100,
        "can_transfer_ownership": role_level >= 100
    }

    return {
        "user_id": user_id,
        "board_id": board_id,
        "has_access": True,
        "role": role,
        "role_description": ROLES.get(role, {}).get("description"),
        "permissions": permissions
    }


@router.post("/boards/{board_id}/transfer-ownership")
async def transfer_board_ownership(board_id: str, new_owner_id: str):
    """Transfer board ownership to another user."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Verify new owner exists
    new_owner = db.members.get(Q.id == new_owner_id)
    if not new_owner:
        raise HTTPException(status_code=404, detail="New owner not found")

    # Find current owner
    current_owner = db.board_members.get(
        (Q.board_id == board_id) & (Q.role == "owner")
    )

    # Check new owner is already a member
    new_owner_membership = db.board_members.get(
        (Q.board_id == board_id) & (Q.user_id == new_owner_id)
    )

    if not new_owner_membership:
        # Add as owner
        db.board_members.insert({
            "id": db.generate_id(),
            "board_id": board_id,
            "user_id": new_owner_id,
            "role": "owner",
            "added_at": db.timestamp()
        })
    else:
        # Update to owner
        db.board_members.update({
            "role": "owner",
            "updated_at": db.timestamp()
        }, Q.id == new_owner_membership["id"])

    # Demote current owner to admin
    if current_owner and current_owner["user_id"] != new_owner_id:
        db.board_members.update({
            "role": "admin",
            "updated_at": db.timestamp()
        }, Q.id == current_owner["id"])

    return {
        "message": "Ownership transferred",
        "new_owner_id": new_owner_id,
        "new_owner_name": new_owner.get("name")
    }


@router.get("/users/{user_id}/boards")
async def get_user_boards(user_id: str):
    """Get all boards a user has access to."""
    db.initialize()

    memberships = db.board_members.search(Q.user_id == user_id)

    boards = []
    for membership in memberships:
        board = db.boards.get(Q.id == membership["board_id"])
        if board:
            boards.append({
                "board_id": board["id"],
                "board_name": board.get("name"),
                "role": membership["role"],
                "role_description": ROLES.get(membership["role"], {}).get("description")
            })

    return {
        "user_id": user_id,
        "boards": boards,
        "count": len(boards)
    }


@router.get("/permissions/roles")
async def list_roles():
    """List available roles and their permissions."""
    return {
        "roles": [
            {
                "role": role,
                "description": info["description"],
                "level": info["level"]
            }
            for role, info in sorted(ROLES.items(), key=lambda x: x[1]["level"], reverse=True)
        ]
    }
