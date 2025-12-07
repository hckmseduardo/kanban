"""
Board Analytics Dashboard API

Provides charts and metrics for board performance analysis.
"""
from fastapi import APIRouter, HTTPException
from typing import Optional
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
import os
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


@router.get("/boards/{board_id}/analytics/overview")
async def get_board_overview(board_id: str):
    """Get board overview statistics."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    columns = db.columns.search(Q.board_id == board_id)
    column_ids = [c["id"] for c in columns]

    total_cards = 0
    active_cards = 0
    archived_cards = 0
    overdue_cards = 0
    blocked_cards = 0
    cards_with_due_date = 0
    completed_cards = 0

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    for col in columns:
        cards = db.cards.search(Q.column_id == col["id"])
        for card in cards:
            total_cards += 1
            if card.get("archived"):
                archived_cards += 1
            else:
                active_cards += 1
                if card.get("due_date"):
                    cards_with_due_date += 1
                    try:
                        due = datetime.strptime(card["due_date"], "%Y-%m-%d")
                        if due < today:
                            overdue_cards += 1
                    except ValueError:
                        pass
                if card.get("blocked_by"):
                    blocked_cards += 1
                if card.get("completed"):
                    completed_cards += 1

    # Column breakdown
    column_breakdown = []
    for col in sorted(columns, key=lambda x: x.get("position", 0)):
        cards = db.cards.search(Q.column_id == col["id"])
        active = [c for c in cards if not c.get("archived")]
        column_breakdown.append({
            "id": col["id"],
            "name": col["name"],
            "card_count": len(active),
            "wip_limit": col.get("wip_limit")
        })

    return {
        "board_id": board_id,
        "board_name": board.get("name"),
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_cards": total_cards,
            "active_cards": active_cards,
            "archived_cards": archived_cards,
            "completed_cards": completed_cards,
            "overdue_cards": overdue_cards,
            "blocked_cards": blocked_cards,
            "cards_with_due_date": cards_with_due_date
        },
        "columns": column_breakdown
    }


@router.get("/boards/{board_id}/analytics/burndown")
async def get_burndown_chart(
    board_id: str,
    days: int = 30,
    done_column_name: str = "Done"
):
    """Get burndown chart data."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    columns = db.columns.search(Q.board_id == board_id)
    done_column = next((c for c in columns if c.get("name", "").lower() == done_column_name.lower()), None)

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = today - timedelta(days=days)

    # Get activity log for card movements to done column
    activities = db.activity.search(Q.board_id == board_id)

    # Track cards completed per day
    completed_per_day = defaultdict(int)
    created_per_day = defaultdict(int)

    for activity in activities:
        try:
            activity_date = datetime.fromisoformat(activity.get("timestamp", "")).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        except (ValueError, TypeError):
            continue

        if activity_date < start_date:
            continue

        date_str = activity_date.strftime("%Y-%m-%d")

        if activity.get("action") == "card_created":
            created_per_day[date_str] += 1
        elif activity.get("action") == "card_moved" and done_column:
            details = activity.get("details", {})
            if details.get("to_column_id") == done_column["id"]:
                completed_per_day[date_str] += 1

    # Build chart data
    chart_data = []
    current = start_date
    total_remaining = 0

    # Count initial cards (before start date)
    for col in columns:
        cards = db.cards.search(Q.column_id == col["id"])
        for card in cards:
            if not card.get("archived"):
                total_remaining += 1

    while current <= today:
        date_str = current.strftime("%Y-%m-%d")
        total_remaining += created_per_day.get(date_str, 0)
        total_remaining -= completed_per_day.get(date_str, 0)

        chart_data.append({
            "date": date_str,
            "remaining": max(0, total_remaining),
            "completed": completed_per_day.get(date_str, 0),
            "created": created_per_day.get(date_str, 0)
        })

        current += timedelta(days=1)

    return {
        "board_id": board_id,
        "period_days": days,
        "chart_data": chart_data
    }


@router.get("/boards/{board_id}/analytics/cumulative-flow")
async def get_cumulative_flow(board_id: str, days: int = 30):
    """Get cumulative flow diagram data."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    columns = db.columns.search(Q.board_id == board_id)
    columns = sorted(columns, key=lambda x: x.get("position", 0))

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = today - timedelta(days=days)

    # For each day, count cards in each column
    # This is simplified - in production, you'd track historical snapshots

    chart_data = []
    current = start_date

    while current <= today:
        date_str = current.strftime("%Y-%m-%d")
        day_data = {"date": date_str}

        for col in columns:
            cards = db.cards.search(Q.column_id == col["id"])
            active_cards = [c for c in cards if not c.get("archived")]
            day_data[col["name"]] = len(active_cards)

        chart_data.append(day_data)
        current += timedelta(days=1)

    return {
        "board_id": board_id,
        "period_days": days,
        "columns": [c["name"] for c in columns],
        "chart_data": chart_data
    }


@router.get("/boards/{board_id}/analytics/velocity")
async def get_velocity(board_id: str, weeks: int = 8, done_column_name: str = "Done"):
    """Get velocity metrics (cards completed per week)."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    columns = db.columns.search(Q.board_id == board_id)
    done_column = next((c for c in columns if c.get("name", "").lower() == done_column_name.lower()), None)

    if not done_column:
        return {
            "board_id": board_id,
            "message": f"No column named '{done_column_name}' found",
            "velocity_data": []
        }

    today = datetime.now()
    activities = db.activity.search(Q.board_id == board_id)

    # Group by week
    weekly_completed = defaultdict(int)

    for activity in activities:
        if activity.get("action") != "card_moved":
            continue

        details = activity.get("details", {})
        if details.get("to_column_id") != done_column["id"]:
            continue

        try:
            activity_date = datetime.fromisoformat(activity.get("timestamp", ""))
            week_start = activity_date - timedelta(days=activity_date.weekday())
            week_key = week_start.strftime("%Y-%m-%d")
            weekly_completed[week_key] += 1
        except (ValueError, TypeError):
            continue

    # Build velocity data for requested weeks
    velocity_data = []
    current_week = today - timedelta(days=today.weekday())

    for i in range(weeks):
        week_start = current_week - timedelta(weeks=i)
        week_key = week_start.strftime("%Y-%m-%d")
        velocity_data.append({
            "week_starting": week_key,
            "cards_completed": weekly_completed.get(week_key, 0)
        })

    velocity_data.reverse()

    # Calculate averages
    if velocity_data:
        values = [v["cards_completed"] for v in velocity_data]
        avg_velocity = sum(values) / len(values)
        max_velocity = max(values)
        min_velocity = min(values)
    else:
        avg_velocity = max_velocity = min_velocity = 0

    return {
        "board_id": board_id,
        "weeks": weeks,
        "velocity_data": velocity_data,
        "statistics": {
            "average": round(avg_velocity, 1),
            "max": max_velocity,
            "min": min_velocity
        }
    }


@router.get("/boards/{board_id}/analytics/wip-aging")
async def get_wip_aging(board_id: str):
    """Get work-in-progress aging analysis."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    columns = db.columns.search(Q.board_id == board_id)
    now = datetime.now()

    aging_data = []

    for col in sorted(columns, key=lambda x: x.get("position", 0)):
        cards = db.cards.search(Q.column_id == col["id"])
        active_cards = [c for c in cards if not c.get("archived")]

        column_cards = []
        for card in active_cards:
            created_at = card.get("created_at")
            if created_at:
                try:
                    created = datetime.fromisoformat(created_at)
                    age_days = (now - created).days
                except (ValueError, TypeError):
                    age_days = 0
            else:
                age_days = 0

            column_cards.append({
                "id": card["id"],
                "title": card.get("title"),
                "age_days": age_days,
                "priority": card.get("priority"),
                "is_blocked": bool(card.get("blocked_by"))
            })

        # Sort by age descending
        column_cards.sort(key=lambda x: x["age_days"], reverse=True)

        aging_data.append({
            "column_id": col["id"],
            "column_name": col["name"],
            "card_count": len(column_cards),
            "avg_age": round(sum(c["age_days"] for c in column_cards) / len(column_cards), 1) if column_cards else 0,
            "max_age": max((c["age_days"] for c in column_cards), default=0),
            "cards": column_cards[:10]  # Top 10 oldest
        })

    return {
        "board_id": board_id,
        "generated_at": now.isoformat(),
        "columns": aging_data
    }


@router.get("/boards/{board_id}/analytics/labels")
async def get_label_distribution(board_id: str):
    """Get label usage distribution."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    columns = db.columns.search(Q.board_id == board_id)
    board_labels = board.get("labels", [])
    label_map = {l["id"]: l for l in board_labels}

    label_counts = defaultdict(int)
    total_cards = 0

    for col in columns:
        cards = db.cards.search(Q.column_id == col["id"])
        for card in cards:
            if card.get("archived"):
                continue
            total_cards += 1
            for label_id in card.get("labels", []):
                label_counts[label_id] += 1

    distribution = []
    for label_id, count in sorted(label_counts.items(), key=lambda x: x[1], reverse=True):
        label = label_map.get(label_id, {})
        distribution.append({
            "label_id": label_id,
            "name": label.get("name", "Unknown"),
            "color": label.get("color"),
            "count": count,
            "percentage": round((count / total_cards) * 100, 1) if total_cards > 0 else 0
        })

    return {
        "board_id": board_id,
        "total_cards": total_cards,
        "distribution": distribution
    }


@router.get("/boards/{board_id}/analytics/assignees")
async def get_assignee_workload(board_id: str):
    """Get workload distribution by assignee."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    columns = db.columns.search(Q.board_id == board_id)
    column_map = {c["id"]: c["name"] for c in columns}

    assignee_data = defaultdict(lambda: {
        "total": 0,
        "by_column": defaultdict(int),
        "overdue": 0,
        "blocked": 0
    })

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    unassigned = {"total": 0, "by_column": defaultdict(int), "overdue": 0, "blocked": 0}

    for col in columns:
        cards = db.cards.search(Q.column_id == col["id"])
        for card in cards:
            if card.get("archived"):
                continue

            assignee_id = card.get("assignee_id")
            if assignee_id:
                data = assignee_data[assignee_id]
            else:
                data = unassigned

            data["total"] += 1
            data["by_column"][col["name"]] += 1

            if card.get("due_date"):
                try:
                    due = datetime.strptime(card["due_date"], "%Y-%m-%d")
                    if due < today:
                        data["overdue"] += 1
                except ValueError:
                    pass

            if card.get("blocked_by"):
                data["blocked"] += 1

    # Enrich with member details
    workload = []
    for assignee_id, data in assignee_data.items():
        member = db.members.get(Q.id == assignee_id)
        workload.append({
            "assignee_id": assignee_id,
            "name": member.get("name") if member else "Unknown",
            "email": member.get("email") if member else None,
            "total_cards": data["total"],
            "by_column": dict(data["by_column"]),
            "overdue_cards": data["overdue"],
            "blocked_cards": data["blocked"]
        })

    # Add unassigned
    if unassigned["total"] > 0:
        workload.append({
            "assignee_id": None,
            "name": "Unassigned",
            "email": None,
            "total_cards": unassigned["total"],
            "by_column": dict(unassigned["by_column"]),
            "overdue_cards": unassigned["overdue"],
            "blocked_cards": unassigned["blocked"]
        })

    # Sort by total cards descending
    workload.sort(key=lambda x: x["total_cards"], reverse=True)

    return {
        "board_id": board_id,
        "workload": workload
    }
