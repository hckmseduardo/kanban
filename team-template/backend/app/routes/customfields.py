"""
Custom Fields API

Allows boards to define custom fields that can be used on cards.
Supports different field types: text, number, date, select (dropdown), checkbox.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Any
from pathlib import Path
import os
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


class FieldOption(BaseModel):
    value: str
    label: str
    color: Optional[str] = None


class CustomFieldCreate(BaseModel):
    name: str
    field_type: str  # text, number, date, select, checkbox
    description: Optional[str] = None
    options: Optional[List[FieldOption]] = None  # For select type
    required: bool = False


class CustomFieldUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    options: Optional[List[FieldOption]] = None
    required: Optional[bool] = None


class FieldValueUpdate(BaseModel):
    value: Any


@router.get("/boards/{board_id}/fields")
async def list_custom_fields(board_id: str):
    """Get all custom fields defined for a board."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    fields = board.get("custom_fields", [])

    return {
        "board_id": board_id,
        "fields": fields,
        "count": len(fields)
    }


@router.post("/boards/{board_id}/fields")
async def create_custom_field(board_id: str, field: CustomFieldCreate):
    """Create a new custom field for a board."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    valid_types = ["text", "number", "date", "select", "checkbox"]
    if field.field_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid field type. Must be one of: {', '.join(valid_types)}")

    if field.field_type == "select" and not field.options:
        raise HTTPException(status_code=400, detail="Select fields require options")

    custom_fields = board.get("custom_fields", [])

    # Check for duplicate name
    if any(f["name"].lower() == field.name.lower() for f in custom_fields):
        raise HTTPException(status_code=400, detail="A field with this name already exists")

    new_field = {
        "id": db.generate_id(),
        "name": field.name,
        "field_type": field.field_type,
        "description": field.description or "",
        "options": [o.model_dump() for o in field.options] if field.options else [],
        "required": field.required,
        "created_at": db.timestamp()
    }

    custom_fields.append(new_field)
    db.boards.update({"custom_fields": custom_fields}, Q.id == board_id)

    return new_field


@router.patch("/boards/{board_id}/fields/{field_id}")
async def update_custom_field(board_id: str, field_id: str, update: CustomFieldUpdate):
    """Update a custom field."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    custom_fields = board.get("custom_fields", [])
    field_index = next((i for i, f in enumerate(custom_fields) if f["id"] == field_id), None)

    if field_index is None:
        raise HTTPException(status_code=404, detail="Field not found")

    field = custom_fields[field_index]

    if update.name is not None:
        # Check for duplicate name (excluding current field)
        if any(f["name"].lower() == update.name.lower() and f["id"] != field_id for f in custom_fields):
            raise HTTPException(status_code=400, detail="A field with this name already exists")
        field["name"] = update.name

    if update.description is not None:
        field["description"] = update.description

    if update.options is not None:
        if field["field_type"] != "select":
            raise HTTPException(status_code=400, detail="Options can only be set for select fields")
        field["options"] = [o.model_dump() for o in update.options]

    if update.required is not None:
        field["required"] = update.required

    field["updated_at"] = db.timestamp()
    custom_fields[field_index] = field

    db.boards.update({"custom_fields": custom_fields}, Q.id == board_id)

    return field


@router.delete("/boards/{board_id}/fields/{field_id}")
async def delete_custom_field(board_id: str, field_id: str):
    """Delete a custom field from a board. Also removes field values from all cards."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    custom_fields = board.get("custom_fields", [])
    field = next((f for f in custom_fields if f["id"] == field_id), None)

    if not field:
        raise HTTPException(status_code=404, detail="Field not found")

    # Remove field from board
    custom_fields = [f for f in custom_fields if f["id"] != field_id]
    db.boards.update({"custom_fields": custom_fields}, Q.id == board_id)

    # Remove field values from all cards
    columns = db.columns.search(Q.board_id == board_id)
    for column in columns:
        cards = db.cards.search(Q.column_id == column["id"])
        for card in cards:
            custom_field_values = card.get("custom_field_values", {})
            if field_id in custom_field_values:
                del custom_field_values[field_id]
                db.cards.update({"custom_field_values": custom_field_values}, Q.id == card["id"])

    return {"message": "Field deleted"}


@router.put("/cards/{card_id}/fields/{field_id}")
async def set_field_value(card_id: str, field_id: str, value_update: FieldValueUpdate):
    """Set a custom field value on a card."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Get the column to find the board
    column = db.columns.get(Q.id == card.get("column_id"))
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")

    # Get the board and verify field exists
    board = db.boards.get(Q.id == column.get("board_id"))
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    field = next((f for f in board.get("custom_fields", []) if f["id"] == field_id), None)
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")

    # Validate value based on field type
    value = value_update.value
    field_type = field["field_type"]

    if field_type == "number" and value is not None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid number value")

    if field_type == "checkbox":
        value = bool(value)

    if field_type == "select" and value is not None:
        valid_options = [o["value"] for o in field.get("options", [])]
        if value not in valid_options:
            raise HTTPException(status_code=400, detail=f"Invalid option. Must be one of: {', '.join(valid_options)}")

    # Update card's custom field values
    custom_field_values = card.get("custom_field_values", {})
    custom_field_values[field_id] = value
    db.cards.update({"custom_field_values": custom_field_values}, Q.id == card_id)

    return {
        "card_id": card_id,
        "field_id": field_id,
        "field_name": field["name"],
        "value": value
    }


@router.delete("/cards/{card_id}/fields/{field_id}")
async def clear_field_value(card_id: str, field_id: str):
    """Clear a custom field value from a card."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    custom_field_values = card.get("custom_field_values", {})
    if field_id in custom_field_values:
        del custom_field_values[field_id]
        db.cards.update({"custom_field_values": custom_field_values}, Q.id == card_id)

    return {"message": "Field value cleared"}


@router.get("/cards/{card_id}/fields")
async def get_card_field_values(card_id: str):
    """Get all custom field values for a card, with field metadata."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Get the column to find the board
    column = db.columns.get(Q.id == card.get("column_id"))
    if not column:
        return {"card_id": card_id, "fields": [], "values": {}}

    # Get the board and its custom fields
    board = db.boards.get(Q.id == column.get("board_id"))
    if not board:
        return {"card_id": card_id, "fields": [], "values": {}}

    custom_fields = board.get("custom_fields", [])
    custom_field_values = card.get("custom_field_values", {})

    # Build response with field metadata and values
    fields_with_values = []
    for field in custom_fields:
        fields_with_values.append({
            "id": field["id"],
            "name": field["name"],
            "field_type": field["field_type"],
            "description": field.get("description"),
            "options": field.get("options", []),
            "required": field.get("required", False),
            "value": custom_field_values.get(field["id"])
        })

    return {
        "card_id": card_id,
        "fields": fields_with_values,
        "values": custom_field_values
    }
