"""Card routes"""

from fastapi import APIRouter, HTTPException
from ..models.board import CardCreate, CardUpdate, ChecklistItemCreate, ChecklistItemUpdate
from ..services.database import Database, Q
from ..services.webhook_service import trigger_webhooks
from pathlib import Path
import os

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


@router.get("")
async def list_cards(column_id: str = None):
    """List cards, optionally filtered by column"""
    db.initialize()
    if column_id:
        cards = db.cards.search(Q.column_id == column_id)
    else:
        cards = db.cards.all()
    return sorted(cards, key=lambda x: x.get("position", 0))


@router.post("")
async def create_card(data: CardCreate):
    """Create a new card"""
    db.initialize()

    column = db.columns.get(Q.id == data.column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")

    # Check WIP limit
    if column.get("wip_limit"):
        current_cards = len(db.cards.search(Q.column_id == data.column_id))
        if current_cards >= column["wip_limit"]:
            raise HTTPException(status_code=400, detail="Column WIP limit reached")

    # Process checklist items with IDs
    checklist = [
        {"id": db.generate_id(), "text": item.text, "completed": item.completed}
        for item in data.checklist
    ]

    card = {
        "id": db.generate_id(),
        "column_id": data.column_id,
        "title": data.title,
        "description": data.description,
        "position": data.position,
        "assignee_id": data.assignee_id,
        "due_date": data.due_date,
        "labels": data.labels,
        "priority": data.priority,
        "checklist": checklist,
        "created_at": db.timestamp(),
        "updated_at": db.timestamp()
    }
    db.cards.insert(card)

    # Log activity for analytics
    db.log_activity(
        card_id=card["id"],
        board_id=column["board_id"],
        action="created",
        to_column_id=data.column_id
    )

    # Trigger webhooks
    await trigger_webhooks(db, "card.created", card)

    return card


@router.get("/{card_id}")
async def get_card(card_id: str):
    """Get a single card"""
    db.initialize()
    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.patch("/{card_id}")
async def update_card(card_id: str, data: CardUpdate):
    """Update a card"""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    updates = data.model_dump(exclude_unset=True)
    old_column_id = card["column_id"]

    # Check WIP limit if moving to new column
    if "column_id" in updates and updates["column_id"] != old_column_id:
        new_column = db.columns.get(Q.id == updates["column_id"])
        if new_column and new_column.get("wip_limit"):
            current_cards = len(db.cards.search(Q.column_id == updates["column_id"]))
            if current_cards >= new_column["wip_limit"]:
                raise HTTPException(status_code=400, detail="Target column WIP limit reached")

    updates["updated_at"] = db.timestamp()
    db.cards.update(updates, Q.id == card_id)

    updated_card = {**card, **updates}

    # Log activity and trigger webhooks
    if "column_id" in updates and updates["column_id"] != old_column_id:
        # Get board_id from new column
        new_column = db.columns.get(Q.id == updates["column_id"])
        db.log_activity(
            card_id=card_id,
            board_id=new_column["board_id"],
            action="moved",
            from_column_id=old_column_id,
            to_column_id=updates["column_id"]
        )
        await trigger_webhooks(db, "card.moved", {
            "card": updated_card,
            "from_column": old_column_id,
            "to_column": updates["column_id"]
        })
    else:
        await trigger_webhooks(db, "card.updated", updated_card)

    return updated_card


@router.delete("/{card_id}")
async def delete_card(card_id: str):
    """Delete a card"""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Get board_id for activity logging
    column = db.columns.get(Q.id == card["column_id"])

    db.cards.remove(Q.id == card_id)

    # Log activity for analytics
    if column:
        db.log_activity(
            card_id=card_id,
            board_id=column["board_id"],
            action="deleted",
            from_column_id=card["column_id"]
        )

    await trigger_webhooks(db, "card.deleted", {"id": card_id})

    return {"deleted": True}


@router.post("/{card_id}/move")
async def move_card(card_id: str, column_id: str, position: int = 0):
    """Move a card to a different column"""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    column = db.columns.get(Q.id == column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")

    # Check WIP limit
    if column.get("wip_limit") and card["column_id"] != column_id:
        current_cards = len(db.cards.search(Q.column_id == column_id))
        if current_cards >= column["wip_limit"]:
            raise HTTPException(status_code=400, detail="Column WIP limit reached")

    old_column_id = card["column_id"]
    db.cards.update({
        "column_id": column_id,
        "position": position,
        "updated_at": db.timestamp()
    }, Q.id == card_id)

    updated_card = db.cards.get(Q.id == card_id)

    # Log activity for analytics (only if actually moving to different column)
    if old_column_id != column_id:
        db.log_activity(
            card_id=card_id,
            board_id=column["board_id"],
            action="moved",
            from_column_id=old_column_id,
            to_column_id=column_id
        )

    await trigger_webhooks(db, "card.moved", {
        "card": updated_card,
        "from_column": old_column_id,
        "to_column": column_id
    })

    return updated_card


# =============================================================================
# Checklist Routes
# =============================================================================

@router.post("/{card_id}/checklist")
async def add_checklist_item(card_id: str, data: ChecklistItemCreate):
    """Add a checklist item to a card"""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    checklist = card.get("checklist", [])
    new_item = {
        "id": db.generate_id(),
        "text": data.text,
        "completed": data.completed
    }
    checklist.append(new_item)

    db.cards.update({
        "checklist": checklist,
        "updated_at": db.timestamp()
    }, Q.id == card_id)

    return new_item


@router.patch("/{card_id}/checklist/{item_id}")
async def update_checklist_item(card_id: str, item_id: str, data: ChecklistItemUpdate):
    """Update a checklist item"""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    checklist = card.get("checklist", [])
    item_index = next((i for i, item in enumerate(checklist) if item["id"] == item_id), None)

    if item_index is None:
        raise HTTPException(status_code=404, detail="Checklist item not found")

    updates = data.model_dump(exclude_unset=True)
    checklist[item_index].update(updates)

    db.cards.update({
        "checklist": checklist,
        "updated_at": db.timestamp()
    }, Q.id == card_id)

    return checklist[item_index]


@router.delete("/{card_id}/checklist/{item_id}")
async def delete_checklist_item(card_id: str, item_id: str):
    """Delete a checklist item"""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    checklist = card.get("checklist", [])
    new_checklist = [item for item in checklist if item["id"] != item_id]

    if len(new_checklist) == len(checklist):
        raise HTTPException(status_code=404, detail="Checklist item not found")

    db.cards.update({
        "checklist": new_checklist,
        "updated_at": db.timestamp()
    }, Q.id == card_id)

    return {"deleted": True}


@router.post("/{card_id}/checklist/{item_id}/toggle")
async def toggle_checklist_item(card_id: str, item_id: str):
    """Toggle a checklist item's completed status"""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    checklist = card.get("checklist", [])
    item_index = next((i for i, item in enumerate(checklist) if item["id"] == item_id), None)

    if item_index is None:
        raise HTTPException(status_code=404, detail="Checklist item not found")

    checklist[item_index]["completed"] = not checklist[item_index]["completed"]

    db.cards.update({
        "checklist": checklist,
        "updated_at": db.timestamp()
    }, Q.id == card_id)

    return checklist[item_index]
