"""
Time Tracking API

Allows users to log time entries on cards and track estimated vs actual time.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from pathlib import Path
import os
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


class TimeEntryCreate(BaseModel):
    minutes: int
    description: Optional[str] = None
    date: Optional[str] = None  # YYYY-MM-DD format, defaults to today


class TimeEstimate(BaseModel):
    estimated_minutes: int


@router.post("/cards/{card_id}/time-entries")
async def add_time_entry(card_id: str, entry: TimeEntryCreate):
    """Add a time entry to a card."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    if entry.minutes <= 0:
        raise HTTPException(status_code=400, detail="Minutes must be positive")

    time_entries = card.get("time_entries", [])
    new_entry = {
        "id": db.generate_id(),
        "minutes": entry.minutes,
        "description": entry.description or "",
        "date": entry.date or datetime.now().strftime("%Y-%m-%d"),
        "logged_at": db.timestamp()
    }
    time_entries.append(new_entry)

    # Calculate total logged time
    total_logged = sum(e["minutes"] for e in time_entries)

    db.cards.update({
        "time_entries": time_entries,
        "time_logged": total_logged
    }, Q.id == card_id)

    # Log activity
    db.log_activity(card_id, card.get("board_id", ""), "time_logged", details={
        "minutes": entry.minutes,
        "description": entry.description,
        "total_logged": total_logged
    })

    return {
        "entry": new_entry,
        "total_logged": total_logged,
        "estimated": card.get("time_estimated"),
        "entries_count": len(time_entries)
    }


@router.get("/cards/{card_id}/time-entries")
async def get_time_entries(card_id: str):
    """Get all time entries for a card."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    time_entries = card.get("time_entries", [])
    total_logged = card.get("time_logged", 0)
    estimated = card.get("time_estimated")

    # Calculate statistics
    percentage = None
    remaining = None
    if estimated and estimated > 0:
        percentage = round((total_logged / estimated) * 100, 1)
        remaining = max(0, estimated - total_logged)

    return {
        "card_id": card_id,
        "entries": sorted(time_entries, key=lambda x: x.get("logged_at", ""), reverse=True),
        "total_logged_minutes": total_logged,
        "total_logged_hours": round(total_logged / 60, 2),
        "estimated_minutes": estimated,
        "estimated_hours": round(estimated / 60, 2) if estimated else None,
        "percentage_complete": percentage,
        "remaining_minutes": remaining,
        "entries_count": len(time_entries)
    }


@router.delete("/cards/{card_id}/time-entries/{entry_id}")
async def delete_time_entry(card_id: str, entry_id: str):
    """Delete a time entry from a card."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    time_entries = card.get("time_entries", [])
    entry = next((e for e in time_entries if e["id"] == entry_id), None)

    if not entry:
        raise HTTPException(status_code=404, detail="Time entry not found")

    time_entries = [e for e in time_entries if e["id"] != entry_id]
    total_logged = sum(e["minutes"] for e in time_entries)

    db.cards.update({
        "time_entries": time_entries,
        "time_logged": total_logged
    }, Q.id == card_id)

    return {
        "message": "Time entry deleted",
        "total_logged": total_logged
    }


@router.put("/cards/{card_id}/time-estimate")
async def set_time_estimate(card_id: str, estimate: TimeEstimate):
    """Set the time estimate for a card."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    if estimate.estimated_minutes < 0:
        raise HTTPException(status_code=400, detail="Estimate must be non-negative")

    db.cards.update({
        "time_estimated": estimate.estimated_minutes
    }, Q.id == card_id)

    total_logged = card.get("time_logged", 0)

    return {
        "estimated_minutes": estimate.estimated_minutes,
        "estimated_hours": round(estimate.estimated_minutes / 60, 2),
        "total_logged": total_logged,
        "percentage_complete": round((total_logged / estimate.estimated_minutes) * 100, 1) if estimate.estimated_minutes > 0 else None
    }


@router.delete("/cards/{card_id}/time-estimate")
async def clear_time_estimate(card_id: str):
    """Clear the time estimate for a card."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    db.cards.update({
        "time_estimated": None
    }, Q.id == card_id)

    return {"message": "Time estimate cleared"}


@router.get("/boards/{board_id}/time-report")
async def get_board_time_report(board_id: str):
    """Get time tracking summary for all cards in a board."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    columns = db.columns.search(Q.board_id == board_id)

    total_estimated = 0
    total_logged = 0
    cards_with_time = []

    for column in columns:
        cards = db.cards.search(Q.column_id == column["id"])

        for card in cards:
            if card.get("archived"):
                continue

            estimated = card.get("time_estimated", 0) or 0
            logged = card.get("time_logged", 0) or 0

            if estimated > 0 or logged > 0:
                total_estimated += estimated
                total_logged += logged

                cards_with_time.append({
                    "id": card["id"],
                    "title": card["title"],
                    "column_name": column["name"],
                    "estimated_minutes": estimated,
                    "logged_minutes": logged,
                    "estimated_hours": round(estimated / 60, 2),
                    "logged_hours": round(logged / 60, 2),
                    "percentage": round((logged / estimated) * 100, 1) if estimated > 0 else None,
                    "over_estimate": logged > estimated if estimated > 0 else None
                })

    # Sort by logged time descending
    cards_with_time.sort(key=lambda x: x["logged_minutes"], reverse=True)

    return {
        "board_id": board_id,
        "board_name": board.get("name"),
        "summary": {
            "total_estimated_minutes": total_estimated,
            "total_estimated_hours": round(total_estimated / 60, 2),
            "total_logged_minutes": total_logged,
            "total_logged_hours": round(total_logged / 60, 2),
            "overall_percentage": round((total_logged / total_estimated) * 100, 1) if total_estimated > 0 else None,
            "cards_tracked": len(cards_with_time)
        },
        "cards": cards_with_time
    }
