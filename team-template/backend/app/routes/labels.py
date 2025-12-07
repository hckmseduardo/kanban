"""Labels routes for boards"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from ..services.database import Database, Q
from pathlib import Path
import os

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")

# Predefined label colors
LABEL_COLORS = [
    {"name": "red", "bg": "#FEE2E2", "text": "#991B1B"},
    {"name": "orange", "bg": "#FFEDD5", "text": "#9A3412"},
    {"name": "yellow", "bg": "#FEF9C3", "text": "#854D0E"},
    {"name": "green", "bg": "#DCFCE7", "text": "#166534"},
    {"name": "blue", "bg": "#DBEAFE", "text": "#1E40AF"},
    {"name": "purple", "bg": "#F3E8FF", "text": "#6B21A8"},
    {"name": "pink", "bg": "#FCE7F3", "text": "#9D174D"},
    {"name": "gray", "bg": "#F3F4F6", "text": "#374151"},
]


class LabelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=30)
    color: str = "blue"  # One of the predefined colors


class LabelUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=30)
    color: Optional[str] = None


@router.get("/colors")
async def list_colors():
    """Get available label colors"""
    return LABEL_COLORS


@router.get("/boards/{board_id}/labels")
async def list_labels(board_id: str):
    """List all labels for a board"""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    labels = db.labels.search(Q.board_id == board_id)
    return sorted(labels, key=lambda x: x.get("name", ""))


@router.post("/boards/{board_id}/labels")
async def create_label(board_id: str, data: LabelCreate):
    """Create a new label for a board"""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Check if label with same name exists
    existing = db.labels.get((Q.board_id == board_id) & (Q.name == data.name))
    if existing:
        raise HTTPException(status_code=400, detail="Label with this name already exists")

    # Get color info
    color_info = next((c for c in LABEL_COLORS if c["name"] == data.color), LABEL_COLORS[4])

    label = {
        "id": db.generate_id(),
        "board_id": board_id,
        "name": data.name,
        "color": data.color,
        "bg": color_info["bg"],
        "text": color_info["text"],
        "created_at": db.timestamp()
    }
    db.labels.insert(label)

    return label


@router.patch("/boards/{board_id}/labels/{label_id}")
async def update_label(board_id: str, label_id: str, data: LabelUpdate):
    """Update a label"""
    db.initialize()

    label = db.labels.get((Q.id == label_id) & (Q.board_id == board_id))
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")

    updates = {}
    if data.name is not None:
        # Check if name is taken
        existing = db.labels.get((Q.board_id == board_id) & (Q.name == data.name) & (Q.id != label_id))
        if existing:
            raise HTTPException(status_code=400, detail="Label with this name already exists")
        updates["name"] = data.name

    if data.color is not None:
        color_info = next((c for c in LABEL_COLORS if c["name"] == data.color), LABEL_COLORS[4])
        updates["color"] = data.color
        updates["bg"] = color_info["bg"]
        updates["text"] = color_info["text"]

    if updates:
        db.labels.update(updates, Q.id == label_id)

    return {**label, **updates}


@router.delete("/boards/{board_id}/labels/{label_id}")
async def delete_label(board_id: str, label_id: str):
    """Delete a label"""
    db.initialize()

    label = db.labels.get((Q.id == label_id) & (Q.board_id == board_id))
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")

    # Remove this label from all cards
    cards = db.cards.all()
    for card in cards:
        if label["name"] in card.get("labels", []):
            new_labels = [l for l in card["labels"] if l != label["name"]]
            db.cards.update({"labels": new_labels}, Q.id == card["id"])

    db.labels.remove(Q.id == label_id)

    return {"deleted": True}
