"""
Due Date Reminders API

Provides endpoints to fetch cards with upcoming or overdue due dates.
"""
from fastapi import APIRouter, Query as QueryParam
from datetime import datetime, timedelta
from pathlib import Path
import os
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


@router.get("/boards/{board_id}/reminders")
async def get_board_reminders(
    board_id: str,
    days_ahead: int = QueryParam(default=7, ge=1, le=30),
    include_overdue: bool = QueryParam(default=True)
):
    """Get cards with due dates within the specified time window."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        return {"error": "Board not found"}

    columns = db.columns.search(Q.board_id == board_id)
    column_map = {col["id"]: col["name"] for col in columns}

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    end_date = today + timedelta(days=days_ahead)

    reminders = {"overdue": [], "today": [], "tomorrow": [], "upcoming": []}

    for column in columns:
        cards = db.cards.search(Q.column_id == column["id"])
        for card in cards:
            if card.get("archived"):
                continue
            due_date_str = card.get("due_date")
            if not due_date_str:
                continue
            try:
                due_date = datetime.strptime(due_date_str, "%Y-%m-%d")
            except ValueError:
                continue

            card_info = {
                "id": card["id"],
                "title": card["title"],
                "due_date": due_date_str,
                "column_id": column["id"],
                "column_name": column_map.get(column["id"], "Unknown"),
                "priority": card.get("priority"),
                "days_until_due": (due_date - today).days
            }

            if due_date < today and include_overdue:
                card_info["days_overdue"] = (today - due_date).days
                reminders["overdue"].append(card_info)
            elif due_date == today:
                reminders["today"].append(card_info)
            elif due_date == tomorrow:
                reminders["tomorrow"].append(card_info)
            elif due_date <= end_date:
                reminders["upcoming"].append(card_info)

    for key in reminders:
        if key == "overdue":
            reminders[key].sort(key=lambda x: x["days_overdue"], reverse=True)
        else:
            reminders[key].sort(key=lambda x: x["due_date"])

    total = sum(len(v) for v in reminders.values())
    return {
        "board_id": board_id,
        "board_name": board.get("name"),
        "generated_at": now.isoformat(),
        "days_ahead": days_ahead,
        "total": total,
        "counts": {k: len(v) for k, v in reminders.items()},
        "reminders": reminders
    }


@router.get("/reminders/summary")
async def get_reminders_summary():
    """Get a quick summary of upcoming due dates."""
    db.initialize()

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    week_end = today + timedelta(days=7)

    counts = {"overdue": 0, "today": 0, "tomorrow": 0, "this_week": 0}
    all_cards = db.cards.all()

    for card in all_cards:
        if card.get("archived"):
            continue
        due_date_str = card.get("due_date")
        if not due_date_str:
            continue
        try:
            due_date = datetime.strptime(due_date_str, "%Y-%m-%d")
        except ValueError:
            continue

        if due_date < today:
            counts["overdue"] += 1
        elif due_date == today:
            counts["today"] += 1
        elif due_date == tomorrow:
            counts["tomorrow"] += 1
        elif due_date <= week_end:
            counts["this_week"] += 1

    urgency = "none"
    if counts["overdue"] > 0:
        urgency = "critical"
    elif counts["today"] > 0:
        urgency = "high"
    elif counts["tomorrow"] > 0:
        urgency = "medium"
    elif counts["this_week"] > 0:
        urgency = "low"

    return {
        "generated_at": now.isoformat(),
        "counts": counts,
        "total": sum(counts.values()),
        "urgency": urgency
    }
