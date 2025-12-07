"""
Card Dependencies (Blockers) API

Manages blocking relationships between cards.
A card can block other cards, indicating that those cards cannot proceed until this one is completed.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
import os
from ..services.database import Database, Q

router = APIRouter()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
db = Database(DATA_DIR / "db" / "team.json")


class DependencyCreate(BaseModel):
    blocker_id: str  # The card that is blocking
    blocked_id: str  # The card that is blocked


@router.post("/cards/{card_id}/blockers/{blocker_id}")
async def add_blocker(card_id: str, blocker_id: str):
    """Add a blocker to a card. The blocker card must be completed before this card can proceed."""
    db.initialize()

    # Verify both cards exist
    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    blocker = db.cards.get(Q.id == blocker_id)
    if not blocker:
        raise HTTPException(status_code=404, detail="Blocker card not found")

    # Prevent self-blocking
    if card_id == blocker_id:
        raise HTTPException(status_code=400, detail="A card cannot block itself")

    # Check for circular dependency
    blocker_blockers = blocker.get("blocked_by", [])
    if card_id in blocker_blockers:
        raise HTTPException(status_code=400, detail="Circular dependency detected")

    # Check deep circular dependencies
    visited = set()
    to_check = [blocker_id]
    while to_check:
        current_id = to_check.pop()
        if current_id in visited:
            continue
        visited.add(current_id)

        current = db.cards.get(Q.id == current_id)
        if current:
            current_blockers = current.get("blocked_by", [])
            if card_id in current_blockers:
                raise HTTPException(status_code=400, detail="Circular dependency detected")
            to_check.extend(current_blockers)

    # Add blocker
    blocked_by = card.get("blocked_by", [])
    if blocker_id not in blocked_by:
        blocked_by.append(blocker_id)
        db.cards.update({"blocked_by": blocked_by}, Q.id == card_id)

    # Update the blocker's "blocks" list
    blocker_blocks = blocker.get("blocks", [])
    if card_id not in blocker_blocks:
        blocker_blocks.append(card_id)
        db.cards.update({"blocks": blocker_blocks}, Q.id == blocker_id)

    # Log activity
    db.log_activity(card_id, card.get("board_id", ""), "dependency_added", details={
        "blocker_id": blocker_id,
        "blocker_title": blocker.get("title")
    })

    return {
        "message": "Blocker added",
        "card_id": card_id,
        "blocker_id": blocker_id,
        "blocked_by": blocked_by
    }


@router.delete("/cards/{card_id}/blockers/{blocker_id}")
async def remove_blocker(card_id: str, blocker_id: str):
    """Remove a blocker from a card."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    blocker = db.cards.get(Q.id == blocker_id)

    # Remove from blocked_by
    blocked_by = card.get("blocked_by", [])
    if blocker_id in blocked_by:
        blocked_by.remove(blocker_id)
        db.cards.update({"blocked_by": blocked_by}, Q.id == card_id)

    # Remove from blocker's blocks list
    if blocker:
        blocker_blocks = blocker.get("blocks", [])
        if card_id in blocker_blocks:
            blocker_blocks.remove(card_id)
            db.cards.update({"blocks": blocker_blocks}, Q.id == blocker_id)

    # Log activity
    db.log_activity(card_id, card.get("board_id", ""), "dependency_removed", details={
        "blocker_id": blocker_id,
        "blocker_title": blocker.get("title") if blocker else None
    })

    return {
        "message": "Blocker removed",
        "card_id": card_id,
        "blocker_id": blocker_id,
        "blocked_by": blocked_by
    }


@router.get("/cards/{card_id}/dependencies")
async def get_card_dependencies(card_id: str):
    """Get all dependencies for a card (both blockers and cards it blocks)."""
    db.initialize()

    card = db.cards.get(Q.id == card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    blocked_by_ids = card.get("blocked_by", [])
    blocks_ids = card.get("blocks", [])

    # Get full card info for blockers
    blockers = []
    for bid in blocked_by_ids:
        blocker = db.cards.get(Q.id == bid)
        if blocker:
            column = db.columns.get(Q.id == blocker.get("column_id"))
            blockers.append({
                "id": blocker["id"],
                "title": blocker["title"],
                "column_name": column.get("name") if column else None,
                "archived": blocker.get("archived", False),
                "completed": blocker.get("completed", False)
            })

    # Get full card info for cards this blocks
    blocking = []
    for bid in blocks_ids:
        blocked = db.cards.get(Q.id == bid)
        if blocked:
            column = db.columns.get(Q.id == blocked.get("column_id"))
            blocking.append({
                "id": blocked["id"],
                "title": blocked["title"],
                "column_name": column.get("name") if column else None,
                "archived": blocked.get("archived", False)
            })

    # Calculate if card is blocked (any unresolved blockers)
    is_blocked = any(not b.get("completed") and not b.get("archived") for b in blockers)

    return {
        "card_id": card_id,
        "card_title": card.get("title"),
        "is_blocked": is_blocked,
        "blocked_by": blockers,
        "blocks": blocking,
        "blocked_by_count": len(blockers),
        "blocks_count": len(blocking)
    }


@router.get("/boards/{board_id}/dependency-graph")
async def get_board_dependency_graph(board_id: str):
    """Get the complete dependency graph for a board. Useful for visualization."""
    db.initialize()

    board = db.boards.get(Q.id == board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    columns = db.columns.search(Q.board_id == board_id)
    column_map = {c["id"]: c["name"] for c in columns}

    nodes = []
    edges = []

    for column in columns:
        cards = db.cards.search(Q.column_id == column["id"])

        for card in cards:
            if card.get("archived"):
                continue

            nodes.append({
                "id": card["id"],
                "title": card["title"],
                "column_name": column_map.get(card.get("column_id")),
                "has_dependencies": bool(card.get("blocked_by")),
                "is_blocking": bool(card.get("blocks")),
                "blocked_count": len(card.get("blocked_by", [])),
                "blocking_count": len(card.get("blocks", []))
            })

            # Add edges for blocked_by relationships
            for blocker_id in card.get("blocked_by", []):
                edges.append({
                    "from": blocker_id,
                    "to": card["id"]
                })

    return {
        "board_id": board_id,
        "board_name": board.get("name"),
        "nodes": nodes,
        "edges": edges,
        "total_dependencies": len(edges)
    }
