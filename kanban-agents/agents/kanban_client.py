"""
Kanban API Client

A Python client for interacting with the Kanban board REST API.
"""

import httpx
from typing import Optional
from dataclasses import dataclass


@dataclass
class KanbanConfig:
    """Configuration for Kanban API connection."""
    base_url: str
    timeout: int = 30


class KanbanClient:
    """Client for interacting with the Kanban REST API."""

    def __init__(self, base_url: str, timeout: int = 30):
        """
        Initialize the Kanban client.

        Args:
            base_url: The base URL of the Kanban API (e.g., "https://team.example.com/api")
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.client = httpx.Client(timeout=timeout)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()

    # ==================== Boards ====================

    def get_boards(self) -> list:
        """Get all boards."""
        response = self.client.get(f"{self.base_url}/boards")
        response.raise_for_status()
        return response.json()

    def get_board(self, board_id: str) -> dict:
        """Get a board with all its columns and cards."""
        response = self.client.get(f"{self.base_url}/boards/{board_id}")
        response.raise_for_status()
        return response.json()

    def create_board(self, name: str, description: str = None) -> dict:
        """Create a new board."""
        payload = {"name": name}
        if description:
            payload["description"] = description
        response = self.client.post(f"{self.base_url}/boards", json=payload)
        response.raise_for_status()
        return response.json()

    # ==================== Columns ====================

    def create_column(self, board_id: str, name: str, position: int = 0, wip_limit: int = None) -> dict:
        """Create a new column in a board."""
        payload = {
            "board_id": board_id,
            "name": name,
            "position": position
        }
        if wip_limit:
            payload["wip_limit"] = wip_limit
        response = self.client.post(f"{self.base_url}/columns", json=payload)
        response.raise_for_status()
        return response.json()

    def update_column(self, column_id: str, **updates) -> dict:
        """Update a column."""
        response = self.client.patch(f"{self.base_url}/columns/{column_id}", json=updates)
        response.raise_for_status()
        return response.json()

    # ==================== Cards ====================

    def get_cards(self, column_id: str = None) -> list:
        """Get cards, optionally filtered by column."""
        params = {}
        if column_id:
            params["column_id"] = column_id
        response = self.client.get(f"{self.base_url}/cards", params=params)
        response.raise_for_status()
        return response.json()

    def get_card(self, card_id: str) -> dict:
        """Get a single card by ID."""
        response = self.client.get(f"{self.base_url}/cards/{card_id}")
        response.raise_for_status()
        return response.json()

    def create_card(
        self,
        column_id: str,
        title: str,
        description: str = None,
        labels: list = None,
        priority: str = None,
        assignee_id: str = None,
        due_date: str = None,
        checklist: list = None
    ) -> dict:
        """Create a new card."""
        payload = {
            "column_id": column_id,
            "title": title
        }
        if description:
            payload["description"] = description
        if labels:
            payload["labels"] = labels
        if priority:
            payload["priority"] = priority
        if assignee_id:
            payload["assignee_id"] = assignee_id
        if due_date:
            payload["due_date"] = due_date
        if checklist:
            payload["checklist"] = checklist

        response = self.client.post(f"{self.base_url}/cards", json=payload)
        response.raise_for_status()
        return response.json()

    def update_card(self, card_id: str, **updates) -> dict:
        """Update a card's properties."""
        response = self.client.patch(f"{self.base_url}/cards/{card_id}", json=updates)
        response.raise_for_status()
        return response.json()

    def move_card(self, card_id: str, column_id: str, position: int = 0) -> dict:
        """Move a card to a different column."""
        response = self.client.post(
            f"{self.base_url}/cards/{card_id}/move",
            json={"column_id": column_id, "position": position}
        )
        response.raise_for_status()
        return response.json()

    def archive_card(self, card_id: str) -> dict:
        """Archive a card."""
        response = self.client.post(f"{self.base_url}/cards/{card_id}/archive")
        response.raise_for_status()
        return response.json()

    def delete_card(self, card_id: str) -> dict:
        """Permanently delete a card."""
        response = self.client.delete(f"{self.base_url}/cards/{card_id}")
        response.raise_for_status()
        return response.json()

    # ==================== Comments ====================

    def get_comments(self, card_id: str) -> list:
        """Get all comments for a card."""
        response = self.client.get(f"{self.base_url}/cards/{card_id}/comments")
        response.raise_for_status()
        return response.json()

    def add_comment(self, card_id: str, text: str, author_name: str = "AI Agent", author_id: str = None) -> dict:
        """Add a comment to a card."""
        payload = {
            "text": text,
            "author_name": author_name
        }
        if author_id:
            payload["author_id"] = author_id
        response = self.client.post(f"{self.base_url}/cards/{card_id}/comments", json=payload)
        response.raise_for_status()
        return response.json()

    def update_comment(self, card_id: str, comment_id: str, text: str) -> dict:
        """Update a comment."""
        response = self.client.patch(
            f"{self.base_url}/cards/{card_id}/comments/{comment_id}",
            json={"text": text}
        )
        response.raise_for_status()
        return response.json()

    # ==================== Checklists ====================

    def add_checklist_item(self, card_id: str, text: str, completed: bool = False) -> dict:
        """Add a checklist item to a card."""
        response = self.client.post(
            f"{self.base_url}/cards/{card_id}/checklist",
            json={"text": text, "completed": completed}
        )
        response.raise_for_status()
        return response.json()

    def toggle_checklist_item(self, card_id: str, item_id: str) -> dict:
        """Toggle a checklist item's completion status."""
        response = self.client.post(
            f"{self.base_url}/cards/{card_id}/checklist/{item_id}/toggle"
        )
        response.raise_for_status()
        return response.json()

    def update_checklist_item(self, card_id: str, item_id: str, **updates) -> dict:
        """Update a checklist item."""
        response = self.client.patch(
            f"{self.base_url}/cards/{card_id}/checklist/{item_id}",
            json=updates
        )
        response.raise_for_status()
        return response.json()

    # ==================== Labels ====================

    def get_labels(self, board_id: str) -> list:
        """Get all labels for a board."""
        response = self.client.get(f"{self.base_url}/labels/boards/{board_id}/labels")
        response.raise_for_status()
        return response.json()

    def create_label(self, board_id: str, name: str, color: str) -> dict:
        """Create a new label."""
        response = self.client.post(
            f"{self.base_url}/labels/boards/{board_id}/labels",
            json={"name": name, "color": color}
        )
        response.raise_for_status()
        return response.json()

    # ==================== Webhooks ====================

    def get_webhooks(self) -> list:
        """Get all webhooks."""
        response = self.client.get(f"{self.base_url}/webhooks")
        response.raise_for_status()
        return response.json()

    def create_webhook(
        self,
        name: str,
        url: str,
        events: list = None,
        secret: str = None,
        active: bool = True
    ) -> dict:
        """Create a new webhook."""
        payload = {
            "name": name,
            "url": url,
            "active": active
        }
        if events:
            payload["events"] = events
        if secret:
            payload["secret"] = secret
        response = self.client.post(f"{self.base_url}/webhooks", json=payload)
        response.raise_for_status()
        return response.json()

    def delete_webhook(self, webhook_id: str) -> dict:
        """Delete a webhook."""
        response = self.client.delete(f"{self.base_url}/webhooks/{webhook_id}")
        response.raise_for_status()
        return response.json()

    def test_webhook(self, webhook_id: str) -> dict:
        """Send a test event to a webhook."""
        response = self.client.post(f"{self.base_url}/webhooks/{webhook_id}/test")
        response.raise_for_status()
        return response.json()

    # ==================== Search ====================

    def search_cards(
        self,
        query: str = None,
        board_id: str = None,
        labels: list = None,
        assignee_id: str = None,
        is_overdue: bool = None,
        limit: int = 50
    ) -> list:
        """Search for cards with various filters."""
        params = {"limit": limit}
        if query:
            params["q"] = query
        if board_id:
            params["board_id"] = board_id
        if labels:
            params["labels"] = ",".join(labels)
        if assignee_id:
            params["assignee_id"] = assignee_id
        if is_overdue is not None:
            params["is_overdue"] = str(is_overdue).lower()

        response = self.client.get(f"{self.base_url}/search", params=params)
        response.raise_for_status()
        return response.json()

    # ==================== Activity ====================

    def get_board_activity(self, board_id: str, limit: int = 50) -> list:
        """Get activity log for a board."""
        response = self.client.get(
            f"{self.base_url}/boards/{board_id}/activity",
            params={"limit": limit}
        )
        response.raise_for_status()
        return response.json()

    def get_card_activity(self, card_id: str) -> list:
        """Get activity log for a card."""
        response = self.client.get(f"{self.base_url}/cards/{card_id}/activity")
        response.raise_for_status()
        return response.json()

    # ==================== Members ====================

    def get_members(self) -> list:
        """Get all team members."""
        response = self.client.get(f"{self.base_url}/members")
        response.raise_for_status()
        return response.json()

    def get_member(self, member_id: str) -> dict:
        """Get a specific member."""
        response = self.client.get(f"{self.base_url}/members/{member_id}")
        response.raise_for_status()
        return response.json()


class AsyncKanbanClient:
    """Async client for interacting with the Kanban REST API."""

    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.client = httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def get_board(self, board_id: str) -> dict:
        response = await self.client.get(f"{self.base_url}/boards/{board_id}")
        response.raise_for_status()
        return response.json()

    async def get_cards(self, column_id: str = None) -> list:
        params = {}
        if column_id:
            params["column_id"] = column_id
        response = await self.client.get(f"{self.base_url}/cards", params=params)
        response.raise_for_status()
        return response.json()

    async def get_card(self, card_id: str) -> dict:
        response = await self.client.get(f"{self.base_url}/cards/{card_id}")
        response.raise_for_status()
        return response.json()

    async def move_card(self, card_id: str, column_id: str, position: int = 0) -> dict:
        response = await self.client.post(
            f"{self.base_url}/cards/{card_id}/move",
            json={"column_id": column_id, "position": position}
        )
        response.raise_for_status()
        return response.json()

    async def add_comment(self, card_id: str, text: str, author_name: str = "AI Agent") -> dict:
        response = await self.client.post(
            f"{self.base_url}/cards/{card_id}/comments",
            json={"text": text, "author_name": author_name}
        )
        response.raise_for_status()
        return response.json()

    async def update_card(self, card_id: str, **updates) -> dict:
        response = await self.client.patch(
            f"{self.base_url}/cards/{card_id}",
            json=updates
        )
        response.raise_for_status()
        return response.json()

    async def get_comments(self, card_id: str) -> list:
        response = await self.client.get(f"{self.base_url}/cards/{card_id}/comments")
        response.raise_for_status()
        return response.json()
