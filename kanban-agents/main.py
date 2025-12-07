#!/usr/bin/env python3
"""
Kanban Agents - Main Entry Point

Multi-personality AI agents that interact with Kanban boards
based on ticket status.

Usage:
    # Run polling mode
    python main.py poll --board-id <id>

    # Run webhook server
    python main.py server --port 8080

    # Process single card
    python main.py process --card-id <id> --agent <type>
"""

import os
import sys
import asyncio
import logging
import argparse

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("kanban-agents")


def get_config():
    """Get configuration from environment."""
    return {
        "kanban_url": os.getenv("KANBAN_URL", "http://localhost:8000"),
        "repo_path": os.getenv("REPO_PATH", os.getcwd()),
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "agent_label": os.getenv("AGENT_LABEL", "agent"),
        "board_id": os.getenv("BOARD_ID", ""),
        "webhook_secret": os.getenv("WEBHOOK_SECRET", ""),
        "poll_interval": int(os.getenv("POLL_INTERVAL", "30")),
    }


async def run_poll_mode(args):
    """Run in polling mode - continuously check for cards to process."""
    from agents.controller import MultiAgentController

    config = get_config()

    if not args.board_id and not config["board_id"]:
        logger.error("Board ID required. Use --board-id or set BOARD_ID env var")
        sys.exit(1)

    board_id = args.board_id or config["board_id"]

    controller = MultiAgentController(
        kanban_url=config["kanban_url"],
        repo_path=args.repo_path or config["repo_path"],
        anthropic_api_key=config["anthropic_api_key"],
        agent_label=config["agent_label"],
        poll_interval=config["poll_interval"]
    )

    logger.info(f"Starting polling mode for board {board_id}")
    logger.info(f"Kanban URL: {config['kanban_url']}")
    logger.info(f"Repo path: {args.repo_path or config['repo_path']}")
    logger.info(f"Agent label: {config['agent_label']}")

    await controller.run_loop(board_id)


def run_server_mode(args):
    """Run webhook server mode."""
    import uvicorn
    from agents.webhook_server import create_app

    config = get_config()

    app = create_app(
        webhook_secret=config["webhook_secret"],
        kanban_url=config["kanban_url"],
        repo_path=args.repo_path or config["repo_path"],
        anthropic_api_key=config["anthropic_api_key"],
        agent_label=config["agent_label"]
    )

    logger.info(f"Starting webhook server on port {args.port}")
    logger.info(f"Kanban URL: {config['kanban_url']}")

    uvicorn.run(app, host=args.host, port=args.port)


async def run_process_mode(args):
    """Process a single card with specified agent."""
    from agents.kanban_client import AsyncKanbanClient
    from agents.controller import MultiAgentController

    config = get_config()

    if not args.card_id:
        logger.error("Card ID required. Use --card-id")
        sys.exit(1)

    controller = MultiAgentController(
        kanban_url=config["kanban_url"],
        repo_path=args.repo_path or config["repo_path"],
        anthropic_api_key=config["anthropic_api_key"],
        agent_label=config["agent_label"]
    )

    async with AsyncKanbanClient(config["kanban_url"]) as kanban:
        card = await kanban.get_card(args.card_id)

        if not card:
            logger.error(f"Card {args.card_id} not found")
            sys.exit(1)

        agent_type = args.agent or "coder"
        logger.info(f"Processing card '{card['title']}' with {agent_type} agent")

        result = await controller.process_card(card, agent_type, kanban)

        if result["status"] == "success":
            logger.info("Processing complete!")
            print("\n" + "=" * 50)
            print(result["output"])
        else:
            logger.error(f"Processing failed: {result.get('error')}")
            sys.exit(1)


def run_list_agents(args):
    """List available agent personalities."""
    from agents.personalities import list_personalities

    print("\nAvailable Agent Personalities:")
    print("=" * 50)

    for agent in list_personalities():
        print(f"\n{agent['emoji']} {agent['name']} ({agent['type']})")
        print(f"   {agent['description']}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Kanban Agents - AI agents that work on tickets"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Poll command
    poll_parser = subparsers.add_parser("poll", help="Run in polling mode")
    poll_parser.add_argument("--board-id", "-b", help="Board ID to monitor")
    poll_parser.add_argument("--repo-path", "-r", help="Repository path")

    # Server command
    server_parser = subparsers.add_parser("server", help="Run webhook server")
    server_parser.add_argument("--port", "-p", type=int, default=8080)
    server_parser.add_argument("--host", "-H", default="0.0.0.0")
    server_parser.add_argument("--repo-path", "-r", help="Repository path")

    # Process command
    process_parser = subparsers.add_parser("process", help="Process single card")
    process_parser.add_argument("--card-id", "-c", required=True, help="Card ID")
    process_parser.add_argument("--agent", "-a", help="Agent type to use")
    process_parser.add_argument("--repo-path", "-r", help="Repository path")

    # List command
    list_parser = subparsers.add_parser("list", help="List available agents")

    args = parser.parse_args()

    if args.command == "poll":
        asyncio.run(run_poll_mode(args))
    elif args.command == "server":
        run_server_mode(args)
    elif args.command == "process":
        asyncio.run(run_process_mode(args))
    elif args.command == "list":
        run_list_agents(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
