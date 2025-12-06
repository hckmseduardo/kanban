"""Webhook service for triggering AI agent integrations"""

import httpx
import hashlib
import hmac
import json
import logging
from ..services.database import Database

logger = logging.getLogger(__name__)


async def send_webhook(url: str, payload: dict, secret: str = None) -> bool:
    """Send a webhook payload to a URL"""
    try:
        headers = {"Content-Type": "application/json"}
        body = json.dumps(payload)

        # Add signature if secret is provided
        if secret:
            signature = hmac.new(
                secret.encode(),
                body.encode(),
                hashlib.sha256
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, content=body, headers=headers)
            return response.status_code < 400

    except Exception as e:
        logger.error(f"Webhook delivery failed: {e}")
        return False


async def trigger_webhooks(db: Database, event: str, data: dict):
    """Trigger all webhooks subscribed to an event"""
    try:
        webhooks = db.webhooks.all()

        for webhook in webhooks:
            if not webhook.get("active", True):
                continue

            if event not in webhook.get("events", []):
                continue

            payload = {
                "event": event,
                "data": data,
                "timestamp": db.timestamp()
            }

            # Fire and forget - don't wait for response
            await send_webhook(
                webhook["url"],
                payload,
                webhook.get("secret")
            )

    except Exception as e:
        logger.error(f"Error triggering webhooks: {e}")
