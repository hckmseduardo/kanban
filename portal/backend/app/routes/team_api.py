"""Team API routes - Programmatic access to team boards and cards

These endpoints allow managing boards and cards within teams using Portal API tokens.
Requests are proxied to the team's internal API.

Authentication: Portal API token (pk_*) or JWT
Required scopes: boards:read, boards:write, cards:read, cards:write

Auto-start: If a team is suspended when an API call is made, the team will be
automatically started. The request will wait up to 60 seconds for the team to
become active.
"""

import asyncio
import logging
from typing import Optional, List, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.unified import AuthContext, require_scope
from app.services.database_service import db_service
from app.services.task_service import task_service
from app.services.team_proxy import team_proxy

logger = logging.getLogger(__name__)

# Auto-start configuration
AUTO_START_TIMEOUT = 60  # Max seconds to wait for team to start
AUTO_START_POLL_INTERVAL = 2  # Seconds between status checks

router = APIRouter()


# =============================================================================
# Pydantic Models
# =============================================================================

class CardCreate(BaseModel):
    column_id: str
    title: str
    description: Optional[str] = ""
    position: Optional[int] = 0
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None
    labels: Optional[List[str]] = []
    priority: Optional[str] = None


class CardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None
    labels: Optional[List[str]] = None
    priority: Optional[str] = None
    column_id: Optional[str] = None
    position: Optional[int] = None


class CardMove(BaseModel):
    column_id: str
    position: Optional[int] = 0


class ColumnCreate(BaseModel):
    board_id: str
    name: str
    position: Optional[int] = 0
    wip_limit: Optional[int] = None
    color: Optional[str] = None


class ColumnUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[int] = None
    wip_limit: Optional[int] = None
    color: Optional[str] = None


# =============================================================================
# Helper Functions
# =============================================================================

async def verify_team_access(
    slug: str,
    auth: AuthContext
) -> dict:
    """Verify user has access to the team and auto-start if suspended.

    If the team is suspended, this function will:
    1. Start the team (create a start task)
    2. Wait for the team to become active (up to AUTO_START_TIMEOUT seconds)
    3. Return the team once it's active

    Returns:
        Team dict if access is granted and team is active

    Raises:
        HTTPException 404 if team not found
        HTTPException 403 if user is not a member
        HTTPException 503 if team fails to start
    """
    team = db_service.get_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    membership = db_service.get_membership(team["id"], auth.user["id"])
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this team")

    current_status = team.get("status")

    # If team is active, we're good
    if current_status in ["active", None]:
        return team

    # If team is already starting, wait for it
    if current_status == "starting":
        logger.info(f"Team {slug} is starting, waiting for it to become active...")
        team = await _wait_for_team_active(slug)
        if team:
            return team
        raise HTTPException(
            status_code=503,
            detail="Team is starting but did not become active in time. Please retry."
        )

    # If team is suspended, start it
    if current_status == "suspended":
        logger.info(f"Team {slug} is suspended, auto-starting...")

        # Update status to starting
        db_service.update_team(team["id"], {"status": "starting"})

        # Create start task
        try:
            task_id = await task_service.create_team_start_task(
                team_id=team["id"],
                team_slug=slug,
                user_id=auth.user["id"]
            )
            logger.info(f"Team {slug} start task created: {task_id}")
        except Exception as e:
            logger.error(f"Failed to create start task for {slug}: {e}")
            # Revert status
            db_service.update_team(team["id"], {"status": "suspended"})
            raise HTTPException(
                status_code=503,
                detail=f"Failed to start team: {str(e)}"
            )

        # Wait for team to become active
        team = await _wait_for_team_active(slug)
        if team:
            return team

        raise HTTPException(
            status_code=503,
            detail="Team start initiated but did not become active in time. Please retry."
        )

    # Unknown status
    raise HTTPException(
        status_code=503,
        detail=f"Team is {current_status}. Cannot process request."
    )


async def _wait_for_team_active(slug: str) -> Optional[dict]:
    """Wait for a team to become active.

    Returns:
        Team dict if it becomes active, None if timeout
    """
    elapsed = 0
    while elapsed < AUTO_START_TIMEOUT:
        await asyncio.sleep(AUTO_START_POLL_INTERVAL)
        elapsed += AUTO_START_POLL_INTERVAL

        team = db_service.get_team_by_slug(slug)
        if not team:
            return None

        status = team.get("status")
        if status == "active":
            logger.info(f"Team {slug} is now active (waited {elapsed}s)")
            return team

        if status not in ["starting", "suspended"]:
            # Team is in an unexpected state
            logger.warning(f"Team {slug} is in unexpected state: {status}")
            return None

    logger.warning(f"Timeout waiting for team {slug} to become active")
    return None


def proxy_response(status_code: int, data: Any):
    """Convert proxy response to FastAPI response"""
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data.get("detail", str(data)))
    return data


# =============================================================================
# Board Endpoints
# =============================================================================

@router.get("/{slug}/boards")
async def list_boards(
    slug: str,
    auth: AuthContext = Depends(require_scope("boards:read"))
):
    """List all boards in a team.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: boards:read
    """
    await verify_team_access(slug, auth)
    status, data = await team_proxy.get(slug, "/boards", auth_token=auth.raw_token)
    return proxy_response(status, data)


@router.get("/{slug}/boards/{board_id}")
async def get_board(
    slug: str,
    board_id: str,
    include_archived: bool = Query(False, description="Include archived cards"),
    auth: AuthContext = Depends(require_scope("boards:read"))
):
    """Get a board with its columns and cards.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: boards:read
    """
    await verify_team_access(slug, auth)
    status, data = await team_proxy.get(
        slug,
        f"/boards/{board_id}",
        params={"include_archived": include_archived},
        auth_token=auth.raw_token
    )
    return proxy_response(status, data)


# =============================================================================
# Column Endpoints
# =============================================================================

@router.get("/{slug}/columns")
async def list_columns(
    slug: str,
    board_id: Optional[str] = Query(None, description="Filter by board"),
    auth: AuthContext = Depends(require_scope("boards:read"))
):
    """List columns, optionally filtered by board.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: boards:read
    """
    await verify_team_access(slug, auth)
    params = {}
    if board_id:
        params["board_id"] = board_id
    status, data = await team_proxy.get(slug, "/columns", params=params, auth_token=auth.raw_token)
    return proxy_response(status, data)


@router.post("/{slug}/columns")
async def create_column(
    slug: str,
    data: ColumnCreate,
    auth: AuthContext = Depends(require_scope("boards:write"))
):
    """Create a new column in a board.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: boards:write
    """
    await verify_team_access(slug, auth)
    status, response = await team_proxy.post(slug, "/columns", json=data.model_dump(), auth_token=auth.raw_token)
    return proxy_response(status, response)


@router.patch("/{slug}/columns/{column_id}")
async def update_column(
    slug: str,
    column_id: str,
    data: ColumnUpdate,
    auth: AuthContext = Depends(require_scope("boards:write"))
):
    """Update a column.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: boards:write
    """
    await verify_team_access(slug, auth)
    status, response = await team_proxy.patch(
        slug,
        f"/columns/{column_id}",
        json=data.model_dump(exclude_unset=True),
        auth_token=auth.raw_token
    )
    return proxy_response(status, response)


@router.delete("/{slug}/columns/{column_id}")
async def delete_column(
    slug: str,
    column_id: str,
    auth: AuthContext = Depends(require_scope("boards:write"))
):
    """Delete a column.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: boards:write
    """
    await verify_team_access(slug, auth)
    status, response = await team_proxy.delete(slug, f"/columns/{column_id}", auth_token=auth.raw_token)
    return proxy_response(status, response)


# =============================================================================
# Card Endpoints
# =============================================================================

@router.get("/{slug}/cards")
async def list_cards(
    slug: str,
    column_id: Optional[str] = Query(None, description="Filter by column"),
    auth: AuthContext = Depends(require_scope("cards:read"))
):
    """List all cards, optionally filtered by column.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: cards:read
    """
    await verify_team_access(slug, auth)
    params = {}
    if column_id:
        params["column_id"] = column_id
    status, data = await team_proxy.get(slug, "/cards", params=params, auth_token=auth.raw_token)
    return proxy_response(status, data)


@router.post("/{slug}/cards")
async def create_card(
    slug: str,
    data: CardCreate,
    auth: AuthContext = Depends(require_scope("cards:write"))
):
    """Create a new card.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: cards:write
    """
    await verify_team_access(slug, auth)
    status, response = await team_proxy.post(slug, "/cards", json=data.model_dump(), auth_token=auth.raw_token)
    return proxy_response(status, response)


@router.get("/{slug}/cards/{card_id}")
async def get_card(
    slug: str,
    card_id: str,
    auth: AuthContext = Depends(require_scope("cards:read"))
):
    """Get a single card by ID.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: cards:read
    """
    await verify_team_access(slug, auth)
    status, data = await team_proxy.get(slug, f"/cards/{card_id}", auth_token=auth.raw_token)
    return proxy_response(status, data)


@router.patch("/{slug}/cards/{card_id}")
async def update_card(
    slug: str,
    card_id: str,
    data: CardUpdate,
    auth: AuthContext = Depends(require_scope("cards:write"))
):
    """Update a card.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: cards:write
    """
    await verify_team_access(slug, auth)
    status, response = await team_proxy.patch(
        slug,
        f"/cards/{card_id}",
        json=data.model_dump(exclude_unset=True),
        auth_token=auth.raw_token
    )
    return proxy_response(status, response)


@router.delete("/{slug}/cards/{card_id}")
async def delete_card(
    slug: str,
    card_id: str,
    auth: AuthContext = Depends(require_scope("cards:write"))
):
    """Delete a card.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: cards:write
    """
    await verify_team_access(slug, auth)
    status, response = await team_proxy.delete(slug, f"/cards/{card_id}", auth_token=auth.raw_token)
    return proxy_response(status, response)


@router.post("/{slug}/cards/{card_id}/move")
async def move_card(
    slug: str,
    card_id: str,
    data: CardMove,
    auth: AuthContext = Depends(require_scope("cards:write"))
):
    """Move a card to a different column and/or position.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: cards:write
    """
    await verify_team_access(slug, auth)
    status, response = await team_proxy.post(
        slug,
        f"/cards/{card_id}/move",
        params={"column_id": data.column_id, "position": data.position},
        auth_token=auth.raw_token
    )
    return proxy_response(status, response)


@router.post("/{slug}/cards/{card_id}/archive")
async def archive_card(
    slug: str,
    card_id: str,
    auth: AuthContext = Depends(require_scope("cards:write"))
):
    """Archive a card.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: cards:write
    """
    await verify_team_access(slug, auth)
    status, response = await team_proxy.post(slug, f"/cards/{card_id}/archive", auth_token=auth.raw_token)
    return proxy_response(status, response)


@router.post("/{slug}/cards/{card_id}/restore")
async def restore_card(
    slug: str,
    card_id: str,
    auth: AuthContext = Depends(require_scope("cards:write"))
):
    """Restore an archived card.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: cards:write
    """
    await verify_team_access(slug, auth)
    status, response = await team_proxy.post(slug, f"/cards/{card_id}/restore", auth_token=auth.raw_token)
    return proxy_response(status, response)


# =============================================================================
# Labels Endpoints
# =============================================================================

@router.get("/{slug}/boards/{board_id}/labels")
async def list_labels(
    slug: str,
    board_id: str,
    auth: AuthContext = Depends(require_scope("boards:read"))
):
    """List all labels in a board.

    Authentication: Portal API token (pk_*) or JWT
    Required scope: boards:read
    """
    await verify_team_access(slug, auth)
    status, data = await team_proxy.get(slug, f"/boards/{board_id}/labels", auth_token=auth.raw_token)
    return proxy_response(status, data)
