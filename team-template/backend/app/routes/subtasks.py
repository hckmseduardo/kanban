"""
Card Subtasks API

Allows cards to have hierarchical subtasks with progress tracking.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from pathlib import Path
import os
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


class SubtaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None


class SubtaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None
    position: Optional[int] = None


@router.get("/cards/{card_id}/subtasks")
async def get_subtasks(card_id: str):
    """Get all subtasks for a card."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    subtasks = card.get("subtasks", [])
    completed = sum(1 for s in subtasks if s.get("completed"))
    total = len(subtasks)

    return {
        "card_id": card_id,
        "subtasks": sorted(subtasks, key=lambda x: x.get("position", 0)),
        "total": total,
        "completed": completed,
        "progress": round((completed / total) * 100) if total > 0 else 0
    }


@router.post("/cards/{card_id}/subtasks")
async def create_subtask(card_id: str, subtask: SubtaskCreate):
    """Create a new subtask on a card."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    subtasks = card.get("subtasks", [])

    new_subtask = {
        "id": db.generate_id(),
        "title": subtask.title,
        "description": subtask.description or "",
        "completed": False,
        "assignee_id": subtask.assignee_id,
        "due_date": subtask.due_date,
        "position": len(subtasks),
        "created_at": db.timestamp()
    }

    subtasks.append(new_subtask)

    # Update card with subtasks and progress
    completed = sum(1 for s in subtasks if s.get("completed"))
    progress = round((completed / len(subtasks)) * 100) if subtasks else 0

    db.cards.update({
        "subtasks": subtasks,
        "subtask_progress": progress
    }, Q.id == card_id)

    # Log activity
    db.log_activity(card_id, card.get("board_id", ""), "subtask_added", details={
        "subtask_id": new_subtask["id"],
        "title": new_subtask["title"]
    })

    return new_subtask


@router.patch("/cards/{card_id}/subtasks/{subtask_id}")
async def update_subtask(card_id: str, subtask_id: str, update: SubtaskUpdate):
    """Update a subtask."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    subtasks = card.get("subtasks", [])
    subtask_index = next((i for i, s in enumerate(subtasks) if s["id"] == subtask_id), None)

    if subtask_index is None:
        raise HTTPException(status_code=404, detail="Subtask not found")

    subtask = subtasks[subtask_index]
    was_completed = subtask.get("completed", False)

    if update.title is not None:
        subtask["title"] = update.title
    if update.description is not None:
        subtask["description"] = update.description
    if update.completed is not None:
        subtask["completed"] = update.completed
        if update.completed and not was_completed:
            subtask["completed_at"] = db.timestamp()
        elif not update.completed:
            subtask["completed_at"] = None
    if update.assignee_id is not None:
        subtask["assignee_id"] = update.assignee_id
    if update.due_date is not None:
        subtask["due_date"] = update.due_date
    if update.position is not None:
        # Reorder subtasks
        subtasks.pop(subtask_index)
        subtasks.insert(update.position, subtask)
        for i, s in enumerate(subtasks):
            s["position"] = i

    subtask["updated_at"] = db.timestamp()
    subtasks[subtask_index] = subtask

    # Update progress
    completed = sum(1 for s in subtasks if s.get("completed"))
    progress = round((completed / len(subtasks)) * 100) if subtasks else 0

    db.cards.update({
        "subtasks": subtasks,
        "subtask_progress": progress
    }, Q.id == card_id)

    # Log activity if completed status changed
    if update.completed is not None and update.completed != was_completed:
        action = "subtask_completed" if update.completed else "subtask_uncompleted"
        db.log_activity(card_id, card.get("board_id", ""), action, details={
            "subtask_id": subtask_id,
            "title": subtask["title"],
            "progress": progress
        })

    return {
        "subtask": subtask,
        "progress": progress
    }


@router.delete("/cards/{card_id}/subtasks/{subtask_id}")
async def delete_subtask(card_id: str, subtask_id: str):
    """Delete a subtask."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    subtasks = card.get("subtasks", [])
    subtask = next((s for s in subtasks if s["id"] == subtask_id), None)

    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")

    subtasks = [s for s in subtasks if s["id"] != subtask_id]

    # Reindex positions
    for i, s in enumerate(subtasks):
        s["position"] = i

    # Update progress
    completed = sum(1 for s in subtasks if s.get("completed"))
    progress = round((completed / len(subtasks)) * 100) if subtasks else 0

    db.cards.update({
        "subtasks": subtasks,
        "subtask_progress": progress
    }, Q.id == card_id)

    # Log activity
    db.log_activity(card_id, card.get("board_id", ""), "subtask_deleted", details={
        "subtask_id": subtask_id,
        "title": subtask["title"]
    })

    return {"message": "Subtask deleted", "progress": progress}


@router.post("/cards/{card_id}/subtasks/{subtask_id}/toggle")
async def toggle_subtask(card_id: str, subtask_id: str):
    """Toggle subtask completion status."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    subtasks = card.get("subtasks", [])
    subtask = next((s for s in subtasks if s["id"] == subtask_id), None)

    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")

    new_completed = not subtask.get("completed", False)
    subtask["completed"] = new_completed
    subtask["completed_at"] = db.timestamp() if new_completed else None
    subtask["updated_at"] = db.timestamp()

    # Update progress
    completed = sum(1 for s in subtasks if s.get("completed"))
    progress = round((completed / len(subtasks)) * 100) if subtasks else 0

    db.cards.update({
        "subtasks": subtasks,
        "subtask_progress": progress
    }, Q.id == card_id)

    # Log activity
    action = "subtask_completed" if new_completed else "subtask_uncompleted"
    db.log_activity(card_id, card.get("board_id", ""), action, details={
        "subtask_id": subtask_id,
        "title": subtask["title"],
        "progress": progress
    })

    return {
        "subtask": subtask,
        "progress": progress
    }


@router.post("/cards/{card_id}/subtasks/convert/{subtask_id}")
async def convert_subtask_to_card(card_id: str, subtask_id: str, column_id: Optional[str] = None):
    """Convert a subtask to a full card."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    subtasks = card.get("subtasks", [])
    subtask = next((s for s in subtasks if s["id"] == subtask_id), None)

    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")

    # Determine target column
    target_column_id = column_id or card.get("column_id")
    column = db.columns.get(Q.id == target_column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")

    # Get position in column
    existing_cards = db.cards.search(Q.column_id == target_column_id)
    max_position = max([c.get("position", 0) for c in existing_cards], default=-1)

    # Create new card from subtask
    new_card = {
        "id": db.generate_id(),
        "title": subtask["title"],
        "description": subtask.get("description", ""),
        "column_id": target_column_id,
        "board_id": column.get("board_id"),
        "position": max_position + 1,
        "assignee_id": subtask.get("assignee_id"),
        "due_date": subtask.get("due_date"),
        "created_at": db.timestamp(),
        "converted_from": {
            "card_id": card_id,
            "subtask_id": subtask_id
        }
    }

    db.cards.insert(new_card)

    # Remove subtask from original card
    subtasks = [s for s in subtasks if s["id"] != subtask_id]
    for i, s in enumerate(subtasks):
        s["position"] = i

    completed = sum(1 for s in subtasks if s.get("completed"))
    progress = round((completed / len(subtasks)) * 100) if subtasks else 0

    db.cards.update({
        "subtasks": subtasks,
        "subtask_progress": progress
    }, Q.id == card_id)

    # Log activity
    db.log_activity(card_id, card.get("board_id", ""), "subtask_converted", details={
        "subtask_id": subtask_id,
        "new_card_id": new_card["id"],
        "title": subtask["title"]
    })

    return {
        "message": "Subtask converted to card",
        "new_card": new_card
    }
