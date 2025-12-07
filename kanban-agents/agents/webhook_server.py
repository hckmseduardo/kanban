"""
Webhook Server

FastAPI server that receives Kanban webhook events and triggers
the appropriate agent based on card status changes.
"""

import hmac
import hashlib
import asyncio
import logging
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel

from .kanban_client import AsyncKanbanClient
from .personalities import get_personality, get_agent_for_column
from .controller import MultiAgentController

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Kanban Agents Webhook Server",
    description="Receives Kanban events and triggers AI agents",
    version="1.0.0"
)

# Configuration - set via environment or override
class WebhookConfig:
    webhook_secret: str = ""
    kanban_url: str = "http://localhost:8000"
    repo_path: str = "/path/to/repo"
    anthropic_api_key: str = ""
    agent_label: str = "agent"

config = WebhookConfig()


class WebhookPayload(BaseModel):
    """Webhook payload structure."""
    event: str
    data: dict
    timestamp: str


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify the webhook signature."""
    if not secret:
        return True  # No secret configured, skip verification

    if not signature:
        return False

    expected = "sha256=" + hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(signature, expected)


@app.post("/webhook")
async def handle_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Handle incoming webhook events from Kanban.

    Events:
    - card.created: New card created
    - card.moved: Card moved to different column
    - card.updated: Card properties changed
    - card.deleted: Card deleted
    """
    # Get raw body for signature verification
    body = await request.body()

    # Verify signature
    signature = request.headers.get("X-Webhook-Signature", "")
    if not verify_signature(body, signature, config.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse payload
    payload = await request.json()
    event = payload.get("event")
    data = payload.get("data", {})

    logger.info(f"Received webhook event: {event}")

    # Route to appropriate handler
    if event == "card.created":
        background_tasks.add_task(handle_card_created, data)

    elif event == "card.moved":
        background_tasks.add_task(handle_card_moved, data)

    elif event == "card.updated":
        background_tasks.add_task(handle_card_updated, data)

    elif event == "webhook.test":
        logger.info("Received test webhook")

    return {"status": "received", "event": event}


async def handle_card_created(card: dict):
    """Handle new card creation."""
    # Check if card has agent label
    if config.agent_label not in card.get("labels", []):
        logger.debug(f"Card {card['id']} doesn't have agent label, skipping")
        return

    logger.info(f"New agent card created: {card['title']}")

    # Get column info to determine which agent
    column_id = card.get("column_id")

    async with AsyncKanbanClient(config.kanban_url) as kanban:
        # We need to get column name - fetch from board
        # For now, assume triager for new cards
        await process_card_with_agent(card, "triager", kanban)


async def handle_card_moved(card: dict):
    """Handle card moved to different column."""
    if config.agent_label not in card.get("labels", []):
        return

    # Get the destination column name
    to_column_id = card.get("to_column_id") or card.get("column_id")
    to_column_name = card.get("to_column_name", "")

    # Determine agent based on column
    agent_type = get_agent_for_column(to_column_name)

    if not agent_type:
        logger.info(f"No agent for column '{to_column_name}'")
        return

    logger.info(f"Card '{card['title']}' moved to '{to_column_name}', triggering {agent_type}")

    async with AsyncKanbanClient(config.kanban_url) as kanban:
        await process_card_with_agent(card, agent_type, kanban)


async def handle_card_updated(card: dict):
    """Handle card property updates."""
    # Only process if label was just added
    if config.agent_label not in card.get("labels", []):
        return

    # Could trigger re-processing here if needed
    logger.debug(f"Card {card['id']} updated")


async def process_card_with_agent(
    card: dict,
    agent_type: str,
    kanban: AsyncKanbanClient
):
    """Process a card with the specified agent."""
    personality = get_personality(agent_type)

    logger.info(f"Processing '{card['title']}' with {personality['name']}")

    # Post starting comment
    await kanban.add_comment(
        card["id"],
        f"{personality['emoji']} **{personality['name']}** is now working on this...",
        author_name=personality["name"]
    )

    try:
        # Build prompt
        prompt = build_agent_prompt(card, personality)

        # Run Claude
        result = await run_claude_agent(prompt, personality)

        # Post result
        await kanban.add_comment(
            card["id"],
            f"{personality['emoji']} **{personality['name']}** completed:\n\n{result[:2000]}",
            author_name=personality["name"]
        )

        logger.info(f"Successfully processed card {card['id']}")

    except Exception as e:
        logger.error(f"Error processing card {card['id']}: {e}")

        await kanban.add_comment(
            card["id"],
            f"{personality['emoji']} **{personality['name']}** error: {str(e)}",
            author_name=personality["name"]
        )


def build_agent_prompt(card: dict, personality: dict) -> str:
    """Build the prompt for the agent."""
    checklist = card.get("checklist", [])
    checklist_str = "\n".join(
        f"- [{'x' if item.get('completed') else ' '}] {item['text']}"
        for item in checklist
    ) or "No checklist"

    return f"""
{personality['system_prompt']}

---

## Ticket

**Title:** {card['title']}

**Description:**
{card.get('description', 'No description')}

**Labels:** {', '.join(card.get('labels', [])) or 'None'}
**Priority:** {card.get('priority', 'Not set')}

**Checklist:**
{checklist_str}

---

Repository path: {config.repo_path}

Perform your role and provide a detailed report.
"""


async def run_claude_agent(prompt: str, personality: dict) -> str:
    """Run Claude with the prompt."""
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.anthropic_api_key)

        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )

        return response.content[0].text

    except ImportError:
        return f"[{personality['name']} would process this ticket]"


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "kanban_url": config.kanban_url,
            "agent_label": config.agent_label,
            "webhook_secret_set": bool(config.webhook_secret)
        }
    }


# List available agents
@app.get("/agents")
async def list_agents():
    """List available agent personalities."""
    from .personalities import list_personalities
    return {"agents": list_personalities()}


def create_app(
    webhook_secret: str = "",
    kanban_url: str = "http://localhost:8000",
    repo_path: str = "/path/to/repo",
    anthropic_api_key: str = "",
    agent_label: str = "agent"
) -> FastAPI:
    """Create configured FastAPI app."""
    config.webhook_secret = webhook_secret
    config.kanban_url = kanban_url
    config.repo_path = repo_path
    config.anthropic_api_key = anthropic_api_key
    config.agent_label = agent_label
    return app


if __name__ == "__main__":
    import uvicorn
    import os

    config.webhook_secret = os.getenv("WEBHOOK_SECRET", "")
    config.kanban_url = os.getenv("KANBAN_URL", "http://localhost:8000")
    config.repo_path = os.getenv("REPO_PATH", "/path/to/repo")
    config.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    config.agent_label = os.getenv("AGENT_LABEL", "agent")

    uvicorn.run(app, host="0.0.0.0", port=8080)
