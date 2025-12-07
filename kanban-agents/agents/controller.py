"""
Multi-Agent Controller

Orchestrates multiple agent personalities based on ticket status.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

from .kanban_client import KanbanClient, AsyncKanbanClient
from .personalities import get_personality, get_agent_for_column, AGENT_PERSONALITIES

logger = logging.getLogger(__name__)


class MultiAgentController:
    """
    Controller that processes Kanban cards with different agent personalities
    based on their current status (column).
    """

    def __init__(
        self,
        kanban_url: str,
        repo_path: str,
        anthropic_api_key: str,
        agent_label: str = "agent",
        poll_interval: int = 30
    ):
        """
        Initialize the multi-agent controller.

        Args:
            kanban_url: Base URL of the Kanban API
            repo_path: Path to the code repository
            anthropic_api_key: Anthropic API key for Claude
            agent_label: Label that marks cards for agent processing
            poll_interval: Seconds between polling cycles
        """
        self.kanban_url = kanban_url
        self.repo_path = Path(repo_path)
        self.anthropic_api_key = anthropic_api_key
        self.agent_label = agent_label
        self.poll_interval = poll_interval
        self.column_to_agent = {}
        self.processed_cards = {}  # card_id -> last_processed timestamp
        self.cooldown_minutes = 5  # Don't reprocess cards within this time

    def setup_column_mapping(self, board: dict) -> dict:
        """Map columns to agent personalities based on column names."""
        for column in board.get("columns", []):
            agent_type = get_agent_for_column(column["name"])
            if agent_type:
                self.column_to_agent[column["id"]] = {
                    "agent_type": agent_type,
                    "column_name": column["name"]
                }
                logger.info(f"Mapped column '{column['name']}' to {agent_type} agent")
        return self.column_to_agent

    def should_process_card(self, card: dict) -> bool:
        """Check if a card should be processed."""
        # Must have the agent label
        if self.agent_label not in card.get("labels", []):
            return False

        # Check cooldown
        card_id = card["id"]
        if card_id in self.processed_cards:
            last_processed = self.processed_cards[card_id]
            if datetime.now() - last_processed < timedelta(minutes=self.cooldown_minutes):
                return False

        return True

    def mark_processed(self, card_id: str):
        """Mark a card as recently processed."""
        self.processed_cards[card_id] = datetime.now()

    async def process_card(
        self,
        card: dict,
        agent_type: str,
        kanban: AsyncKanbanClient
    ) -> dict:
        """
        Process a single card with the appropriate agent personality.

        Args:
            card: The card to process
            agent_type: The type of agent to use
            kanban: Async Kanban client

        Returns:
            Result dictionary with status and output
        """
        personality = get_personality(agent_type)

        logger.info(f"Processing card '{card['title']}' with {personality['name']}")

        # Get additional context
        comments = await kanban.get_comments(card["id"])
        recent_comments = comments[-5:] if len(comments) > 5 else comments

        # Build the prompt
        prompt = self._build_prompt(card, personality, recent_comments)

        # Post starting comment
        await kanban.add_comment(
            card["id"],
            f"{personality['emoji']} **{personality['name']}** is analyzing this ticket...",
            author_name=personality["name"]
        )

        try:
            # Process with Claude
            result = await self._run_claude(prompt, personality)

            # Post result comment
            await kanban.add_comment(
                card["id"],
                f"{personality['emoji']} **{personality['name']}** completed:\n\n{result[:2000]}",
                author_name=personality["name"]
            )

            self.mark_processed(card["id"])

            return {
                "status": "success",
                "agent": agent_type,
                "card_id": card["id"],
                "output": result
            }

        except Exception as e:
            logger.error(f"Error processing card {card['id']}: {e}")

            await kanban.add_comment(
                card["id"],
                f"{personality['emoji']} **{personality['name']}** encountered an error:\n\n{str(e)}",
                author_name=personality["name"]
            )

            return {
                "status": "error",
                "agent": agent_type,
                "card_id": card["id"],
                "error": str(e)
            }

    def _build_prompt(self, card: dict, personality: dict, recent_comments: list) -> str:
        """Build the prompt for the agent."""
        checklist_str = self._format_checklist(card.get("checklist", []))
        comments_str = self._format_comments(recent_comments)

        return f"""
{personality['system_prompt']}

---

## Current Ticket

**Title:** {card['title']}

**Description:**
{card.get('description', 'No description provided')}

**Labels:** {', '.join(card.get('labels', [])) or 'None'}
**Priority:** {card.get('priority', 'Not set')}
**Assignee:** {card.get('assignee_id', 'Unassigned')}
**Due Date:** {card.get('due_date', 'Not set')}

**Checklist:**
{checklist_str}

**Recent Comments:**
{comments_str}

---

## Repository

Working directory: {self.repo_path}

Please perform your role and provide a detailed report of your analysis/actions.
"""

    def _format_checklist(self, checklist: list) -> str:
        """Format checklist items as markdown."""
        if not checklist:
            return "No checklist items"
        return "\n".join(
            f"- [{'x' if item.get('completed') else ' '}] {item['text']}"
            for item in checklist
        )

    def _format_comments(self, comments: list) -> str:
        """Format comments for context."""
        if not comments:
            return "No comments yet"
        return "\n\n".join(
            f"**{c.get('author_name', 'Unknown')}** ({c.get('created_at', '')[:10]}):\n{c['text'][:300]}"
            for c in comments
        )

    async def _run_claude(self, prompt: str, personality: dict) -> str:
        """
        Run Claude with the given prompt.

        This is a placeholder - implement with your preferred Claude integration:
        - anthropic Python SDK
        - Claude Code SDK
        - Custom API wrapper
        """
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self.anthropic_api_key)

            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=4096,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            return response.content[0].text

        except ImportError:
            # Fallback if anthropic not installed
            logger.warning("anthropic package not installed, using mock response")
            return f"[Mock Response from {personality['name']}]\n\nAnalysis would go here..."

    async def run_once(self, board_id: str) -> list:
        """
        Run a single processing cycle for all eligible cards.

        Args:
            board_id: The board ID to process

        Returns:
            List of results from processed cards
        """
        results = []

        async with AsyncKanbanClient(self.kanban_url) as kanban:
            # Get board state
            board = await kanban.get_board(board_id)

            # Setup column mapping if not done
            if not self.column_to_agent:
                self.setup_column_mapping(board)

            # Process each column
            for column in board.get("columns", []):
                mapping = self.column_to_agent.get(column["id"])

                if not mapping:
                    continue  # No agent for this column

                agent_type = mapping["agent_type"]

                # Process eligible cards
                for card in column.get("cards", []):
                    if not self.should_process_card(card):
                        continue

                    result = await self.process_card(card, agent_type, kanban)
                    results.append(result)

        return results

    async def run_loop(self, board_id: str):
        """
        Run the continuous processing loop.

        Args:
            board_id: The board ID to process
        """
        logger.info(f"Starting agent loop for board {board_id}")
        logger.info(f"Poll interval: {self.poll_interval}s, Agent label: {self.agent_label}")

        while True:
            try:
                results = await self.run_once(board_id)

                if results:
                    logger.info(f"Processed {len(results)} cards")
                    for r in results:
                        status = "✓" if r["status"] == "success" else "✗"
                        logger.info(f"  {status} Card {r['card_id']} with {r['agent']}")

            except Exception as e:
                logger.error(f"Error in processing loop: {e}")

            await asyncio.sleep(self.poll_interval)


async def main():
    """Example usage of the multi-agent controller."""
    import os

    controller = MultiAgentController(
        kanban_url=os.getenv("KANBAN_URL", "http://localhost:8000"),
        repo_path=os.getenv("REPO_PATH", "/path/to/repo"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        agent_label="agent",
        poll_interval=30
    )

    board_id = os.getenv("BOARD_ID", "your-board-id")

    await controller.run_loop(board_id)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    asyncio.run(main())
