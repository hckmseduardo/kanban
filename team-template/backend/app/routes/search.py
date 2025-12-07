"""
Search API

Provides global search across cards with advanced filtering options.
"""
from fastapi import APIRouter, Query as QueryParam
from typing import Optional, List
from datetime import datetime, timedelta
from pathlib import Path
import os
import re
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


@router.get("/search")
async def search_cards(
    q: str = QueryParam(default="", description="Search query"),
    board_id: Optional[str] = QueryParam(default=None, description="Filter by board"),
    labels: Optional[str] = QueryParam(default=None, description="Comma-separated label IDs"),
    priority: Optional[str] = QueryParam(default=None, description="Filter by priority"),
    assignee_id: Optional[str] = QueryParam(default=None, description="Filter by assignee"),
    due_from: Optional[str] = QueryParam(default=None, description="Due date from (YYYY-MM-DD)"),
    due_to: Optional[str] = QueryParam(default=None, description="Due date to (YYYY-MM-DD)"),
    has_due_date: Optional[bool] = QueryParam(default=None, description="Filter cards with/without due dates"),
    is_overdue: Optional[bool] = QueryParam(default=None, description="Filter overdue cards"),
    is_blocked: Optional[bool] = QueryParam(default=None, description="Filter blocked cards"),
    has_attachments: Optional[bool] = QueryParam(default=None, description="Filter cards with attachments"),
    include_archived: bool = QueryParam(default=False, description="Include archived cards"),
    limit: int = QueryParam(default=50, ge=1, le=200),
    offset: int = QueryParam(default=0, ge=0)
):
    """Search cards with advanced filters."""
    db.initialize()

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    results = []

    # Get boards to search
    if board_id:
        boards = [db.boards.get(Q.id == board_id)]
        boards = [b for b in boards if b]
    else:
        boards = db.boards.all()

    # Parse labels filter
    label_filter = labels.split(",") if labels else None

    for board in boards:
        columns = db.columns.search(Q.board_id == board["id"])
        column_map = {c["id"]: c["name"] for c in columns}

        for column in columns:
            cards = db.cards.search(Q.column_id == column["id"])

            for card in cards:
                # Skip archived unless requested
                if card.get("archived") and not include_archived:
                    continue

                # Text search in title, description
                if q:
                    query_lower = q.lower()
                    title_match = query_lower in (card.get("title") or "").lower()
                    desc_match = query_lower in (card.get("description") or "").lower()
                    if not (title_match or desc_match):
                        continue

                # Label filter
                if label_filter:
                    card_labels = card.get("labels", [])
                    if not any(lbl in card_labels for lbl in label_filter):
                        continue

                # Priority filter
                if priority and card.get("priority") != priority:
                    continue

                # Assignee filter
                if assignee_id and card.get("assignee_id") != assignee_id:
                    continue

                # Due date filters
                due_date_str = card.get("due_date")
                due_date = None
                if due_date_str:
                    try:
                        due_date = datetime.strptime(due_date_str, "%Y-%m-%d")
                    except ValueError:
                        pass

                if has_due_date is True and not due_date:
                    continue
                if has_due_date is False and due_date:
                    continue

                if due_from and due_date:
                    try:
                        from_date = datetime.strptime(due_from, "%Y-%m-%d")
                        if due_date < from_date:
                            continue
                    except ValueError:
                        pass

                if due_to and due_date:
                    try:
                        to_date = datetime.strptime(due_to, "%Y-%m-%d")
                        if due_date > to_date:
                            continue
                    except ValueError:
                        pass

                if is_overdue is True:
                    if not due_date or due_date >= today:
                        continue
                if is_overdue is False:
                    if due_date and due_date < today:
                        continue

                # Blocked filter
                if is_blocked is True and not card.get("blocked_by"):
                    continue
                if is_blocked is False and card.get("blocked_by"):
                    continue

                # Attachments filter
                if has_attachments is True and not card.get("attachment_count", 0):
                    continue
                if has_attachments is False and card.get("attachment_count", 0):
                    continue

                # Build result
                results.append({
                    "id": card["id"],
                    "title": card["title"],
                    "description": (card.get("description") or "")[:200],
                    "board_id": board["id"],
                    "board_name": board.get("name"),
                    "column_id": column["id"],
                    "column_name": column_map.get(column["id"]),
                    "labels": card.get("labels", []),
                    "priority": card.get("priority"),
                    "assignee_id": card.get("assignee_id"),
                    "due_date": due_date_str,
                    "is_overdue": due_date < today if due_date else False,
                    "archived": card.get("archived", False),
                    "attachment_count": card.get("attachment_count", 0),
                    "blocked_by_count": len(card.get("blocked_by", [])),
                    "created_at": card.get("created_at")
                })

    # Sort by relevance (title matches first, then by created_at)
    if q:
        query_lower = q.lower()
        results.sort(key=lambda x: (
            0 if query_lower in x["title"].lower() else 1,
            x.get("created_at", "") or ""
        ), reverse=True)
    else:
        results.sort(key=lambda x: x.get("created_at", "") or "", reverse=True)

    total = len(results)
    results = results[offset:offset + limit]

    return {
        "query": q,
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": results
    }


@router.get("/search/suggestions")
async def get_search_suggestions(
    q: str = QueryParam(default="", min_length=2),
    limit: int = QueryParam(default=10, ge=1, le=50)
):
    """Get search suggestions based on card titles."""
    db.initialize()

    if len(q) < 2:
        return {"suggestions": []}

    query_lower = q.lower()
    suggestions = set()

    all_cards = db.cards.all()
    for card in all_cards:
        if card.get("archived"):
            continue
        title = card.get("title", "")
        if query_lower in title.lower():
            suggestions.add(title)
            if len(suggestions) >= limit:
                break

    return {"suggestions": list(suggestions)[:limit]}


@router.get("/filters/options")
async def get_filter_options(board_id: Optional[str] = None):
    """Get available filter options for the search UI."""
    db.initialize()

    # Get boards
    if board_id:
        boards = [db.boards.get(Q.id == board_id)]
        boards = [b for b in boards if b]
    else:
        boards = db.boards.all()

    # Collect unique values
    priorities = set()
    assignees = set()
    labels_set = set()

    for board in boards:
        # Get board labels
        board_labels = board.get("labels", [])
        for label in board_labels:
            labels_set.add((label.get("id"), label.get("name"), label.get("color")))

        columns = db.columns.search(Q.board_id == board["id"])
        for column in columns:
            cards = db.cards.search(Q.column_id == column["id"])
            for card in cards:
                if card.get("archived"):
                    continue
                if card.get("priority"):
                    priorities.add(card["priority"])
                if card.get("assignee_id"):
                    assignees.add(card["assignee_id"])

    # Get member details
    members = []
    for assignee_id in assignees:
        member = db.members.get(Q.id == assignee_id)
        if member:
            members.append({
                "id": member["id"],
                "name": member.get("name"),
                "email": member.get("email")
            })

    return {
        "boards": [{"id": b["id"], "name": b.get("name")} for b in boards],
        "priorities": sorted(list(priorities)),
        "assignees": members,
        "labels": [{"id": l[0], "name": l[1], "color": l[2]} for l in labels_set]
    }
