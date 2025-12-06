"""Reports and analytics routes"""

from fastapi import APIRouter, HTTPException, Query as QueryParam
from datetime import datetime, timedelta
from typing import Optional, List
from collections import defaultdict
from ..services.database import Database, Q
from pathlib import Path
import os

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO date string to datetime"""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        return datetime.strptime(date_str, "%Y-%m-%d")


def get_date_key(timestamp: str, group_by: str) -> str:
    """Get grouping key based on period"""
    dt = parse_date(timestamp)
    if not dt:
        return "unknown"

    if group_by == "day":
        return dt.strftime("%Y-%m-%d")
    elif group_by == "week":
        # Get Monday of the week
        monday = dt - timedelta(days=dt.weekday())
        return monday.strftime("%Y-%m-%d")
    elif group_by == "month":
        return dt.strftime("%Y-%m")
    return dt.strftime("%Y-%m-%d")


def calculate_hours_between(start: str, end: str) -> float:
    """Calculate hours between two ISO timestamps"""
    start_dt = parse_date(start)
    end_dt = parse_date(end)
    if not start_dt or not end_dt:
        return 0
    diff = end_dt - start_dt
    return diff.total_seconds() / 3600


@router.get("/boards/{board_id}/reports/cycle-time")
async def get_cycle_time(
    board_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    group_by: str = QueryParam(default="day", regex="^(day|week|month)$")
):
    """
    Get cycle time metrics for a board.
    Cycle time = time from first active column to done column.
    """
    db.initialize()

    # Verify board exists
    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Get columns for this board to identify "done" column (last column)
    columns = db.columns.search(Q.board_id == board_id)
    if not columns:
        return {"data": [], "summary": {"avg_hours": 0, "completed_cards": 0}}

    columns_sorted = sorted(columns, key=lambda x: x.get("position", 0))
    done_column_id = columns_sorted[-1]["id"] if columns_sorted else None
    first_active_column_id = columns_sorted[1]["id"] if len(columns_sorted) > 1 else columns_sorted[0]["id"]

    # Create column lookup
    column_lookup = {c["id"]: c for c in columns}

    # Get activity for this board
    activities = db.activity.search(Q.board_id == board_id)

    # Filter by date range
    from_dt = parse_date(from_date) if from_date else datetime.min
    to_dt = parse_date(to_date) if to_date else datetime.max

    # Group activities by card
    card_activities = defaultdict(list)
    for activity in activities:
        act_dt = parse_date(activity["timestamp"])
        if act_dt and from_dt <= act_dt <= to_dt:
            card_activities[activity["card_id"]].append(activity)

    # Calculate cycle time for each completed card
    cycle_times = []
    for card_id, acts in card_activities.items():
        acts_sorted = sorted(acts, key=lambda x: x["timestamp"])

        # Find first entry to active column
        start_time = None
        for act in acts_sorted:
            if act["action"] == "moved" and act["to_column_id"] == first_active_column_id:
                start_time = act["timestamp"]
                break
            elif act["action"] == "created" and act["to_column_id"] == first_active_column_id:
                start_time = act["timestamp"]
                break

        # Find completion time (moved to done)
        end_time = None
        for act in reversed(acts_sorted):
            if act["action"] == "moved" and act["to_column_id"] == done_column_id:
                end_time = act["timestamp"]
                break

        if start_time and end_time:
            hours = calculate_hours_between(start_time, end_time)
            if hours > 0:
                cycle_times.append({
                    "card_id": card_id,
                    "hours": hours,
                    "completed_at": end_time,
                    "date_key": get_date_key(end_time, group_by)
                })

    # Group by period
    grouped = defaultdict(list)
    for ct in cycle_times:
        grouped[ct["date_key"]].append(ct["hours"])

    # Calculate averages per period
    data = []
    for date_key in sorted(grouped.keys()):
        hours_list = grouped[date_key]
        data.append({
            "date": date_key,
            "avg_hours": round(sum(hours_list) / len(hours_list), 1),
            "min_hours": round(min(hours_list), 1),
            "max_hours": round(max(hours_list), 1),
            "count": len(hours_list)
        })

    # Overall summary
    all_hours = [ct["hours"] for ct in cycle_times]
    summary = {
        "avg_hours": round(sum(all_hours) / len(all_hours), 1) if all_hours else 0,
        "median_hours": round(sorted(all_hours)[len(all_hours)//2], 1) if all_hours else 0,
        "completed_cards": len(cycle_times)
    }

    return {"data": data, "summary": summary}


@router.get("/boards/{board_id}/reports/lead-time")
async def get_lead_time(
    board_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    group_by: str = QueryParam(default="day", regex="^(day|week|month)$")
):
    """
    Get lead time metrics for a board.
    Lead time = time from card creation to completion.
    """
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Get done column (last column)
    columns = db.columns.search(Q.board_id == board_id)
    columns_sorted = sorted(columns, key=lambda x: x.get("position", 0))
    done_column_id = columns_sorted[-1]["id"] if columns_sorted else None

    # Get activity
    activities = db.activity.search(Q.board_id == board_id)

    from_dt = parse_date(from_date) if from_date else datetime.min
    to_dt = parse_date(to_date) if to_date else datetime.max

    # Group by card
    card_activities = defaultdict(list)
    for activity in activities:
        act_dt = parse_date(activity["timestamp"])
        if act_dt and from_dt <= act_dt <= to_dt:
            card_activities[activity["card_id"]].append(activity)

    # Calculate lead time
    lead_times = []
    for card_id, acts in card_activities.items():
        acts_sorted = sorted(acts, key=lambda x: x["timestamp"])

        # Find creation time
        start_time = None
        for act in acts_sorted:
            if act["action"] == "created":
                start_time = act["timestamp"]
                break

        # Find completion time
        end_time = None
        for act in reversed(acts_sorted):
            if act["action"] == "moved" and act["to_column_id"] == done_column_id:
                end_time = act["timestamp"]
                break

        if start_time and end_time:
            hours = calculate_hours_between(start_time, end_time)
            if hours > 0:
                lead_times.append({
                    "card_id": card_id,
                    "hours": hours,
                    "completed_at": end_time,
                    "date_key": get_date_key(end_time, group_by)
                })

    # Group and calculate
    grouped = defaultdict(list)
    for lt in lead_times:
        grouped[lt["date_key"]].append(lt["hours"])

    data = []
    for date_key in sorted(grouped.keys()):
        hours_list = grouped[date_key]
        data.append({
            "date": date_key,
            "avg_hours": round(sum(hours_list) / len(hours_list), 1),
            "min_hours": round(min(hours_list), 1),
            "max_hours": round(max(hours_list), 1),
            "count": len(hours_list)
        })

    all_hours = [lt["hours"] for lt in lead_times]
    summary = {
        "avg_hours": round(sum(all_hours) / len(all_hours), 1) if all_hours else 0,
        "median_hours": round(sorted(all_hours)[len(all_hours)//2], 1) if all_hours else 0,
        "completed_cards": len(lead_times)
    }

    return {"data": data, "summary": summary}


@router.get("/boards/{board_id}/reports/throughput")
async def get_throughput(
    board_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    group_by: str = QueryParam(default="day", regex="^(day|week|month)$")
):
    """
    Get throughput metrics for a board.
    Throughput = number of cards completed per period.
    """
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Get done column
    columns = db.columns.search(Q.board_id == board_id)
    columns_sorted = sorted(columns, key=lambda x: x.get("position", 0))
    done_column_id = columns_sorted[-1]["id"] if columns_sorted else None

    # Get all moves to done column
    activities = db.activity.search(Q.board_id == board_id)

    from_dt = parse_date(from_date) if from_date else datetime.min
    to_dt = parse_date(to_date) if to_date else datetime.max

    # Count completions per period
    completions = defaultdict(set)  # Use set to avoid counting same card twice

    for activity in activities:
        if activity["action"] == "moved" and activity["to_column_id"] == done_column_id:
            act_dt = parse_date(activity["timestamp"])
            if act_dt and from_dt <= act_dt <= to_dt:
                date_key = get_date_key(activity["timestamp"], group_by)
                completions[date_key].add(activity["card_id"])

    data = []
    for date_key in sorted(completions.keys()):
        data.append({
            "date": date_key,
            "count": len(completions[date_key])
        })

    total = sum(len(cards) for cards in completions.values())
    summary = {
        "total_completed": total,
        "avg_per_period": round(total / len(completions), 1) if completions else 0
    }

    return {"data": data, "summary": summary}


@router.get("/boards/{board_id}/reports/summary")
async def get_reports_summary(board_id: str):
    """
    Get a summary of all metrics for the dashboard.
    Returns last 30 days of data.
    """
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Calculate date range (last 30 days)
    to_date = datetime.utcnow()
    from_date = to_date - timedelta(days=30)
    from_str = from_date.strftime("%Y-%m-%d")
    to_str = to_date.strftime("%Y-%m-%d")

    # Get columns
    columns = db.columns.search(Q.board_id == board_id)
    columns_sorted = sorted(columns, key=lambda x: x.get("position", 0))
    done_column_id = columns_sorted[-1]["id"] if columns_sorted else None

    # Get current card counts per column
    cards = db.cards.all()
    column_counts = defaultdict(int)
    for card in cards:
        col = db.columns.get(Q.id == card["column_id"])
        if col and col.get("board_id") == board_id:
            column_counts[card["column_id"]] += 1

    # Get activities for metrics
    activities = db.activity.search(Q.board_id == board_id)

    # Count completed in last 30 days
    completed_count = 0
    for activity in activities:
        if activity["action"] == "moved" and activity["to_column_id"] == done_column_id:
            act_dt = parse_date(activity["timestamp"])
            if act_dt and from_date <= act_dt <= to_date:
                completed_count += 1

    # Build column distribution
    column_distribution = []
    for col in columns_sorted:
        column_distribution.append({
            "id": col["id"],
            "name": col["name"],
            "count": column_counts.get(col["id"], 0),
            "wip_limit": col.get("wip_limit")
        })

    return {
        "board_id": board_id,
        "board_name": board["name"],
        "period": {
            "from": from_str,
            "to": to_str,
            "days": 30
        },
        "metrics": {
            "completed_last_30d": completed_count,
            "total_cards": sum(column_counts.values()),
            "columns": len(columns)
        },
        "column_distribution": column_distribution
    }
