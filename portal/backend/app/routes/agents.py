"""Agent webhook routes for on-demand AI processing.

This module receives card events from kanban-team instances and queues
them for processing by Claude Code subprocess agents.
"""

import hashlib
import hmac
import httpx
import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel

from app.config import settings
from app.services.database_service import db_service
from app.services.task_service import task_service

logger = logging.getLogger(__name__)

router = APIRouter()


async def get_agent_config_for_column(
    kanban_api_url: str,
    column_name: str,
    board_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Query kanban-team to get agent configuration for a column.

    This makes kanban-team the single source of truth for agent configuration.
    Returns the full agent_config including persona, tool_profile, and timeout.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{kanban_api_url}/agents/resolve",
                params={"column_name": column_name, "board_id": board_id},
                headers={"X-Service-Secret": settings.cross_domain_secret}
            )

            if response.status_code == 404:
                # No agent configured for this column
                logger.debug(f"No agent configured for column '{column_name}' in board {board_id}")
                return None

            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as e:
        logger.warning(f"Failed to get agent config from kanban-team: {e}")
        return None
    except httpx.RequestError as e:
        logger.error(f"Request error getting agent config: {e}")
        return None


class CardEventPayload(BaseModel):
    """Webhook payload for card events from kanban-team."""
    event: str  # card.moved, card.created, etc.
    card: dict  # Card data
    previous_column: Optional[dict] = None
    board: Optional[dict] = None
    sandbox_id: Optional[str] = None  # Sandbox identifier for isolation
    sandbox_slug: Optional[str] = None  # Sandbox slug from card's linked sandbox
    workspace_slug: Optional[str] = None
    claude_session_id: Optional[str] = None  # Persistent Claude CLI session for this card


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
    board_id = payload.board.get("id") if payload.board else None
    claude_session_id = card.get("claude_session_id") or payload.claude_session_id

    # Get sandbox details for isolation
    # sandbox_id from payload should be UUID, but might be full_slug if card was created incorrectly
    sandbox_id = payload.sandbox_id
    sandbox_slug = payload.sandbox_slug  # May be None if kanban-team lookup failed
    git_branch = "main"
    target_project_path = f"/data/repos/{workspace_slug}"
    sandbox_record = None  # Store for later use

    if sandbox_id:
        # First try to look up by UUID
        sandbox_record = db_service.get_sandbox_by_id(sandbox_id)

        # If not found and sandbox_id looks like a full_slug (contains workspace prefix),
        # try to look up by full_slug - this handles cards created with wrong sandbox_id format
        if not sandbox_record and '-' in sandbox_id:
            logger.warning(f"sandbox_id '{sandbox_id}' not found by UUID, trying as full_slug")
            sandbox_record = db_service.get_sandbox_by_full_slug(sandbox_id)

        if sandbox_record:
            # Use the actual UUID from the record, not the payload value
            sandbox_id = sandbox_record.get("id", sandbox_id)
            full_slug = sandbox_record.get("full_slug", sandbox_id)
            git_branch = sandbox_record.get("git_branch", f"sandbox/{full_slug}")
            target_project_path = f"/data/repos/{workspace_slug}/sandboxes/{full_slug}"
            # Derive sandbox_slug from record if not in payload
            if not sandbox_slug:
                sandbox_slug = sandbox_record.get("slug")
            logger.info(f"Resolved sandbox: id={sandbox_id}, slug={sandbox_slug}, full_slug={full_slug}")

    # Build kanban API URL
    if settings.port == 443:
        kanban_api_url = f"https://{workspace_slug}.{settings.domain}/api"
    else:
        kanban_api_url = f"https://{workspace_slug}.{settings.domain}:{settings.port}/api"

    # Get agent configuration from kanban-team (single source of truth)
    agent_config = await get_agent_config_for_column(kanban_api_url, column_name, board_id)
    if not agent_config:
        logger.debug(f"No agent configured for column: {column_name}")
        return {"status": "ignored", "reason": f"No agent for column {column_name}"}

    # Queue agent task with full agent configuration
    try:
        task_id = await task_service.create_agent_task(
            card_id=card.get("id"),
            card_title=card.get("title", "Untitled"),
            card_description=card.get("description", ""),
            column_name=column_name,
            agent_config=agent_config,
            sandbox_id=sandbox_id or workspace_slug,
            sandbox_slug=sandbox_slug,
            claude_session_id=claude_session_id,
            workspace_slug=workspace_slug,
            git_branch=git_branch,
            kanban_api_url=kanban_api_url,
            target_project_path=target_project_path,
            user_id=card.get("assignee", {}).get("id", "system"),
            board_id=board_id,
            labels=card.get("labels", []),
            priority="high" if "urgent" in [l.lower() for l in card.get("labels", [])] else "normal",
            github_repo_url=workspace.get("github_repo_url"),
            card_number=card.get("card_number"),
        )

        card_num = card.get('card_number') or card.get('id', '')[:8]
        logger.info(
            f"Agent task queued: {task_id} "
            f"(card={card_num}, agent={agent_config['agent_name']}, sandbox={sandbox_id})"
        )

        return {
            "status": "queued",
            "task_id": task_id,
            "agent_name": agent_config["agent_name"],
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


class EnhanceOptions(BaseModel):
    """Options for description enhancement."""
    acceptance_criteria: bool = True
    complexity_estimate: bool = True
    suggest_labels: bool = True
    refine_description: bool = True


class EnhanceDescriptionRequest(BaseModel):
    """Request body for enhance description via portal."""
    card_id: str
    card_title: str
    card_description: str
    mode: str = "append"  # "append" or "replace"
    options: EnhanceOptions = EnhanceOptions()
    apply_labels: bool = True
    add_checklist: bool = True
    sandbox_slug: Optional[str] = None  # Sandbox slug for codebase context


@router.post("/enhance-description")
async def enhance_card_description(
    request: Request,
    payload: EnhanceDescriptionRequest,
    x_workspace_slug: Optional[str] = Header(None),
    x_webhook_signature: Optional[str] = Header(None),
):
    """
    Enhance a card's description using AI via Claude Code subprocess.

    This endpoint is called by kanban-team when a user clicks "Enhance with AI".
    It queues a task for the worker to process using ClaudeCodeRunner.

    The request should include:
    - X-Workspace-Slug: Workspace identifier
    - X-Webhook-Signature: HMAC-SHA256 signature (optional)
    """
    workspace_slug = x_workspace_slug
    if not workspace_slug:
        raise HTTPException(
            status_code=400,
            detail="Missing X-Workspace-Slug header"
        )

    # Look up workspace
    workspace = db_service.get_workspace_by_slug(workspace_slug)
    if not workspace:
        logger.warning(f"Unknown workspace: {workspace_slug}")
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Verify webhook signature if secret is configured
    webhook_secret = workspace.get("agent_webhook_secret")
    if webhook_secret and x_webhook_signature:
        body = await request.body()
        if not verify_webhook_signature(body, x_webhook_signature, webhook_secret):
            logger.warning(f"Invalid webhook signature for {workspace_slug}")
            raise HTTPException(status_code=401, detail="Invalid signature")

    # Build kanban API URL
    if settings.port == 443:
        kanban_api_url = f"https://{workspace_slug}.{settings.domain}/api"
    else:
        kanban_api_url = f"https://{workspace_slug}.{settings.domain}:{settings.port}/api"

    # Queue enhance description task
    try:
        task_id = await task_service.create_enhance_description_task(
            card_id=payload.card_id,
            card_title=payload.card_title,
            card_description=payload.card_description,
            workspace_slug=workspace_slug,
            kanban_api_url=kanban_api_url,
            user_id="system",  # TODO: Get from auth
            options=payload.options.model_dump(),
            mode=payload.mode,
            apply_labels=payload.apply_labels,
            add_checklist=payload.add_checklist,
            sandbox_slug=payload.sandbox_slug,
        )

        logger.info(
            f"Enhance description task queued: {task_id} "
            f"(card={payload.card_id}, workspace={workspace_slug})"
        )

        return {
            "status": "queued",
            "task_id": task_id,
            "card_id": payload.card_id,
        }

    except Exception as e:
        logger.error(f"Failed to queue enhance task: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to queue enhancement task: {str(e)}"
        )
