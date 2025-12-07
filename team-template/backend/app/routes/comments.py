"""Comments routes for cards"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from ..services.database import Database, Q
from pathlib import Path
import os

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


class CommentCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    author_name: Optional[str] = "Anonymous"
    author_id: Optional[str] = None


class CommentUpdate(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@router.get("/cards/{card_id}/comments")
async def list_comments(card_id: str):
    """List all comments for a card"""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    comments = db.comments.search(Q.card_id == card_id)
    return sorted(comments, key=lambda x: x.get("created_at", ""), reverse=True)


@router.post("/cards/{card_id}/comments")
async def create_comment(card_id: str, data: CommentCreate):
    """Add a comment to a card"""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    comment = {
        "id": db.generate_id(),
        "card_id": card_id,
        "text": data.text,
        "author_name": data.author_name,
        "author_id": data.author_id,
        "created_at": db.timestamp(),
        "updated_at": db.timestamp()
    }
    db.comments.insert(comment)

    return comment


@router.patch("/cards/{card_id}/comments/{comment_id}")
async def update_comment(card_id: str, comment_id: str, data: CommentUpdate):
    """Update a comment"""
    db.initialize()

    comment = db.comments.get((Q.id == comment_id) & (Q.card_id == card_id))
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    db.comments.update({
        "text": data.text,
        "updated_at": db.timestamp()
    }, Q.id == comment_id)

    return {**comment, "text": data.text, "updated_at": db.timestamp()}


@router.delete("/cards/{card_id}/comments/{comment_id}")
async def delete_comment(card_id: str, comment_id: str):
    """Delete a comment"""
    db.initialize()

    comment = db.comments.get((Q.id == comment_id) & (Q.card_id == card_id))
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    db.comments.remove(Q.id == comment_id)

    return {"deleted": True}
