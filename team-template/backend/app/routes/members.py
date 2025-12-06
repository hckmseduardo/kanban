"""Member routes"""

from fastapi import APIRouter, HTTPException
from ..models.member import MemberCreate, MemberUpdate
from ..services.database import Database, Q
from pathlib import Path
import os

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


@router.get("")
async def list_members():
    """List all team members"""
    db.initialize()
    return db.members.all()


@router.post("")
async def add_member(data: MemberCreate):
    """Add a team member"""
    db.initialize()

    # Check if already a member
    existing = db.members.get(Q.user_id == data.user_id)
    if existing:
        raise HTTPException(status_code=400, detail="User is already a member")

    member = {
        "id": db.generate_id(),
        "user_id": data.user_id,
        "email": data.email,
        "name": data.name,
        "role": data.role,
        "avatar_url": None,
        "joined_at": db.timestamp()
    }
    db.members.insert(member)
    return member


@router.get("/{member_id}")
async def get_member(member_id: str):
    """Get a member"""
    db.initialize()
    member = db.members.get(Q.id == member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


@router.patch("/{member_id}")
async def update_member(member_id: str, data: MemberUpdate):
    """Update a member"""
    db.initialize()

    member = db.members.get(Q.id == member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    updates = data.model_dump(exclude_unset=True)
    db.members.update(updates, Q.id == member_id)

    return {**member, **updates}


@router.delete("/{member_id}")
async def remove_member(member_id: str):
    """Remove a member from the team"""
    db.initialize()

    member = db.members.get(Q.id == member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # Unassign cards
    db.cards.update({"assignee_id": None}, Q.assignee_id == member["user_id"])

    db.members.remove(Q.id == member_id)
    return {"deleted": True}
