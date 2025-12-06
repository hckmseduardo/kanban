"""Column routes"""

from fastapi import APIRouter, HTTPException
from ..models.board import ColumnCreate, ColumnUpdate
from ..services.database import Database, Q
from pathlib import Path
import os

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


@router.post("")
async def create_column(data: ColumnCreate):
    """Create a new column"""
    db.initialize()

    board = db.boards.get(Q.id == data.board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    column = {
        "id": db.generate_id(),
        "board_id": data.board_id,
        "name": data.name,
        "position": data.position,
        "wip_limit": data.wip_limit,
        "created_at": db.timestamp()
    }
    db.columns.insert(column)
    return column


@router.patch("/{column_id}")
async def update_column(column_id: str, data: ColumnUpdate):
    """Update a column"""
    db.initialize()

    column = db.columns.get(Q.id == column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")

    updates = data.model_dump(exclude_unset=True)
    db.columns.update(updates, Q.id == column_id)

    return {**column, **updates}


@router.delete("/{column_id}")
async def delete_column(column_id: str):
    """Delete a column and move cards to first column"""
    db.initialize()

    column = db.columns.get(Q.id == column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")

    # Get first column of the board (fallback)
    columns = db.columns.search(Q.board_id == column["board_id"])
    other_columns = [c for c in columns if c["id"] != column_id]

    if other_columns:
        first_col = sorted(other_columns, key=lambda x: x["position"])[0]
        # Move cards to first column
        db.cards.update({"column_id": first_col["id"]}, Q.column_id == column_id)
    else:
        # Delete cards if no other columns
        db.cards.remove(Q.column_id == column_id)

    db.columns.remove(Q.id == column_id)
    return {"deleted": True}


@router.post("/{column_id}/reorder")
async def reorder_columns(column_id: str, new_position: int):
    """Reorder columns"""
    db.initialize()

    column = db.columns.get(Q.id == column_id)
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")

    columns = db.columns.search(Q.board_id == column["board_id"])
    columns = sorted(columns, key=lambda x: x["position"])

    # Remove and reinsert at new position
    old_pos = column["position"]
    for col in columns:
        if col["id"] == column_id:
            db.columns.update({"position": new_position}, Q.id == column_id)
        elif old_pos < new_position and old_pos < col["position"] <= new_position:
            db.columns.update({"position": col["position"] - 1}, Q.id == col["id"])
        elif old_pos > new_position and new_position <= col["position"] < old_pos:
            db.columns.update({"position": col["position"] + 1}, Q.id == col["id"])

    return {"reordered": True}
