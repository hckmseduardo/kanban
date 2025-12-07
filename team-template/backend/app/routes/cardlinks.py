"""
Card Links API

Allows cards to be linked to related cards across boards.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Literal
from pathlib import Path
import os
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


class CardLinkCreate(BaseModel):
    target_card_id: str
    link_type: Literal["related", "duplicates", "is_duplicated_by", "parent", "child"] = "related"


LINK_TYPE_INVERSE = {
    "related": "related",
    "duplicates": "is_duplicated_by",
    "is_duplicated_by": "duplicates",
    "parent": "child",
    "child": "parent"
}


@router.get("/cards/{card_id}/links")
async def get_card_links(card_id: str):
    """Get all links for a card."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    links = card.get("links", [])

    # Enrich with target card details
    enriched_links = []
    for link in links:
        target = db.cards.get(Q.id == link["target_id"])
        if target:
            column = db.columns.get(Q.id == target.get("column_id"))
            board = db.boards.get(Q.id == column.get("board_id")) if column else None

            enriched_links.append({
                "id": link["id"],
                "target_id": link["target_id"],
                "link_type": link["link_type"],
                "target_title": target.get("title"),
                "target_column": column.get("name") if column else None,
                "target_board_id": board.get("id") if board else None,
                "target_board_name": board.get("name") if board else None,
                "target_archived": target.get("archived", False),
                "created_at": link.get("created_at")
            })

    return {
        "card_id": card_id,
        "links": enriched_links,
        "count": len(enriched_links)
    }


@router.post("/cards/{card_id}/links")
async def create_card_link(card_id: str, link: CardLinkCreate):
    """Create a link between two cards."""
    db.initialize()

    # Validate source card
    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Validate target card
    target = db.cards.get(Q.id == link.target_card_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target card not found")

    # Prevent self-linking
    if card_id == link.target_card_id:
        raise HTTPException(status_code=400, detail="Cannot link a card to itself")

    # Check if link already exists
    existing_links = card.get("links", [])
    if any(l["target_id"] == link.target_card_id for l in existing_links):
        raise HTTPException(status_code=400, detail="Link already exists")

    # Create link on source card
    new_link = {
        "id": db.generate_id(),
        "target_id": link.target_card_id,
        "link_type": link.link_type,
        "created_at": db.timestamp()
    }
    existing_links.append(new_link)
    db.cards.update({"links": existing_links}, Q.id == card_id)

    # Create inverse link on target card
    inverse_type = LINK_TYPE_INVERSE.get(link.link_type, "related")
    target_links = target.get("links", [])
    inverse_link = {
        "id": db.generate_id(),
        "target_id": card_id,
        "link_type": inverse_type,
        "created_at": db.timestamp()
    }
    target_links.append(inverse_link)
    db.cards.update({"links": target_links}, Q.id == link.target_card_id)

    # Log activity
    db.log_activity(card_id, card.get("board_id", ""), "card_linked", details={
        "target_id": link.target_card_id,
        "target_title": target.get("title"),
        "link_type": link.link_type
    })

    return {
        "message": "Cards linked",
        "link": new_link
    }


@router.delete("/cards/{card_id}/links/{link_id}")
async def delete_card_link(card_id: str, link_id: str):
    """Delete a link between two cards."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    links = card.get("links", [])
    link = next((l for l in links if l["id"] == link_id), None)

    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    target_id = link["target_id"]

    # Remove link from source card
    links = [l for l in links if l["id"] != link_id]
    db.cards.update({"links": links}, Q.id == card_id)

    # Remove inverse link from target card
    target = db.cards.get(Q.id == target_id)
    if target:
        target_links = target.get("links", [])
        target_links = [l for l in target_links if l["target_id"] != card_id]
        db.cards.update({"links": target_links}, Q.id == target_id)

    # Log activity
    db.log_activity(card_id, card.get("board_id", ""), "card_unlinked", details={
        "target_id": target_id,
        "target_title": target.get("title") if target else None
    })

    return {"message": "Link removed"}


@router.get("/cards/{card_id}/links/suggestions")
async def get_link_suggestions(card_id: str, q: str = "", limit: int = 10):
    """Get card suggestions for linking."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Get already linked card IDs
    existing_links = card.get("links", [])
    linked_ids = {l["target_id"] for l in existing_links}
    linked_ids.add(card_id)  # Exclude self

    suggestions = []
    query_lower = q.lower()

    # Search all cards
    all_cards = db.cards.all()
    for c in all_cards:
        if c["id"] in linked_ids:
            continue
        if c.get("archived"):
            continue

        # Match by title
        if q and query_lower not in c.get("title", "").lower():
            continue

        column = db.columns.get(Q.id == c.get("column_id"))
        board = db.boards.get(Q.id == column.get("board_id")) if column else None

        suggestions.append({
            "id": c["id"],
            "title": c.get("title"),
            "board_id": board.get("id") if board else None,
            "board_name": board.get("name") if board else None,
            "column_name": column.get("name") if column else None
        })

        if len(suggestions) >= limit:
            break

    return {"suggestions": suggestions}
