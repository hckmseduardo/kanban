"""Import/Export routes for boards"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
from ..services.database import Database, Q
from pathlib import Path
import os

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


class ColumnImport(BaseModel):
    name: str
    position: int = 0
    wip_limit: Optional[int] = None
    cards: List[dict] = []


class BoardImport(BaseModel):
    name: str
    description: Optional[str] = None
    columns: List[ColumnImport] = []
    labels: List[dict] = []


@router.get("/boards/{board_id}/export")
async def export_board(board_id: str, include_archived: bool = False):
    """Export a board with all its data as JSON"""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Get columns
    columns = db.columns.search(Q.board_id == board_id)
    columns = sorted(columns, key=lambda x: x.get("position", 0))

    # Get cards for each column
    export_columns = []
    for column in columns:
        if include_archived:
            cards = db.cards.search(Q.column_id == column["id"])
        else:
            cards = db.cards.search(
                (Q.column_id == column["id"]) & (~Q.archived.exists() | (Q.archived == False))
            )
        cards = sorted(cards, key=lambda x: x.get("position", 0))

        # Get comments for each card
        export_cards = []
        for card in cards:
            comments = db.comments.search(Q.card_id == card["id"])
            comments = sorted(comments, key=lambda x: x.get("created_at", ""))

            export_card = {
                "title": card["title"],
                "description": card.get("description"),
                "position": card.get("position", 0),
                "labels": card.get("labels", []),
                "priority": card.get("priority"),
                "due_date": card.get("due_date"),
                "assignee_id": card.get("assignee_id"),
                "checklist": card.get("checklist", []),
                "archived": card.get("archived", False),
                "comments": [
                    {"text": c["text"], "author_name": c.get("author_name")}
                    for c in comments
                ]
            }
            export_cards.append(export_card)

        export_columns.append({
            "name": column["name"],
            "position": column.get("position", 0),
            "wip_limit": column.get("wip_limit"),
            "cards": export_cards
        })

    # Get labels
    labels = db.labels.search(Q.board_id == board_id)
    export_labels = [
        {"name": l["name"], "color": l["color"]}
        for l in labels
    ]

    export_data = {
        "name": board["name"],
        "description": board.get("description"),
        "columns": export_columns,
        "labels": export_labels,
        "exported_at": db.timestamp(),
        "version": "1.0"
    }

    return JSONResponse(
        content=export_data,
        headers={
            "Content-Disposition": f'attachment; filename="{board["name"]}.json"'
        }
    )


@router.post("/boards/import")
async def import_board(data: BoardImport):
    """Import a board from JSON data"""
    db.initialize()

    # Create the board
    board_id = db.generate_id()
    board = {
        "id": board_id,
        "name": data.name,
        "description": data.description,
        "created_at": db.timestamp(),
        "updated_at": db.timestamp()
    }
    db.boards.insert(board)

    # Create labels first (for reference)
    label_colors = {
        "red": {"bg": "#FEE2E2", "text": "#991B1B"},
        "orange": {"bg": "#FFEDD5", "text": "#9A3412"},
        "yellow": {"bg": "#FEF9C3", "text": "#854D0E"},
        "green": {"bg": "#DCFCE7", "text": "#166534"},
        "blue": {"bg": "#DBEAFE", "text": "#1E40AF"},
        "purple": {"bg": "#F3E8FF", "text": "#6B21A8"},
        "pink": {"bg": "#FCE7F3", "text": "#9D174D"},
        "gray": {"bg": "#F3F4F6", "text": "#374151"},
    }

    for label_data in data.labels:
        color = label_data.get("color", "blue")
        color_info = label_colors.get(color, label_colors["blue"])
        db.labels.insert({
            "id": db.generate_id(),
            "board_id": board_id,
            "name": label_data["name"],
            "color": color,
            "bg": color_info["bg"],
            "text": color_info["text"],
            "created_at": db.timestamp()
        })

    # Create columns and cards
    for col_data in data.columns:
        column_id = db.generate_id()
        db.columns.insert({
            "id": column_id,
            "board_id": board_id,
            "name": col_data.name,
            "position": col_data.position,
            "wip_limit": col_data.wip_limit,
            "created_at": db.timestamp()
        })

        # Create cards in this column
        for card_data in col_data.cards:
            card_id = db.generate_id()

            # Process checklist items with new IDs
            checklist = [
                {
                    "id": db.generate_id(),
                    "text": item.get("text", ""),
                    "completed": item.get("completed", False)
                }
                for item in card_data.get("checklist", [])
            ]

            db.cards.insert({
                "id": card_id,
                "column_id": column_id,
                "title": card_data.get("title", "Untitled"),
                "description": card_data.get("description"),
                "position": card_data.get("position", 0),
                "labels": card_data.get("labels", []),
                "priority": card_data.get("priority"),
                "due_date": card_data.get("due_date"),
                "assignee_id": card_data.get("assignee_id"),
                "checklist": checklist,
                "archived": card_data.get("archived", False),
                "created_at": db.timestamp(),
                "updated_at": db.timestamp()
            })

            # Import comments
            for comment_data in card_data.get("comments", []):
                db.comments.insert({
                    "id": db.generate_id(),
                    "card_id": card_id,
                    "text": comment_data.get("text", ""),
                    "author_name": comment_data.get("author_name"),
                    "created_at": db.timestamp()
                })

            # Log activity
            db.log_activity(
                card_id=card_id,
                board_id=board_id,
                action="created",
                to_column_id=column_id,
                details={"imported": True}
            )

    return {
        "id": board_id,
        "name": board["name"],
        "message": f"Board imported successfully with {len(data.columns)} columns"
    }
