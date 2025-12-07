"""
Automation Rules API

Allows creating automation rules like "When X happens, do Y".
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Literal, Any, Dict
from pathlib import Path
import os
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


# Trigger types
TRIGGER_TYPES = [
    "card_created",
    "card_moved",
    "card_updated",
    "due_date_approaching",
    "due_date_passed",
    "label_added",
    "label_removed",
    "assignee_changed",
    "checklist_completed",
    "all_subtasks_completed"
]

# Action types
ACTION_TYPES = [
    "move_card",
    "add_label",
    "remove_label",
    "set_priority",
    "assign_member",
    "add_comment",
    "set_due_date",
    "archive_card",
    "create_notification",
    "mark_completed"
]


class TriggerCondition(BaseModel):
    field: str
    operator: Literal["equals", "not_equals", "contains", "not_contains", "is_empty", "is_not_empty"]
    value: Optional[Any] = None


class AutomationTrigger(BaseModel):
    type: str
    conditions: Optional[List[TriggerCondition]] = None


class AutomationAction(BaseModel):
    type: str
    params: Dict[str, Any] = {}


class AutomationCreate(BaseModel):
    name: str
    description: Optional[str] = None
    trigger: AutomationTrigger
    actions: List[AutomationAction]
    enabled: bool = True


class AutomationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger: Optional[AutomationTrigger] = None
    actions: Optional[List[AutomationAction]] = None
    enabled: Optional[bool] = None


@router.get("/boards/{board_id}/automations")
async def list_automations(board_id: str):
    """List all automations for a board."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    automations = db.automations.search(Q.board_id == board_id)

    return {
        "board_id": board_id,
        "automations": automations,
        "count": len(automations)
    }


@router.post("/boards/{board_id}/automations")
async def create_automation(board_id: str, automation: AutomationCreate):
    """Create a new automation rule."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Validate trigger type
    if automation.trigger.type not in TRIGGER_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid trigger type. Must be one of: {', '.join(TRIGGER_TYPES)}"
        )

    # Validate action types
    for action in automation.actions:
        if action.type not in ACTION_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action type. Must be one of: {', '.join(ACTION_TYPES)}"
            )

    new_automation = {
        "id": db.generate_id(),
        "board_id": board_id,
        "name": automation.name,
        "description": automation.description or "",
        "trigger": automation.trigger.model_dump(),
        "actions": [a.model_dump() for a in automation.actions],
        "enabled": automation.enabled,
        "run_count": 0,
        "last_run": None,
        "created_at": db.timestamp()
    }

    db.automations.insert(new_automation)

    return new_automation


@router.get("/boards/{board_id}/automations/{automation_id}")
async def get_automation(board_id: str, automation_id: str):
    """Get a specific automation."""
    db.initialize()

    automation = db.automations.get(
        (Q.id == automation_id) & (Q.board_id == board_id)
    )

    if not automation:
        raise HTTPException(status_code=404, detail="Automation not found")

    return automation


@router.patch("/boards/{board_id}/automations/{automation_id}")
async def update_automation(board_id: str, automation_id: str, update: AutomationUpdate):
    """Update an automation rule."""
    db.initialize()

    automation = db.automations.get(
        (Q.id == automation_id) & (Q.board_id == board_id)
    )

    if not automation:
        raise HTTPException(status_code=404, detail="Automation not found")

    updates = {}

    if update.name is not None:
        updates["name"] = update.name
    if update.description is not None:
        updates["description"] = update.description
    if update.trigger is not None:
        if update.trigger.type not in TRIGGER_TYPES:
            raise HTTPException(status_code=400, detail="Invalid trigger type")
        updates["trigger"] = update.trigger.model_dump()
    if update.actions is not None:
        for action in update.actions:
            if action.type not in ACTION_TYPES:
                raise HTTPException(status_code=400, detail="Invalid action type")
        updates["actions"] = [a.model_dump() for a in update.actions]
    if update.enabled is not None:
        updates["enabled"] = update.enabled

    updates["updated_at"] = db.timestamp()

    db.automations.update(updates, Q.id == automation_id)

    return {**automation, **updates}


@router.delete("/boards/{board_id}/automations/{automation_id}")
async def delete_automation(board_id: str, automation_id: str):
    """Delete an automation rule."""
    db.initialize()

    automation = db.automations.get(
        (Q.id == automation_id) & (Q.board_id == board_id)
    )

    if not automation:
        raise HTTPException(status_code=404, detail="Automation not found")

    db.automations.remove(Q.id == automation_id)

    return {"message": "Automation deleted"}


@router.post("/boards/{board_id}/automations/{automation_id}/toggle")
async def toggle_automation(board_id: str, automation_id: str):
    """Toggle automation enabled/disabled."""
    db.initialize()

    automation = db.automations.get(
        (Q.id == automation_id) & (Q.board_id == board_id)
    )

    if not automation:
        raise HTTPException(status_code=404, detail="Automation not found")

    new_enabled = not automation.get("enabled", True)
    db.automations.update({
        "enabled": new_enabled,
        "updated_at": db.timestamp()
    }, Q.id == automation_id)

    return {"enabled": new_enabled}


@router.post("/boards/{board_id}/automations/{automation_id}/test")
async def test_automation(board_id: str, automation_id: str, card_id: str):
    """Test an automation against a specific card (dry run)."""
    db.initialize()

    automation = db.automations.get(
        (Q.id == automation_id) & (Q.board_id == board_id)
    )

    if not automation:
        raise HTTPException(status_code=404, detail="Automation not found")

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Simulate what would happen
    would_trigger = True
    trigger = automation.get("trigger", {})
    conditions = trigger.get("conditions", [])

    condition_results = []
    for condition in conditions:
        field = condition.get("field")
        operator = condition.get("operator")
        value = condition.get("value")
        card_value = card.get(field)

        result = False
        if operator == "equals":
            result = card_value == value
        elif operator == "not_equals":
            result = card_value != value
        elif operator == "contains":
            result = value in (card_value or "") if isinstance(card_value, str) else value in (card_value or [])
        elif operator == "not_contains":
            result = value not in (card_value or "") if isinstance(card_value, str) else value not in (card_value or [])
        elif operator == "is_empty":
            result = not card_value
        elif operator == "is_not_empty":
            result = bool(card_value)

        condition_results.append({
            "field": field,
            "operator": operator,
            "expected": value,
            "actual": card_value,
            "passed": result
        })

        if not result:
            would_trigger = False

    return {
        "would_trigger": would_trigger,
        "automation_name": automation.get("name"),
        "trigger_type": trigger.get("type"),
        "condition_results": condition_results,
        "actions_that_would_run": automation.get("actions", []) if would_trigger else []
    }


@router.get("/automations/triggers")
async def list_trigger_types():
    """List available trigger types."""
    return {
        "triggers": [
            {"type": "card_created", "description": "When a new card is created"},
            {"type": "card_moved", "description": "When a card is moved to a different column"},
            {"type": "card_updated", "description": "When a card is updated"},
            {"type": "due_date_approaching", "description": "When due date is within X days"},
            {"type": "due_date_passed", "description": "When due date has passed"},
            {"type": "label_added", "description": "When a label is added to a card"},
            {"type": "label_removed", "description": "When a label is removed from a card"},
            {"type": "assignee_changed", "description": "When card assignee changes"},
            {"type": "checklist_completed", "description": "When all checklist items are completed"},
            {"type": "all_subtasks_completed", "description": "When all subtasks are completed"}
        ]
    }


@router.get("/automations/actions")
async def list_action_types():
    """List available action types."""
    return {
        "actions": [
            {"type": "move_card", "description": "Move card to a column", "params": ["column_id"]},
            {"type": "add_label", "description": "Add a label to the card", "params": ["label_id"]},
            {"type": "remove_label", "description": "Remove a label from the card", "params": ["label_id"]},
            {"type": "set_priority", "description": "Set card priority", "params": ["priority"]},
            {"type": "assign_member", "description": "Assign card to a member", "params": ["member_id"]},
            {"type": "add_comment", "description": "Add a comment to the card", "params": ["text"]},
            {"type": "set_due_date", "description": "Set or adjust due date", "params": ["days_from_now"]},
            {"type": "archive_card", "description": "Archive the card", "params": []},
            {"type": "create_notification", "description": "Create a notification", "params": ["user_id", "message"]},
            {"type": "mark_completed", "description": "Mark card as completed", "params": []}
        ]
    }
