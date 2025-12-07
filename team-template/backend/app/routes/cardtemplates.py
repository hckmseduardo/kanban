"""
Card Templates API

Reusable card templates within a board.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Any, Dict
from pathlib import Path
import os
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


class CardTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    title_template: str = "New Card"
    card_description: Optional[str] = None
    labels: Optional[List[str]] = None
    priority: Optional[str] = None
    checklist: Optional[List[str]] = None
    subtasks: Optional[List[str]] = None
    custom_field_values: Optional[Dict[str, Any]] = None
    due_days_from_creation: Optional[int] = None


class CardTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    title_template: Optional[str] = None
    card_description: Optional[str] = None
    labels: Optional[List[str]] = None
    priority: Optional[str] = None
    checklist: Optional[List[str]] = None
    subtasks: Optional[List[str]] = None
    custom_field_values: Optional[Dict[str, Any]] = None
    due_days_from_creation: Optional[int] = None


@router.get("/boards/{board_id}/card-templates")
async def list_card_templates(board_id: str):
    """List all card templates for a board."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    templates = db.card_templates.search(Q.board_id == board_id)

    return {
        "board_id": board_id,
        "templates": templates,
        "count": len(templates)
    }


@router.post("/boards/{board_id}/card-templates")
async def create_card_template(board_id: str, template: CardTemplateCreate):
    """Create a new card template."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    new_template = {
        "id": db.generate_id(),
        "board_id": board_id,
        "name": template.name,
        "description": template.description or "",
        "title_template": template.title_template,
        "card_description": template.card_description or "",
        "labels": template.labels or [],
        "priority": template.priority,
        "checklist": template.checklist or [],
        "subtasks": template.subtasks or [],
        "custom_field_values": template.custom_field_values or {},
        "due_days_from_creation": template.due_days_from_creation,
        "use_count": 0,
        "created_at": db.timestamp()
    }

    db.card_templates.insert(new_template)

    return new_template


@router.get("/boards/{board_id}/card-templates/{template_id}")
async def get_card_template(board_id: str, template_id: str):
    """Get a specific card template."""
    db.initialize()

    template = db.card_templates.get(
        (Q.id == template_id) & (Q.board_id == board_id)
    )

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return template


@router.patch("/boards/{board_id}/card-templates/{template_id}")
async def update_card_template(board_id: str, template_id: str, update: CardTemplateUpdate):
    """Update a card template."""
    db.initialize()

    template = db.card_templates.get(
        (Q.id == template_id) & (Q.board_id == board_id)
    )

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    updates = {}

    if update.name is not None:
        updates["name"] = update.name
    if update.description is not None:
        updates["description"] = update.description
    if update.title_template is not None:
        updates["title_template"] = update.title_template
    if update.card_description is not None:
        updates["card_description"] = update.card_description
    if update.labels is not None:
        updates["labels"] = update.labels
    if update.priority is not None:
        updates["priority"] = update.priority
    if update.checklist is not None:
        updates["checklist"] = update.checklist
    if update.subtasks is not None:
        updates["subtasks"] = update.subtasks
    if update.custom_field_values is not None:
        updates["custom_field_values"] = update.custom_field_values
    if update.due_days_from_creation is not None:
        updates["due_days_from_creation"] = update.due_days_from_creation

    updates["updated_at"] = db.timestamp()

    db.card_templates.update(updates, Q.id == template_id)

    return {**template, **updates}


@router.delete("/boards/{board_id}/card-templates/{template_id}")
async def delete_card_template(board_id: str, template_id: str):
    """Delete a card template."""
    db.initialize()

    template = db.card_templates.get(
        (Q.id == template_id) & (Q.board_id == board_id)
    )

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    db.card_templates.remove(Q.id == template_id)

    return {"message": "Template deleted"}


@router.post("/boards/{board_id}/card-templates/{template_id}/apply")
async def apply_card_template(
    board_id: str,
    template_id: str,
    column_id: str,
    title_override: Optional[str] = None
):
    """Create a new card from a template."""
    db.initialize()

    template = db.card_templates.get(
        (Q.id == template_id) & (Q.board_id == board_id)
    )

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    column = db.columns.get(Q.id == column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")

    # Get position in column
    existing_cards = db.cards.search(Q.column_id == column_id)
    max_position = max([c.get("position", 0) for c in existing_cards], default=-1)

    # Calculate due date if specified
    due_date = None
    if template.get("due_days_from_creation"):
        from datetime import datetime, timedelta
        due = datetime.now() + timedelta(days=template["due_days_from_creation"])
        due_date = due.strftime("%Y-%m-%d")

    # Create checklist items
    checklist = []
    for item_text in template.get("checklist", []):
        checklist.append({
            "id": db.generate_id(),
            "text": item_text,
            "completed": False
        })

    # Create subtasks
    subtasks = []
    for idx, subtask_title in enumerate(template.get("subtasks", [])):
        subtasks.append({
            "id": db.generate_id(),
            "title": subtask_title,
            "completed": False,
            "position": idx,
            "created_at": db.timestamp()
        })

    # Create new card
    new_card = {
        "id": db.generate_id(),
        "title": title_override or template.get("title_template", "New Card"),
        "description": template.get("card_description", ""),
        "column_id": column_id,
        "board_id": board_id,
        "position": max_position + 1,
        "labels": template.get("labels", []),
        "priority": template.get("priority"),
        "due_date": due_date,
        "checklist": checklist,
        "subtasks": subtasks,
        "subtask_progress": 0,
        "custom_field_values": template.get("custom_field_values", {}),
        "created_from_template": template_id,
        "created_at": db.timestamp()
    }

    db.cards.insert(new_card)

    # Increment template use count
    db.card_templates.update({
        "use_count": template.get("use_count", 0) + 1,
        "last_used_at": db.timestamp()
    }, Q.id == template_id)

    # Log activity
    db.log_activity(new_card["id"], board_id, "card_created", details={
        "from_template": template_id,
        "template_name": template.get("name")
    })

    return new_card


@router.post("/boards/{board_id}/card-templates/from-card/{card_id}")
async def create_template_from_card(
    board_id: str,
    card_id: str,
    name: str,
    description: Optional[str] = None
):
    """Create a template from an existing card."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Extract subtask titles
    subtask_titles = [s.get("title") for s in card.get("subtasks", [])]

    # Extract checklist items
    checklist_items = [item.get("text") for item in card.get("checklist", [])]

    new_template = {
        "id": db.generate_id(),
        "board_id": board_id,
        "name": name,
        "description": description or f"Created from card: {card.get('title')}",
        "title_template": card.get("title", "New Card"),
        "card_description": card.get("description", ""),
        "labels": card.get("labels", []),
        "priority": card.get("priority"),
        "checklist": checklist_items,
        "subtasks": subtask_titles,
        "custom_field_values": card.get("custom_field_values", {}),
        "due_days_from_creation": None,
        "use_count": 0,
        "source_card_id": card_id,
        "created_at": db.timestamp()
    }

    db.card_templates.insert(new_template)

    return new_template
