"""
Notifications API

In-app notifications for mentions, assignments, due dates, etc.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Literal
from datetime import datetime
from pathlib import Path
import os
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


class NotificationCreate(BaseModel):
    user_id: str
    type: Literal["mention", "assignment", "due_date", "comment", "card_update", "blocker"]
    title: str
    message: str
    card_id: Optional[str] = None
    board_id: Optional[str] = None
    action_url: Optional[str] = None


class NotificationPreferences(BaseModel):
    mentions: bool = True
    assignments: bool = True
    due_dates: bool = True
    comments: bool = True
    card_updates: bool = False


@router.get("")
async def get_notifications(
    user_id: str,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0
):
    """Get notifications for a user."""
    db.initialize()

    all_notifications = db.notifications.search(Q.user_id == user_id)

    if unread_only:
        all_notifications = [n for n in all_notifications if not n.get("read")]

    # Sort by created_at descending
    all_notifications.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    total = len(all_notifications)
    notifications = all_notifications[offset:offset + limit]

    # Count unread
    unread_count = sum(1 for n in db.notifications.search(Q.user_id == user_id) if not n.get("read"))

    return {
        "notifications": notifications,
        "total": total,
        "unread_count": unread_count,
        "limit": limit,
        "offset": offset
    }


@router.post("")
async def create_notification(notification: NotificationCreate):
    """Create a new notification."""
    db.initialize()

    # Check user preferences
    prefs = db.notification_preferences.get(Q.user_id == notification.user_id)
    if prefs:
        type_pref_map = {
            "mention": "mentions",
            "assignment": "assignments",
            "due_date": "due_dates",
            "comment": "comments",
            "card_update": "card_updates",
            "blocker": "card_updates"
        }
        pref_key = type_pref_map.get(notification.type, "card_updates")
        if not prefs.get(pref_key, True):
            return {"message": "Notification suppressed by user preferences"}

    new_notification = {
        "id": db.generate_id(),
        "user_id": notification.user_id,
        "type": notification.type,
        "title": notification.title,
        "message": notification.message,
        "card_id": notification.card_id,
        "board_id": notification.board_id,
        "action_url": notification.action_url,
        "read": False,
        "created_at": db.timestamp()
    }

    db.notifications.insert(new_notification)

    return new_notification


@router.post("/{notification_id}/read")
async def mark_notification_read(notification_id: str):
    """Mark a notification as read."""
    db.initialize()

    notification = db.notifications.get(Q.id == notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    db.notifications.update({
        "read": True,
        "read_at": db.timestamp()
    }, Q.id == notification_id)

    return {"message": "Notification marked as read"}


@router.post("/read-all")
async def mark_all_notifications_read(user_id: str):
    """Mark all notifications as read for a user."""
    db.initialize()

    notifications = db.notifications.search(Q.user_id == user_id)
    timestamp = db.timestamp()

    for n in notifications:
        if not n.get("read"):
            db.notifications.update({
                "read": True,
                "read_at": timestamp
            }, Q.id == n["id"])

    return {"message": "All notifications marked as read"}


@router.delete("/{notification_id}")
async def delete_notification(notification_id: str):
    """Delete a notification."""
    db.initialize()

    notification = db.notifications.get(Q.id == notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    db.notifications.remove(Q.id == notification_id)

    return {"message": "Notification deleted"}


@router.delete("")
async def clear_notifications(user_id: str, read_only: bool = True):
    """Clear notifications for a user."""
    db.initialize()

    if read_only:
        notifications = db.notifications.search(
            (Q.user_id == user_id) & (Q.read == True)
        )
    else:
        notifications = db.notifications.search(Q.user_id == user_id)

    for n in notifications:
        db.notifications.remove(Q.id == n["id"])

    return {"message": f"Cleared {len(notifications)} notifications"}


@router.get("/preferences")
async def get_notification_preferences(user_id: str):
    """Get notification preferences for a user."""
    db.initialize()

    prefs = db.notification_preferences.get(Q.user_id == user_id)

    if not prefs:
        # Return defaults
        return {
            "user_id": user_id,
            "mentions": True,
            "assignments": True,
            "due_dates": True,
            "comments": True,
            "card_updates": False
        }

    return prefs


@router.put("/preferences")
async def update_notification_preferences(user_id: str, preferences: NotificationPreferences):
    """Update notification preferences for a user."""
    db.initialize()

    existing = db.notification_preferences.get(Q.user_id == user_id)

    prefs_data = {
        "user_id": user_id,
        "mentions": preferences.mentions,
        "assignments": preferences.assignments,
        "due_dates": preferences.due_dates,
        "comments": preferences.comments,
        "card_updates": preferences.card_updates,
        "updated_at": db.timestamp()
    }

    if existing:
        db.notification_preferences.update(prefs_data, Q.user_id == user_id)
    else:
        prefs_data["id"] = db.generate_id()
        prefs_data["created_at"] = db.timestamp()
        db.notification_preferences.insert(prefs_data)

    return prefs_data
