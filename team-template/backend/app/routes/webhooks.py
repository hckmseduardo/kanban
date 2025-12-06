"""Webhook routes for AI agent integrations"""

from fastapi import APIRouter, HTTPException
from ..models.webhook import WebhookCreate, WebhookUpdate
from ..services.database import Database, Q
from pathlib import Path
import os

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


@router.get("")
async def list_webhooks():
    """List all webhooks"""
    db.initialize()
    webhooks = db.webhooks.all()
    # Hide secrets
    for wh in webhooks:
        if wh.get("secret"):
            wh["secret"] = "***"
    return webhooks


@router.post("")
async def create_webhook(data: WebhookCreate):
    """Create a new webhook"""
    db.initialize()

    webhook = {
        "id": db.generate_id(),
        "name": data.name,
        "url": data.url,
        "events": data.events,
        "secret": data.secret,
        "active": data.active,
        "created_at": db.timestamp()
    }
    db.webhooks.insert(webhook)

    # Hide secret in response
    response = {**webhook}
    if response.get("secret"):
        response["secret"] = "***"
    return response


@router.get("/{webhook_id}")
async def get_webhook(webhook_id: str):
    """Get a webhook"""
    db.initialize()
    webhook = db.webhooks.get(Q.id == webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    if webhook.get("secret"):
        webhook["secret"] = "***"
    return webhook


@router.patch("/{webhook_id}")
async def update_webhook(webhook_id: str, data: WebhookUpdate):
    """Update a webhook"""
    db.initialize()

    webhook = db.webhooks.get(Q.id == webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    updates = data.model_dump(exclude_unset=True)
    db.webhooks.update(updates, Q.id == webhook_id)

    result = {**webhook, **updates}
    if result.get("secret"):
        result["secret"] = "***"
    return result


@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: str):
    """Delete a webhook"""
    db.initialize()

    webhook = db.webhooks.get(Q.id == webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    db.webhooks.remove(Q.id == webhook_id)
    return {"deleted": True}


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: str):
    """Send a test event to a webhook"""
    db.initialize()

    webhook = db.webhooks.get(Q.id == webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    from ..services.webhook_service import send_webhook

    test_payload = {
        "event": "webhook.test",
        "data": {"message": "Test webhook delivery"}
    }

    success = await send_webhook(webhook["url"], test_payload, webhook.get("secret"))

    return {"success": success, "url": webhook["url"]}
