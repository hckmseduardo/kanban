"""Test data factories for Kanban Portal API tests"""

import uuid
from datetime import datetime
from typing import Optional, List


def create_user(
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    display_name: str = "Test User"
) -> dict:
    """Create a user dict for testing"""
    uid = user_id or str(uuid.uuid4())
    return {
        "id": uid,
        "email": email or f"user-{uid[:8]}@example.com",
        "display_name": display_name,
        "avatar_url": None,
        "created_at": datetime.utcnow().isoformat(),
        "last_login_at": datetime.utcnow().isoformat()
    }


def create_team(
    team_id: Optional[str] = None,
    slug: Optional[str] = None,
    name: str = "Test Team",
    owner_id: Optional[str] = None,
    status: str = "active"
) -> dict:
    """Create a team dict for testing"""
    tid = team_id or str(uuid.uuid4())
    return {
        "id": tid,
        "slug": slug or f"team-{tid[:8]}",
        "name": name,
        "description": f"Description for {name}",
        "owner_id": owner_id or str(uuid.uuid4()),
        "status": status,
        "created_at": datetime.utcnow().isoformat(),
        "provisioned_at": datetime.utcnow().isoformat() if status == "active" else None
    }


def create_membership(
    user_id: str,
    team_id: str,
    role: str = "member"
) -> dict:
    """Create a membership dict for testing"""
    return {
        "user_id": user_id,
        "team_id": team_id,
        "role": role,
        "joined_at": datetime.utcnow().isoformat()
    }


def create_portal_token(
    token_id: Optional[str] = None,
    name: str = "Test Token",
    scopes: Optional[List[str]] = None,
    created_by: Optional[str] = None,
    is_active: bool = True,
    expires_at: Optional[str] = None
) -> dict:
    """Create a portal API token dict for testing"""
    tid = token_id or str(uuid.uuid4())
    return {
        "id": tid,
        "name": name,
        "token_hash": f"hash_{tid[:16]}",
        "scopes": scopes or ["*"],
        "created_by": created_by or str(uuid.uuid4()),
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": expires_at,
        "last_used_at": None,
        "is_active": is_active
    }


def create_board(
    board_id: Optional[str] = None,
    name: str = "Test Board",
    owner_id: Optional[str] = None,
    visibility: str = "team"
) -> dict:
    """Create a board dict for testing"""
    bid = board_id or str(uuid.uuid4())
    return {
        "id": bid,
        "name": name,
        "description": f"Description for {name}",
        "visibility": visibility,
        "owner_id": owner_id or str(uuid.uuid4()),
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }


def create_column(
    column_id: Optional[str] = None,
    board_id: Optional[str] = None,
    name: str = "Test Column",
    position: int = 0,
    wip_limit: Optional[int] = None
) -> dict:
    """Create a column dict for testing"""
    cid = column_id or str(uuid.uuid4())
    return {
        "id": cid,
        "board_id": board_id or str(uuid.uuid4()),
        "name": name,
        "position": position,
        "wip_limit": wip_limit,
        "created_at": datetime.utcnow().isoformat()
    }


def create_card(
    card_id: Optional[str] = None,
    column_id: Optional[str] = None,
    title: str = "Test Card",
    description: str = "Test description",
    position: int = 0,
    priority: str = "medium",
    labels: Optional[List[str]] = None,
    assignee_id: Optional[str] = None,
    due_date: Optional[str] = None,
    archived: bool = False,
    created_by: Optional[str] = None
) -> dict:
    """Create a card dict for testing"""
    cid = card_id or str(uuid.uuid4())
    return {
        "id": cid,
        "column_id": column_id or str(uuid.uuid4()),
        "title": title,
        "description": description,
        "position": position,
        "priority": priority,
        "labels": labels or [],
        "assignee_id": assignee_id,
        "due_date": due_date,
        "archived": archived,
        "created_by": created_by or str(uuid.uuid4()),
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }


def create_label(
    label_id: Optional[str] = None,
    board_id: Optional[str] = None,
    name: str = "Test Label",
    color: str = "#3498db"
) -> dict:
    """Create a label dict for testing"""
    lid = label_id or str(uuid.uuid4())
    return {
        "id": lid,
        "board_id": board_id or str(uuid.uuid4()),
        "name": name,
        "color": color,
        "created_at": datetime.utcnow().isoformat()
    }


# =============================================================================
# Request Body Factories
# =============================================================================

def team_create_request(
    name: str = "New Team",
    slug: Optional[str] = None,
    description: str = "Team description"
) -> dict:
    """Create a team creation request body"""
    return {
        "name": name,
        "slug": slug or f"team-{uuid.uuid4().hex[:8]}",
        "description": description
    }


def team_update_request(
    name: Optional[str] = None,
    description: Optional[str] = None
) -> dict:
    """Create a team update request body"""
    data = {}
    if name:
        data["name"] = name
    if description:
        data["description"] = description
    return data


def column_create_request(
    board_id: str,
    name: str = "New Column",
    position: int = 0,
    wip_limit: Optional[int] = None
) -> dict:
    """Create a column creation request body"""
    data = {
        "board_id": board_id,
        "name": name,
        "position": position
    }
    if wip_limit is not None:
        data["wip_limit"] = wip_limit
    return data


def card_create_request(
    column_id: str,
    title: str = "New Card",
    description: str = "Card description",
    priority: str = "medium",
    labels: Optional[List[str]] = None,
    assignee_id: Optional[str] = None,
    due_date: Optional[str] = None
) -> dict:
    """Create a card creation request body"""
    data = {
        "column_id": column_id,
        "title": title,
        "description": description,
        "priority": priority
    }
    if labels:
        data["labels"] = labels
    if assignee_id:
        data["assignee_id"] = assignee_id
    if due_date:
        data["due_date"] = due_date
    return data


def card_update_request(
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    labels: Optional[List[str]] = None,
    assignee_id: Optional[str] = None,
    due_date: Optional[str] = None
) -> dict:
    """Create a card update request body"""
    data = {}
    if title:
        data["title"] = title
    if description:
        data["description"] = description
    if priority:
        data["priority"] = priority
    if labels is not None:
        data["labels"] = labels
    if assignee_id:
        data["assignee_id"] = assignee_id
    if due_date:
        data["due_date"] = due_date
    return data


def card_move_request(
    column_id: str,
    position: int = 0
) -> dict:
    """Create a card move request body"""
    return {
        "column_id": column_id,
        "position": position
    }


def portal_token_create_request(
    name: str = "API Token",
    scopes: Optional[List[str]] = None
) -> dict:
    """Create a portal token creation request body"""
    return {
        "name": name,
        "scopes": scopes or ["*"]
    }
