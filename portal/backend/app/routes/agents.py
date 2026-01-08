"""Agent webhook routes for on-demand AI processing.

This module receives card events from kanban-team instances and queues
them for processing by Claude Code subprocess agents.
"""

import hashlib
import hmac
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel

from app.config import settings
from app.services.database_service import db_service
from app.services.task_service import task_service

logger = logging.getLogger(__name__)

router = APIRouter()


# Column to agent type mapping
COLUMN_AGENTS = {
    "Backlog": "product_owner",
    "To Do": "architect",
    "Development": "developer",
    "In Progress": "developer",
    "Code Review": "reviewer",
    "Review": "reviewer",
    "Testing": "qa",
    "QA": "qa",
    "Done": "release",
    "Triage": "triage",
    "Analysis": "support_analyst",
}


class CardEventPayload(BaseModel):
    """Webhook payload for card events from kanban-team."""
    event: str  # card.moved, card.created, etc.
    card: dict  # Card data
    previous_column: Optional[dict] = None
    board: Optional[dict] = None
    sandbox_id: Optional[str] = None  # Sandbox identifier for isolation
    workspace_slug: Optional[str] = None


def verify_webhook_signature(
    body: bytes,
    signature: str,
    secret: str
) -> bool:
    """Verify HMAC-SHA256 webhook signature."""
    expected = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


@router.post("/webhook")
async def receive_card_event(
    request: Request,
    payload: CardEventPayload,
    x_webhook_signature: Optional[str] = Header(None),
    x_workspace_slug: Optional[str] = Header(None),
):
    """
    Receive card events from kanban-team and queue agent tasks.

    This endpoint is called by kanban-team when:
    - A card is moved to a new column
    - A card is created in a column that triggers an agent

    The request should include:
    - X-Webhook-Signature: HMAC-SHA256 signature
    - X-Workspace-Slug: Workspace identifier (or in payload)
    """
    # Get workspace slug from header or payload
    workspace_slug = x_workspace_slug or payload.workspace_slug
    if not workspace_slug:
        raise HTTPException(
            status_code=400,
            detail="Missing workspace identifier"
        )

    # Look up workspace to get webhook secret
    workspace = db_service.get_workspace_by_slug(workspace_slug)
    if not workspace:
        logger.warning(f"Unknown workspace: {workspace_slug}")
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Verify webhook signature if secret is configured
    # For sandbox events, use sandbox-specific secret
    webhook_secret = None
    if payload.sandbox_id:
        sandbox = db_service.get_sandbox_by_full_slug(payload.sandbox_id)
        if sandbox:
            webhook_secret = sandbox.get("agent_webhook_secret")

    # Fall back to workspace-level secret
    if not webhook_secret:
        webhook_secret = workspace.get("agent_webhook_secret")

    if webhook_secret and x_webhook_signature:
        body = await request.body()
        if not verify_webhook_signature(body, x_webhook_signature, webhook_secret):
            logger.warning(f"Invalid webhook signature for {workspace_slug}")
            raise HTTPException(status_code=401, detail="Invalid signature")

    # Only process card.moved events for now
    if payload.event != "card.moved":
        logger.debug(f"Ignoring event type: {payload.event}")
        return {"status": "ignored", "reason": f"Event type {payload.event} not processed"}

    # Get card details
    card = payload.card
    column_name = card.get("column", {}).get("name", "")

    # Determine agent type from column
    agent_type = COLUMN_AGENTS.get(column_name)
    if not agent_type:
        logger.debug(f"No agent configured for column: {column_name}")
        return {"status": "ignored", "reason": f"No agent for column {column_name}"}

    # Get sandbox details for isolation
    sandbox_id = payload.sandbox_id
    git_branch = "main"
    target_project_path = f"/data/repos/{workspace_slug}"

    if sandbox_id:
        sandbox = db_service.get_sandbox_by_full_slug(sandbox_id)
        if sandbox:
            git_branch = sandbox.get("git_branch", f"sandbox/{sandbox_id}")
            target_project_path = f"/data/repos/{workspace_slug}/sandboxes/{sandbox_id}"

    # Build kanban API URL
    if settings.port == 443:
        kanban_api_url = f"https://{workspace_slug}.{settings.domain}/api"
    else:
        kanban_api_url = f"https://{workspace_slug}.{settings.domain}:{settings.port}/api"

    # Queue agent task
    try:
        task_id = await task_service.create_agent_task(
            card_id=card.get("id"),
            card_title=card.get("title", "Untitled"),
            card_description=card.get("description", ""),
            column_name=column_name,
            agent_type=agent_type,
            sandbox_id=sandbox_id or workspace_slug,
            workspace_slug=workspace_slug,
            git_branch=git_branch,
            kanban_api_url=kanban_api_url,
            target_project_path=target_project_path,
            user_id=card.get("assignee", {}).get("id", "system"),
            board_id=payload.board.get("id") if payload.board else None,
            labels=card.get("labels", []),
            priority="high" if "urgent" in [l.lower() for l in card.get("labels", [])] else "normal",
        )

        logger.info(
            f"Agent task queued: {task_id} "
            f"(card={card.get('id')}, agent={agent_type}, sandbox={sandbox_id})"
        )

        return {
            "status": "queued",
            "task_id": task_id,
            "agent_type": agent_type,
            "card_id": card.get("id"),
        }

    except Exception as e:
        logger.error(f"Failed to queue agent task: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to queue agent task: {str(e)}"
        )


@router.get("/status/{task_id}")
async def get_agent_task_status(task_id: str):
    """Get status of an agent task."""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task_id": task_id,
        "status": task.get("status"),
        "progress": task.get("progress"),
        "error": task.get("error"),
        "result": task.get("result"),
    }
