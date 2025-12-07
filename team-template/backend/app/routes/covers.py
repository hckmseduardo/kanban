"""
Card Cover Images API

Allows cards to have a cover image displayed at the top of the card.
Covers can be set from:
- An uploaded image attachment
- A color (solid background)
- An external URL
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal
from pathlib import Path
import os
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


class CoverUpdate(BaseModel):
    type: Literal["image", "color", "url", "attachment"]
    value: str  # For image: attachment_id, for color: hex color, for url: image URL


# Predefined cover colors
COVER_COLORS = {
    "red": "#EF4444",
    "orange": "#F97316",
    "amber": "#F59E0B",
    "yellow": "#EAB308",
    "lime": "#84CC16",
    "green": "#22C55E",
    "emerald": "#10B981",
    "teal": "#14B8A6",
    "cyan": "#06B6D4",
    "sky": "#0EA5E9",
    "blue": "#3B82F6",
    "indigo": "#6366F1",
    "violet": "#8B5CF6",
    "purple": "#A855F7",
    "fuchsia": "#D946EF",
    "pink": "#EC4899",
    "rose": "#F43F5E",
    "gray": "#6B7280",
}


@router.get("/covers/colors")
async def get_cover_colors():
    """Get available cover colors."""
    return {
        "colors": [
            {"name": name, "hex": hex_code}
            for name, hex_code in COVER_COLORS.items()
        ]
    }


@router.put("/cards/{card_id}/cover")
async def set_card_cover(card_id: str, cover: CoverUpdate):
    """Set or update a card's cover."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    cover_data = {
        "type": cover.type,
        "value": cover.value
    }

    # Validate based on type
    if cover.type == "color":
        # Accept named color or hex
        if cover.value.lower() in COVER_COLORS:
            cover_data["hex"] = COVER_COLORS[cover.value.lower()]
            cover_data["value"] = cover.value.lower()
        elif cover.value.startswith("#"):
            cover_data["hex"] = cover.value
        else:
            raise HTTPException(status_code=400, detail="Invalid color. Use a named color or hex code.")

    elif cover.type == "attachment":
        # Verify attachment exists and is an image
        attachments = card.get("attachments", [])
        # Note: Attachments are stored in the attachments table, not on the card
        # We'll need to check the attachments API
        pass  # Allow any attachment ID for now

    elif cover.type == "url":
        # Basic URL validation
        if not cover.value.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Invalid URL. Must start with http:// or https://")

    db.cards.update({"cover": cover_data}, Q.id == card_id)

    return {
        "card_id": card_id,
        "cover": cover_data
    }


@router.delete("/cards/{card_id}/cover")
async def remove_card_cover(card_id: str):
    """Remove a card's cover."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    db.cards.update({"cover": None}, Q.id == card_id)

    return {"message": "Cover removed"}


@router.get("/cards/{card_id}/cover")
async def get_card_cover(card_id: str):
    """Get a card's cover."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    cover = card.get("cover")

    return {
        "card_id": card_id,
        "cover": cover
    }


@router.post("/cards/{card_id}/cover/from-first-attachment")
async def set_cover_from_first_image_attachment(card_id: str):
    """Set the card cover from the first image attachment."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Get attachments for this card
    attachments = db.attachments.search(Q.card_id == card_id)

    # Find first image attachment
    image_attachment = None
    for att in attachments:
        content_type = att.get("content_type", "")
        if content_type.startswith("image/"):
            image_attachment = att
            break

    if not image_attachment:
        raise HTTPException(status_code=404, detail="No image attachments found")

    cover_data = {
        "type": "attachment",
        "value": image_attachment["id"],
        "attachment_filename": image_attachment.get("original_filename")
    }

    db.cards.update({"cover": cover_data}, Q.id == card_id)

    return {
        "card_id": card_id,
        "cover": cover_data
    }
