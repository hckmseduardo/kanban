"""Board routes"""

from fastapi import APIRouter, HTTPException
from ..models.board import BoardCreate, BoardUpdate, Board
from ..services.database import Database, Q
from pathlib import Path
import os

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


@router.get("")
async def list_boards():
    """List all boards"""
    db.initialize()
    boards = db.boards.all()
    return sorted(boards, key=lambda x: x.get("created_at", ""), reverse=True)


@router.post("")
async def create_board(data: BoardCreate):
    """Create a new board"""
    db.initialize()
    board = {
        "id": db.generate_id(),
        "name": data.name,
        "description": data.description,
        "visibility": data.visibility.value,
        "created_at": db.timestamp(),
        "updated_at": db.timestamp()
    }
    db.boards.insert(board)

    # Create default columns
    default_columns = ["To Do", "In Progress", "Done"]
    for i, col_name in enumerate(default_columns):
        db.columns.insert({
            "id": db.generate_id(),
            "board_id": board["id"],
            "name": col_name,
            "position": i,
            "wip_limit": None,
            "created_at": db.timestamp()
        })

    return board


@router.get("/{board_id}")
async def get_board(board_id: str):
    """Get board with columns and cards"""
    db.initialize()
    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    columns = db.columns.search(Q.board_id == board_id)
    columns = sorted(columns, key=lambda x: x.get("position", 0))

    for col in columns:
        cards = db.cards.search(Q.column_id == col["id"])
        col["cards"] = sorted(cards, key=lambda x: x.get("position", 0))

    board["columns"] = columns
    return board


@router.patch("/{board_id}")
async def update_board(board_id: str, data: BoardUpdate):
    """Update a board"""
    db.initialize()
    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    updates = data.model_dump(exclude_unset=True)
    # Convert visibility enum to string value
    if "visibility" in updates and updates["visibility"]:
        updates["visibility"] = updates["visibility"].value
    updates["updated_at"] = db.timestamp()
    db.boards.update(updates, Q.id == board_id)

    return {**board, **updates}


@router.delete("/{board_id}")
async def delete_board(board_id: str):
    """Delete a board and all its content"""
    db.initialize()
    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Delete cards in columns
    columns = db.columns.search(Q.board_id == board_id)
    for col in columns:
        db.cards.remove(Q.column_id == col["id"])

    # Delete columns
    db.columns.remove(Q.board_id == board_id)

    # Delete board
    db.boards.remove(Q.id == board_id)

    return {"deleted": True}
