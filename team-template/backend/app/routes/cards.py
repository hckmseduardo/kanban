"""Card routes"""

from fastapi import APIRouter, HTTPException
from ..models.board import CardCreate, CardUpdate, ChecklistItemCreate, ChecklistItemUpdate
from ..services.database import Database, Q
from ..services.webhook_service import trigger_webhooks
from .websocket import broadcast_board_event
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

    # Broadcast to WebSocket clients
    await broadcast_board_event(column["board_id"], "card_created", {"card": card})

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

    # Check if moving to new column
    if "column_id" in updates and updates["column_id"] != old_column_id:
        new_column = db.columns.get(Q.id == updates["column_id"])
        # Validate target column exists
        if not new_column:
            raise HTTPException(status_code=404, detail="Target column not found")
        # Check WIP limit
        if new_column.get("wip_limit"):
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
        # Broadcast to WebSocket clients
        await broadcast_board_event(new_column["board_id"], "card_moved", {
            "card": updated_card,
            "from_column": old_column_id,
            "to_column": updates["column_id"]
        })
    else:
        await trigger_webhooks(db, "card.updated", updated_card)
        # Get board_id from current column for broadcast
        current_column = db.columns.get(Q.id == card["column_id"])
        if current_column:
            await broadcast_board_event(current_column["board_id"], "card_updated", {"card": updated_card})

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

    # Delete attachments (files and database records)
    attachments = db.attachments.search(Q.card_id == card_id)
    uploads_dir = DATA_DIR / "uploads" / "cards" / card_id
    for attachment in attachments:
        file_path = uploads_dir / attachment["filename"]
        if file_path.exists():
            file_path.unlink()
    if uploads_dir.exists():
        try:
            uploads_dir.rmdir()
        except OSError:
            pass  # Directory not empty or other error
    db.attachments.remove(Q.card_id == card_id)

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

    # Broadcast to WebSocket clients
    if column:
        await broadcast_board_event(column["board_id"], "card_deleted", {"card_id": card_id})

    return {"deleted": True}


@router.post("/{card_id}/move")
async def move_card(card_id: str, column_id: str, position: int = 0):
    """Move a card to a different column or reorder within same column"""
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
    old_position = card.get("position", 0)

    # Reorder cards in the affected columns
    if old_column_id == column_id:
        # Moving within the same column - reorder cards between old and new position
        column_cards = db.cards.search(Q.column_id == column_id)
        for c in column_cards:
            if c["id"] == card_id:
                continue
            c_pos = c.get("position", 0)
            if old_position < position:
                # Moving down: shift cards between old+1 and new position up
                if old_position < c_pos <= position:
                    db.cards.update({"position": c_pos - 1}, Q.id == c["id"])
            else:
                # Moving up: shift cards between new position and old-1 down
                if position <= c_pos < old_position:
                    db.cards.update({"position": c_pos + 1}, Q.id == c["id"])
    else:
        # Moving to different column
        # Shift cards down in source column (close the gap)
        source_cards = db.cards.search(Q.column_id == old_column_id)
        for c in source_cards:
            if c["id"] == card_id:
                continue
            c_pos = c.get("position", 0)
            if c_pos > old_position:
                db.cards.update({"position": c_pos - 1}, Q.id == c["id"])

        # Shift cards down in destination column (make room)
        dest_cards = db.cards.search(Q.column_id == column_id)
        for c in dest_cards:
            c_pos = c.get("position", 0)
            if c_pos >= position:
                db.cards.update({"position": c_pos + 1}, Q.id == c["id"])

    # Update the moved card
    db.cards.update({
        "column_id": column_id,
        "position": position,
        "updated_at": db.timestamp()
    }, Q.id == card_id)

    updated_card = db.cards.get(Q.id == card_id)

    # Log activity, trigger webhooks and broadcast only if actually moving to different column
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

        # Broadcast to WebSocket clients
        await broadcast_board_event(column["board_id"], "card_moved", {
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


# =============================================================================
# Archive Routes
# =============================================================================

@router.post("/{card_id}/archive")
async def archive_card(card_id: str):
    """Archive a card (soft delete)"""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    if card.get("archived"):
        raise HTTPException(status_code=400, detail="Card is already archived")

    column = db.columns.get(Q.id == card["column_id"])

    db.cards.update({
        "archived": True,
        "archived_at": db.timestamp(),
        "updated_at": db.timestamp()
    }, Q.id == card_id)

    # Log activity
    if column:
        db.log_activity(
            card_id=card_id,
            board_id=column["board_id"],
            action="archived",
            from_column_id=card["column_id"],
            details={"title": card["title"]}
        )

    return {"archived": True}


@router.post("/{card_id}/restore")
async def restore_card(card_id: str, column_id: str = None):
    """Restore an archived card"""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    if not card.get("archived"):
        raise HTTPException(status_code=400, detail="Card is not archived")

    # Use provided column_id or original column
    target_column_id = column_id or card["column_id"]
    column = db.columns.get(Q.id == target_column_id)

    if not column:
        raise HTTPException(status_code=404, detail="Target column not found")

    # Check WIP limit
    if column.get("wip_limit"):
        current_cards = len(db.cards.search(
            (Q.column_id == target_column_id) & (~Q.archived.exists() | (Q.archived == False))
        ))
        if current_cards >= column["wip_limit"]:
            raise HTTPException(status_code=400, detail="Target column WIP limit reached")

    db.cards.update({
        "archived": False,
        "archived_at": None,
        "column_id": target_column_id,
        "updated_at": db.timestamp()
    }, Q.id == card_id)

    # Log activity
    db.log_activity(
        card_id=card_id,
        board_id=column["board_id"],
        action="restored",
        to_column_id=target_column_id,
        details={"title": card["title"]}
    )

    return db.cards.get(Q.id == card_id)


# =============================================================================
# Copy Routes
# =============================================================================

@router.post("/{card_id}/copy")
async def copy_card(card_id: str, column_id: str = None, include_comments: bool = False):
    """Copy a card to the same or different column"""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Use provided column_id or same column
    target_column_id = column_id or card["column_id"]
    column = db.columns.get(Q.id == target_column_id)

    if not column:
        raise HTTPException(status_code=404, detail="Target column not found")

    # Check WIP limit
    if column.get("wip_limit"):
        current_cards = len(db.cards.search(
            (Q.column_id == target_column_id) & (~Q.archived.exists() | (Q.archived == False))
        ))
        if current_cards >= column["wip_limit"]:
            raise HTTPException(status_code=400, detail="Target column WIP limit reached")

    # Create new card with copied data
    new_card_id = db.generate_id()

    # Copy checklist items with new IDs
    new_checklist = [
        {"id": db.generate_id(), "text": item["text"], "completed": False}
        for item in card.get("checklist", [])
    ]

    new_card = {
        "id": new_card_id,
        "column_id": target_column_id,
        "title": f"{card['title']} (Copy)",
        "description": card.get("description"),
        "position": len(db.cards.search(Q.column_id == target_column_id)),
        "assignee_id": card.get("assignee_id"),
        "due_date": card.get("due_date"),
        "labels": card.get("labels", []).copy(),
        "priority": card.get("priority"),
        "checklist": new_checklist,
        "archived": False,
        "created_at": db.timestamp(),
        "updated_at": db.timestamp()
    }
    db.cards.insert(new_card)

    # Optionally copy comments
    if include_comments:
        comments = db.comments.search(Q.card_id == card_id)
        for comment in comments:
            db.comments.insert({
                "id": db.generate_id(),
                "card_id": new_card_id,
                "text": comment["text"],
                "author_name": comment.get("author_name"),
                "created_at": db.timestamp()
            })

    # Log activity
    db.log_activity(
        card_id=new_card_id,
        board_id=column["board_id"],
        action="created",
        to_column_id=target_column_id,
        details={"copied_from": card_id, "original_title": card["title"]}
    )

    await trigger_webhooks(db, "card.created", new_card)

    return new_card


# =============================================================================
# Bulk Operations
# =============================================================================

from pydantic import BaseModel
from typing import List


class BulkMoveRequest(BaseModel):
    card_ids: List[str]
    column_id: str


class BulkArchiveRequest(BaseModel):
    card_ids: List[str]


class BulkDeleteRequest(BaseModel):
    card_ids: List[str]


@router.post("/bulk/move")
async def bulk_move_cards(data: BulkMoveRequest):
    """Move multiple cards to a column"""
    db.initialize()

    column = db.columns.get(Q.id == data.column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")

    # Check WIP limit
    if column.get("wip_limit"):
        current_cards = len(db.cards.search(
            (Q.column_id == data.column_id) & (~Q.archived.exists() | (Q.archived == False))
        ))
        if current_cards + len(data.card_ids) > column["wip_limit"]:
            raise HTTPException(status_code=400, detail="Would exceed column WIP limit")

    moved = []
    position = len(db.cards.search(Q.column_id == data.column_id))

    for card_id in data.card_ids:
        card = db.cards.get(Q.id == card_id)
        if card and card["column_id"] != data.column_id:
            old_column_id = card["column_id"]
            db.cards.update({
                "column_id": data.column_id,
                "position": position,
                "updated_at": db.timestamp()
            }, Q.id == card_id)

            db.log_activity(
                card_id=card_id,
                board_id=column["board_id"],
                action="moved",
                from_column_id=old_column_id,
                to_column_id=data.column_id,
                details={"bulk_operation": True}
            )
            moved.append(card_id)
            position += 1

    return {"moved": moved, "count": len(moved)}


@router.post("/bulk/archive")
async def bulk_archive_cards(data: BulkArchiveRequest):
    """Archive multiple cards"""
    db.initialize()

    archived = []
    for card_id in data.card_ids:
        card = db.cards.get(Q.id == card_id)
        if card and not card.get("archived"):
            column = db.columns.get(Q.id == card["column_id"])

            db.cards.update({
                "archived": True,
                "archived_at": db.timestamp(),
                "updated_at": db.timestamp()
            }, Q.id == card_id)

            if column:
                db.log_activity(
                    card_id=card_id,
                    board_id=column["board_id"],
                    action="archived",
                    from_column_id=card["column_id"],
                    details={"bulk_operation": True}
                )
            archived.append(card_id)

    return {"archived": archived, "count": len(archived)}


@router.post("/bulk/delete")
async def bulk_delete_cards(data: BulkDeleteRequest):
    """Delete multiple cards permanently"""
    db.initialize()

    deleted = []
    for card_id in data.card_ids:
        card = db.cards.get(Q.id == card_id)
        if card:
            column = db.columns.get(Q.id == card["column_id"])

            # Delete attachments
            attachments = db.attachments.search(Q.card_id == card_id)
            uploads_dir = DATA_DIR / "uploads" / "cards" / card_id
            for attachment in attachments:
                file_path = uploads_dir / attachment["filename"]
                if file_path.exists():
                    file_path.unlink()
            if uploads_dir.exists():
                try:
                    uploads_dir.rmdir()
                except OSError:
                    pass
            db.attachments.remove(Q.card_id == card_id)

            # Delete comments
            db.comments.remove(Q.card_id == card_id)

            # Delete the card
            db.cards.remove(Q.id == card_id)

            if column:
                db.log_activity(
                    card_id=card_id,
                    board_id=column["board_id"],
                    action="deleted",
                    from_column_id=card["column_id"],
                    details={"bulk_operation": True}
                )
            deleted.append(card_id)

    return {"deleted": deleted, "count": len(deleted)}
