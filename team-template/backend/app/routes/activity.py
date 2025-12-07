"""Activity log routes"""

from fastapi import APIRouter, HTTPException
from typing import Optional
from ..services.database import Database, Q
from pathlib import Path
import os

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


@router.get("/boards/{board_id}/activity")
async def get_board_activity(
    board_id: str,
    limit: int = 50,
    offset: int = 0,
    card_id: Optional[str] = None
):
    """Get activity log for a board"""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Get activities for this board
    if card_id:
        activities = db.activity.search(
            (Q.board_id == board_id) & (Q.card_id == card_id)
        )
    else:
        activities = db.activity.search(Q.board_id == board_id)

    # Sort by timestamp descending
    activities = sorted(activities, key=lambda x: x.get("timestamp", ""), reverse=True)

    # Get column and card names for enrichment
    columns = {col["id"]: col["name"] for col in db.columns.search(Q.board_id == board_id)}
    cards = {card["id"]: card["title"] for card in db.cards.all()}

    # Enrich activities with readable names
    enriched = []
    for activity in activities[offset:offset + limit]:
        enriched_activity = {
            **activity,
            "card_title": cards.get(activity.get("card_id"), "Unknown Card"),
            "from_column_name": columns.get(activity.get("from_column_id")) if activity.get("from_column_id") else None,
            "to_column_name": columns.get(activity.get("to_column_id")) if activity.get("to_column_id") else None,
        }
        enriched.append(enriched_activity)

    return {
        "activities": enriched,
        "total": len(activities),
        "has_more": len(activities) > offset + limit
    }


@router.get("/cards/{card_id}/activity")
async def get_card_activity(card_id: str, limit: int = 20):
    """Get activity log for a specific card"""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    activities = db.activity.search(Q.card_id == card_id)
    activities = sorted(activities, key=lambda x: x.get("timestamp", ""), reverse=True)

    # Get column names
    columns = {col["id"]: col["name"] for col in db.columns.all()}

    enriched = []
    for activity in activities[:limit]:
        enriched_activity = {
            **activity,
            "from_column_name": columns.get(activity.get("from_column_id")) if activity.get("from_column_id") else None,
            "to_column_name": columns.get(activity.get("to_column_id")) if activity.get("to_column_id") else None,
        }
        enriched.append(enriched_activity)

    return enriched
