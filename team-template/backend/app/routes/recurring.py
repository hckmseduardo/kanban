"""
Recurring Cards API

Auto-create cards on a schedule.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Literal
from datetime import datetime, timedelta
from pathlib import Path
import os
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


class RecurringCardCreate(BaseModel):
    name: str
    description: Optional[str] = None
    title_template: str
    card_description: Optional[str] = None
    column_id: str
    labels: Optional[List[str]] = None
    priority: Optional[str] = None
    assignee_id: Optional[str] = None
    frequency: Literal["daily", "weekly", "biweekly", "monthly", "quarterly", "yearly"]
    day_of_week: Optional[int] = None  # 0=Monday, 6=Sunday (for weekly)
    day_of_month: Optional[int] = None  # 1-31 (for monthly)
    time_of_day: str = "09:00"  # HH:MM
    due_days_after_creation: Optional[int] = None
    enabled: bool = True


class RecurringCardUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    title_template: Optional[str] = None
    card_description: Optional[str] = None
    column_id: Optional[str] = None
    labels: Optional[List[str]] = None
    priority: Optional[str] = None
    assignee_id: Optional[str] = None
    frequency: Optional[Literal["daily", "weekly", "biweekly", "monthly", "quarterly", "yearly"]] = None
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    time_of_day: Optional[str] = None
    due_days_after_creation: Optional[int] = None
    enabled: Optional[bool] = None


def calculate_next_run(
    frequency: str,
    day_of_week: Optional[int],
    day_of_month: Optional[int],
    time_of_day: str,
    from_date: Optional[datetime] = None
) -> datetime:
    """Calculate the next run time for a recurring card."""
    now = from_date or datetime.now()
    hour, minute = map(int, time_of_day.split(":"))

    if frequency == "daily":
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)

    elif frequency == "weekly":
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        target_day = day_of_week or 0
        days_ahead = target_day - now.weekday()
        if days_ahead < 0 or (days_ahead == 0 and next_run <= now):
            days_ahead += 7
        next_run += timedelta(days=days_ahead)

    elif frequency == "biweekly":
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        target_day = day_of_week or 0
        days_ahead = target_day - now.weekday()
        if days_ahead < 0 or (days_ahead == 0 and next_run <= now):
            days_ahead += 14
        next_run += timedelta(days=days_ahead)

    elif frequency == "monthly":
        target_day = day_of_month or 1
        next_run = now.replace(day=min(target_day, 28), hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            if now.month == 12:
                next_run = next_run.replace(year=now.year + 1, month=1)
            else:
                next_run = next_run.replace(month=now.month + 1)

    elif frequency == "quarterly":
        target_day = day_of_month or 1
        current_quarter = (now.month - 1) // 3
        next_quarter_month = (current_quarter + 1) * 3 + 1
        if next_quarter_month > 12:
            next_run = datetime(now.year + 1, 1, min(target_day, 28), hour, minute)
        else:
            next_run = datetime(now.year, next_quarter_month, min(target_day, 28), hour, minute)

    elif frequency == "yearly":
        target_day = day_of_month or 1
        next_run = now.replace(day=min(target_day, 28), hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run = next_run.replace(year=now.year + 1)

    else:
        next_run = now + timedelta(days=1)

    return next_run


@router.get("/boards/{board_id}/recurring-cards")
async def list_recurring_cards(board_id: str):
    """List all recurring card rules for a board."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    recurring = db.recurring_cards.search(Q.board_id == board_id)

    return {
        "board_id": board_id,
        "recurring_cards": recurring,
        "count": len(recurring)
    }


@router.post("/boards/{board_id}/recurring-cards")
async def create_recurring_card(board_id: str, recurring: RecurringCardCreate):
    """Create a new recurring card rule."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    column = db.columns.get(Q.id == recurring.column_id)
    if not column or column.get("board_id") != board_id:
        raise HTTPException(status_code=404, detail="Column not found")

    next_run = calculate_next_run(
        recurring.frequency,
        recurring.day_of_week,
        recurring.day_of_month,
        recurring.time_of_day
    )

    new_recurring = {
        "id": db.generate_id(),
        "board_id": board_id,
        "name": recurring.name,
        "description": recurring.description or "",
        "title_template": recurring.title_template,
        "card_description": recurring.card_description or "",
        "column_id": recurring.column_id,
        "labels": recurring.labels or [],
        "priority": recurring.priority,
        "assignee_id": recurring.assignee_id,
        "frequency": recurring.frequency,
        "day_of_week": recurring.day_of_week,
        "day_of_month": recurring.day_of_month,
        "time_of_day": recurring.time_of_day,
        "due_days_after_creation": recurring.due_days_after_creation,
        "enabled": recurring.enabled,
        "next_run": next_run.isoformat(),
        "last_run": None,
        "run_count": 0,
        "created_at": db.timestamp()
    }

    db.recurring_cards.insert(new_recurring)

    return new_recurring


@router.get("/boards/{board_id}/recurring-cards/{recurring_id}")
async def get_recurring_card(board_id: str, recurring_id: str):
    """Get a specific recurring card rule."""
    db.initialize()

    recurring = db.recurring_cards.get(
        (Q.id == recurring_id) & (Q.board_id == board_id)
    )

    if not recurring:
        raise HTTPException(status_code=404, detail="Recurring card not found")

    return recurring


@router.patch("/boards/{board_id}/recurring-cards/{recurring_id}")
async def update_recurring_card(board_id: str, recurring_id: str, update: RecurringCardUpdate):
    """Update a recurring card rule."""
    db.initialize()

    recurring = db.recurring_cards.get(
        (Q.id == recurring_id) & (Q.board_id == board_id)
    )

    if not recurring:
        raise HTTPException(status_code=404, detail="Recurring card not found")

    updates = {}

    if update.name is not None:
        updates["name"] = update.name
    if update.description is not None:
        updates["description"] = update.description
    if update.title_template is not None:
        updates["title_template"] = update.title_template
    if update.card_description is not None:
        updates["card_description"] = update.card_description
    if update.column_id is not None:
        column = db.columns.get(Q.id == update.column_id)
        if not column:
            raise HTTPException(status_code=404, detail="Column not found")
        updates["column_id"] = update.column_id
    if update.labels is not None:
        updates["labels"] = update.labels
    if update.priority is not None:
        updates["priority"] = update.priority
    if update.assignee_id is not None:
        updates["assignee_id"] = update.assignee_id
    if update.frequency is not None:
        updates["frequency"] = update.frequency
    if update.day_of_week is not None:
        updates["day_of_week"] = update.day_of_week
    if update.day_of_month is not None:
        updates["day_of_month"] = update.day_of_month
    if update.time_of_day is not None:
        updates["time_of_day"] = update.time_of_day
    if update.due_days_after_creation is not None:
        updates["due_days_after_creation"] = update.due_days_after_creation
    if update.enabled is not None:
        updates["enabled"] = update.enabled

    # Recalculate next run if schedule changed
    if any(k in updates for k in ["frequency", "day_of_week", "day_of_month", "time_of_day"]):
        next_run = calculate_next_run(
            updates.get("frequency", recurring["frequency"]),
            updates.get("day_of_week", recurring.get("day_of_week")),
            updates.get("day_of_month", recurring.get("day_of_month")),
            updates.get("time_of_day", recurring["time_of_day"])
        )
        updates["next_run"] = next_run.isoformat()

    updates["updated_at"] = db.timestamp()

    db.recurring_cards.update(updates, Q.id == recurring_id)

    return {**recurring, **updates}


@router.delete("/boards/{board_id}/recurring-cards/{recurring_id}")
async def delete_recurring_card(board_id: str, recurring_id: str):
    """Delete a recurring card rule."""
    db.initialize()

    recurring = db.recurring_cards.get(
        (Q.id == recurring_id) & (Q.board_id == board_id)
    )

    if not recurring:
        raise HTTPException(status_code=404, detail="Recurring card not found")

    db.recurring_cards.remove(Q.id == recurring_id)

    return {"message": "Recurring card rule deleted"}


@router.post("/boards/{board_id}/recurring-cards/{recurring_id}/toggle")
async def toggle_recurring_card(board_id: str, recurring_id: str):
    """Toggle recurring card enabled/disabled."""
    db.initialize()

    recurring = db.recurring_cards.get(
        (Q.id == recurring_id) & (Q.board_id == board_id)
    )

    if not recurring:
        raise HTTPException(status_code=404, detail="Recurring card not found")

    new_enabled = not recurring.get("enabled", True)

    updates = {
        "enabled": new_enabled,
        "updated_at": db.timestamp()
    }

    if new_enabled:
        # Recalculate next run when re-enabling
        next_run = calculate_next_run(
            recurring["frequency"],
            recurring.get("day_of_week"),
            recurring.get("day_of_month"),
            recurring["time_of_day"]
        )
        updates["next_run"] = next_run.isoformat()

    db.recurring_cards.update(updates, Q.id == recurring_id)

    return {"enabled": new_enabled}


@router.post("/boards/{board_id}/recurring-cards/{recurring_id}/run-now")
async def run_recurring_card_now(board_id: str, recurring_id: str):
    """Manually trigger a recurring card to create a card now."""
    db.initialize()

    recurring = db.recurring_cards.get(
        (Q.id == recurring_id) & (Q.board_id == board_id)
    )

    if not recurring:
        raise HTTPException(status_code=404, detail="Recurring card not found")

    column = db.columns.get(Q.id == recurring["column_id"])
    if not column:
        raise HTTPException(status_code=404, detail="Target column not found")

    # Get position in column
    existing_cards = db.cards.search(Q.column_id == recurring["column_id"])
    max_position = max([c.get("position", 0) for c in existing_cards], default=-1)

    # Calculate due date
    due_date = None
    if recurring.get("due_days_after_creation"):
        due = datetime.now() + timedelta(days=recurring["due_days_after_creation"])
        due_date = due.strftime("%Y-%m-%d")

    # Format title with date
    now = datetime.now()
    title = recurring["title_template"]
    title = title.replace("{date}", now.strftime("%Y-%m-%d"))
    title = title.replace("{month}", now.strftime("%B"))
    title = title.replace("{week}", str(now.isocalendar()[1]))
    title = title.replace("{year}", str(now.year))

    # Create new card
    new_card = {
        "id": db.generate_id(),
        "title": title,
        "description": recurring.get("card_description", ""),
        "column_id": recurring["column_id"],
        "board_id": board_id,
        "position": max_position + 1,
        "labels": recurring.get("labels", []),
        "priority": recurring.get("priority"),
        "assignee_id": recurring.get("assignee_id"),
        "due_date": due_date,
        "created_from_recurring": recurring_id,
        "created_at": db.timestamp()
    }

    db.cards.insert(new_card)

    # Update recurring card stats
    next_run = calculate_next_run(
        recurring["frequency"],
        recurring.get("day_of_week"),
        recurring.get("day_of_month"),
        recurring["time_of_day"]
    )

    db.recurring_cards.update({
        "last_run": db.timestamp(),
        "next_run": next_run.isoformat(),
        "run_count": recurring.get("run_count", 0) + 1
    }, Q.id == recurring_id)

    # Log activity
    db.log_activity(new_card["id"], board_id, "card_created", details={
        "from_recurring": recurring_id,
        "recurring_name": recurring.get("name")
    })

    return {
        "message": "Card created from recurring rule",
        "card": new_card,
        "next_run": next_run.isoformat()
    }


@router.get("/recurring-cards/due")
async def get_due_recurring_cards():
    """Get all recurring cards that are due to run (for cron job)."""
    db.initialize()

    now = datetime.now()
    due_cards = []

    all_recurring = db.recurring_cards.all()

    for recurring in all_recurring:
        if not recurring.get("enabled"):
            continue

        next_run_str = recurring.get("next_run")
        if not next_run_str:
            continue

        try:
            next_run = datetime.fromisoformat(next_run_str)
            if next_run <= now:
                due_cards.append(recurring)
        except (ValueError, TypeError):
            continue

    return {
        "due_count": len(due_cards),
        "recurring_cards": due_cards
    }
