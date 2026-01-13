"""Orchestrator main entry point - listens for provisioning tasks"""

import asyncio
import base64
import json
import logging
import os
import secrets
import shutil
import signal
import subprocess
import shlex
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import redis.asyncio as redis
from jinja2 import Environment, FileSystemLoader
import anthropic
import httpx

from app.services.database_cloner import database_cloner
from app.services.github_service import github_service
from app.services.certificate_service import certificate_service
from app.services.azure_service import azure_service
from app.services.keyvault_service import keyvault_service
from app.services.claude_code_runner import claude_runner
from app.services.codex_cli_runner import codex_runner
# QA test runner no longer used - QA agent creates and runs its own tests
# from app.services.qa_test_runner import qa_runner, QATestConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DOMAIN = os.getenv("DOMAIN", "localhost")
PORT = os.getenv("PORT", "4443")
CERT_MODE = os.getenv("CERT_MODE", "development")
HOST_IP = os.getenv("HOST_IP", "127.0.1")
HOST_PROJECT_PATH = os.getenv("HOST_PROJECT_PATH", "/Volumes/dados/projects/kanban")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
ENTRA_CIAM_AUTHORITY = os.getenv("ENTRA_CIAM_AUTHORITY", "")

# Try to load CROSS_DOMAIN_SECRET from Key Vault first, fall back to env var
CROSS_DOMAIN_SECRET = os.getenv("CROSS_DOMAIN_SECRET", "")
try:
    _kv_cross_domain_secret = keyvault_service.get_secret("cross-domain-secret")
    if _kv_cross_domain_secret:
        CROSS_DOMAIN_SECRET = _kv_cross_domain_secret
        logger.info("Loaded CROSS_DOMAIN_SECRET from Key Vault")
except Exception as e:
    logger.warning(f"Could not load CROSS_DOMAIN_SECRET from Key Vault: {e}")

# Try to load ANTHROPIC_API_KEY from Key Vault first, fall back to env var
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
try:
    _kv_anthropic_key = keyvault_service.get_secret("anthropic-api-key")
    if _kv_anthropic_key:
        ANTHROPIC_API_KEY = _kv_anthropic_key
        logger.info("Loaded ANTHROPIC_API_KEY from Key Vault")
except Exception as e:
    logger.warning(f"Could not load ANTHROPIC_API_KEY from Key Vault: {e}")

# Try to load OPENAI_API_KEY from Key Vault first, fall back to env var
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
try:
    _kv_openai_key = keyvault_service.get_secret("openai-api-key")
    if _kv_openai_key:
        OPENAI_API_KEY = _kv_openai_key
        logger.info("Loaded OPENAI_API_KEY from Key Vault")
except Exception as e:
    logger.warning(f"Could not load OPENAI_API_KEY from Key Vault: {e}")

TEAMS_DIR = Path("/app/data/teams")
# Use HOST_PROJECT_PATH for workspaces so docker compose build contexts resolve correctly
WORKSPACES_DIR = Path(f"{HOST_PROJECT_PATH}/data/workspaces")
TEMPLATE_DIR = Path("/app/kanban-team")
APP_FACTORY_TEMPLATE_DIR = Path(__file__).parent / "templates"
TRAEFIK_DIR = Path("/app/traefik-dynamic")
DNS_DIR = Path("/app/dns-zones")
NETWORK_NAME = "kanban-global"

# Auto-scaling configuration
ENABLE_IDLE_CHECK = os.getenv("ENABLE_IDLE_CHECK", "false").lower() == "true"
IDLE_CHECK_INTERVAL = int(os.getenv("IDLE_CHECK_INTERVAL", "900"))  # 15 minutes
IDLE_THRESHOLD = int(os.getenv("IDLE_THRESHOLD", "900"))  # 15 minutes


def run_docker_cmd(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a docker command and return the result"""
    cmd = ["docker"] + args
    logger.debug(f"Running: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def docker_available() -> bool:
    """Check if docker CLI is available"""
    try:
        result = run_docker_cmd(["version", "--format", "{{.Server.Version}}"], check=False)
        return result.returncode == 0
    except Exception:
        return False


class Orchestrator:
    """Team provisioning orchestrator"""

    QUEUES = [
        "queue:provisioning:high",
        "queue:provisioning:normal",
        "queue:agents:high",
        "queue:agents:normal",
    ]

    # Maximum number of concurrent agent tasks
    MAX_AGENT_WORKERS = int(os.getenv("MAX_AGENT_WORKERS", "5"))

    def __init__(self):
        self.running = False
        self.redis: redis.Redis = None
        self.docker_available = False
        self.jinja = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
        self.app_factory_jinja = Environment(loader=FileSystemLoader(str(APP_FACTORY_TEMPLATE_DIR)))

        # Track active agent tasks for graceful shutdown and restart recovery
        self.active_agent_tasks: dict[str, asyncio.Task] = {}  # task_id -> asyncio.Task
        self.agent_semaphore = asyncio.Semaphore(self.MAX_AGENT_WORKERS)

        # Check if Docker CLI is available
        if docker_available():
            self.docker_available = True
            logger.info("Docker CLI available")
        else:
            logger.warning("Docker CLI not available. Container operations disabled.")

        # Ensure workspaces directory exists
        WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)

    async def start(self):
        """Start the orchestrator"""
        logger.info("Starting Kanban Orchestrator...")
        self.running = True

        # Connect to Redis
        self.redis = redis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True
        )

        # Set up signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_event_loop().add_signal_handler(
                sig, lambda: asyncio.create_task(self.stop())
            )

        # NOTE: Auto-start of workspaces on boot has been disabled.
        # Workspaces are now started on-demand when users access them via the portal.
        # The start_active_workspaces() method is kept for reference but not called.
        # await self.start_active_workspaces()

        # Start idle team checker background task (if enabled)
        if ENABLE_IDLE_CHECK:
            asyncio.create_task(self.check_idle_teams())
            logger.info(f"Idle team checker started (interval: {IDLE_CHECK_INTERVAL}s, threshold: {IDLE_THRESHOLD}s)")
        else:
            logger.info("Idle team checker disabled (ENABLE_IDLE_CHECK=false)")

        # Start health check processor background task
        asyncio.create_task(self.process_health_checks())
        logger.info("Health check processor started")

        # Recover any orphaned agent tasks from previous run
        await self.recover_orphaned_agent_tasks()

        logger.info(f"Orchestrator listening on queues: {self.QUEUES}")
        logger.info(f"Max concurrent agent workers: {self.MAX_AGENT_WORKERS}")

        while self.running:
            try:
                result = await self.redis.brpop(self.QUEUES, timeout=5)

                if result:
                    queue_name, task_id = result
                    logger.info(f"Processing task {task_id} from {queue_name}")

                    # Check if this is an agent task (should run in parallel)
                    if "agents" in queue_name:
                        # Spawn agent task in background with semaphore limit
                        asyncio.create_task(self._run_agent_task_with_semaphore(task_id))
                    else:
                        # Provisioning tasks run sequentially (they're quick)
                        await self.process_task(task_id)

                # Clean up completed agent tasks
                self._cleanup_completed_agent_tasks()

            except Exception as e:
                logger.error(f"Orchestrator error: {e}", exc_info=True)
                await asyncio.sleep(1)

        # Wait for active agent tasks to complete on shutdown
        if self.active_agent_tasks:
            logger.info(f"Waiting for {len(self.active_agent_tasks)} active agent tasks to complete...")
            await asyncio.gather(*self.active_agent_tasks.values(), return_exceptions=True)

        logger.info("Orchestrator stopped")

    async def stop(self):
        """Stop the orchestrator"""
        logger.info("Stopping orchestrator...")
        self.running = False

    async def _run_agent_task_with_semaphore(self, task_id: str):
        """Run an agent task with semaphore-limited concurrency."""
        async with self.agent_semaphore:
            # Track the task
            current_task = asyncio.current_task()
            self.active_agent_tasks[task_id] = current_task
            logger.info(f"Starting agent task {task_id} (active: {len(self.active_agent_tasks)}/{self.MAX_AGENT_WORKERS})")

            try:
                await self.process_task(task_id)
            except Exception as e:
                logger.error(f"Agent task {task_id} failed: {e}")
            finally:
                # Remove from active tasks
                self.active_agent_tasks.pop(task_id, None)
                logger.info(f"Agent task {task_id} finished (active: {len(self.active_agent_tasks)}/{self.MAX_AGENT_WORKERS})")

    def _cleanup_completed_agent_tasks(self):
        """Remove completed tasks from the active tasks dict."""
        completed = [
            task_id for task_id, task in self.active_agent_tasks.items()
            if task.done()
        ]
        for task_id in completed:
            self.active_agent_tasks.pop(task_id, None)

    async def start_active_workspaces(self):
        """Start containers for all active workspaces from database on orchestrator startup"""
        logger.info("Starting active workspaces...")

        # Read portal database to get active workspaces
        portal_db_path = Path("/app/data/portal/portal.json")
        if not portal_db_path.exists():
            logger.warning("Portal database not found, skipping workspace startup")
            return

        try:
            with open(portal_db_path, 'r') as f:
                portal_data = json.load(f)

            workspaces = portal_data.get("workspaces", {})
            if not workspaces:
                logger.info("No workspaces found in database")
                return

            started = 0
            skipped = 0

            for ws_key, ws in workspaces.items():
                workspace_slug = ws.get("slug")
                status = ws.get("status", "active")

                if not workspace_slug:
                    continue

                # Only start active workspaces
                if status != "active":
                    logger.debug(f"[{workspace_slug}] Skipping - status: {status}")
                    skipped += 1
                    continue

                # Check if workspace data directory exists
                workspace_dir = Path(f"/app/data/workspaces/{workspace_slug}")
                if not workspace_dir.exists():
                    logger.warning(f"[{workspace_slug}] Data directory not found, skipping")
                    skipped += 1
                    continue

                # Check if containers are already running
                project_name = f"{workspace_slug}-kanban"
                result = subprocess.run(
                    ["docker", "ps", "--filter", f"name={project_name}", "--format", "{{.Names}}"],
                    capture_output=True,
                    text=True,
                    check=False
                )

                if result.stdout.strip():
                    logger.debug(f"[{workspace_slug}] Containers already running")
                    skipped += 1
                    continue

                # Start workspace containers
                try:
                    await self._start_workspace_kanban(workspace_slug, ws.get("id", workspace_slug))
                    started += 1
                    logger.info(f"[{workspace_slug}] Started workspace containers")

                    # Also start app containers if compose file exists
                    app_compose = Path(f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/docker-compose.app.yml")
                    if app_compose.exists():
                        await self._start_workspace_app(workspace_slug)
                        logger.info(f"[{workspace_slug}] Started app containers")

                except Exception as e:
                    logger.error(f"[{workspace_slug}] Failed to start: {e}")

            logger.info(f"Workspace startup complete: {started} started, {skipped} skipped")

        except Exception as e:
            logger.error(f"Failed to start active workspaces: {e}", exc_info=True)

    async def _start_workspace_kanban(self, workspace_slug: str, workspace_id: str):
        """Start kanban containers for a workspace"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        project_name = f"{workspace_slug}-kanban"
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")
        workspace_data_host_path = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}"

        env = os.environ.copy()
        env.update({
            "TEAM_SLUG": workspace_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": workspace_data_host_path,
        })

        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "up", "-d", "api", "web"],
            capture_output=True,
            text=True,
            env=env,
            check=False
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to start kanban containers: {result.stderr}")

    async def _start_workspace_app(self, workspace_slug: str):
        """Start app containers for a workspace"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        compose_file = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/docker-compose.app.yml"
        project_name = f"{workspace_slug}-app"

        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "up", "-d"],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            logger.warning(f"[{workspace_slug}] App containers failed to start: {result.stderr}")

    async def recover_orphaned_agent_tasks(self):
        """
        Recover orphaned agent tasks from previous orchestrator run.

        When the orchestrator restarts while agents are running, those cards
        will be stuck with agent_status.status = "processing". This method
        finds those cards and automatically re-queues them for processing.

        Additionally, this method scans cards in agent-managed columns that
        may not have been processed (no agent_status or pending status).

        The recovery process:
        1. Finds cards with agent_status.status = "processing" (interrupted)
        2. Finds cards in agent-managed columns without agent_status (never triggered)
        3. Retrieves the original task data using task_id from agent_status
        4. Re-queues the task with high priority
        5. Creates fresh tasks for cards that need processing
        6. Falls back to marking as failed if recovery isn't possible
        """
        logger.info("Checking for orphaned agent tasks and cards in agent-managed columns...")

        # Read portal database to get active workspaces
        portal_db_path = Path("/app/data/portal/portal.json")
        if not portal_db_path.exists():
            logger.warning("Portal database not found, skipping orphan recovery")
            return

        try:
            with open(portal_db_path, 'r') as f:
                portal_data = json.load(f)

            workspaces = portal_data.get("workspaces", {})
            if not workspaces:
                logger.info("No workspaces found, skipping orphan recovery")
                return

            recovered = 0
            cross_domain_secret = os.environ.get("CROSS_DOMAIN_SECRET", "")

            for ws_key, ws in workspaces.items():
                workspace_slug = ws.get("slug")
                if not workspace_slug:
                    continue

                # Check if workspace containers are running
                project_name = f"{workspace_slug}-kanban"
                result = subprocess.run(
                    ["docker", "compose", "-p", project_name, "ps", "-q"],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if not result.stdout.strip():
                    # Workspace not running, skip
                    continue

                # Query kanban API for cards with processing status
                kanban_api_url = f"http://{workspace_slug}-kanban-api-1:8000"
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        # Get all boards to find cards
                        boards_resp = await client.get(
                            f"{kanban_api_url}/boards",
                            headers={"X-Service-Secret": cross_domain_secret}
                        )
                        if boards_resp.status_code != 200:
                            continue

                        boards = boards_resp.json()
                        for board in boards:
                            board_id = board.get("id")
                            board_resp = await client.get(
                                f"{kanban_api_url}/boards/{board_id}",
                                headers={"X-Service-Secret": cross_domain_secret}
                            )
                            if board_resp.status_code != 200:
                                continue

                            board_data = board_resp.json()
                            dev_column_id = None

                            # Find Development column (fallback for failed cards)
                            for col in board_data.get("columns", []):
                                if col.get("name") == "Development":
                                    dev_column_id = col.get("id")
                                    break

                            # Get column agent configurations for this board
                            column_agent_configs = {}
                            try:
                                agent_configs_resp = await client.get(
                                    f"{kanban_api_url}/agents/boards/{board_id}/agents",
                                    headers={"X-Service-Secret": cross_domain_secret}
                                )
                                if agent_configs_resp.status_code == 200:
                                    configs_data = agent_configs_resp.json()
                                    # Build map of column_id -> {config, agent}
                                    # Response format: {"board_id": ..., "columns": [{column_id, config, agent}, ...]}
                                    for col_cfg in configs_data.get("columns", []):
                                        col_id = col_cfg.get("column_id")
                                        # Only include if config exists and has an agent assigned
                                        if col_id and col_cfg.get("config"):
                                            # Build resolved agent_config from base agent + overrides
                                            base_agent = col_cfg.get("agent", {}) or {}
                                            config = col_cfg.get("config", {})
                                            overrides = config.get("agent_config_override", {}) or {}

                                            resolved_config = {
                                                "agent_name": config.get("agent_name"),
                                                "persona": overrides.get("persona") or base_agent.get("persona", ""),
                                                "tool_profile": overrides.get("tool_profile") or base_agent.get("tool_profile", "developer"),
                                                "timeout": overrides.get("timeout") or base_agent.get("timeout", 600),
                                                "column_success": config.get("column_success"),
                                                "column_failure": config.get("column_failure"),
                                                "llm_provider": overrides.get("llm_provider") or config.get("llm_provider"),
                                            }
                                            column_agent_configs[col_id] = {
                                                "column_id": col_id,
                                                "column_name": col_cfg.get("column_name"),
                                                "agent_config": resolved_config,
                                            }
                            except Exception as e:
                                logger.debug(f"[{workspace_slug}] Could not get column agent configs: {e}")

                            # Check all cards in all columns
                            for col in board_data.get("columns", []):
                                column_id = col.get("id")
                                column_name = col.get("name", "")
                                column_has_agent = column_id in column_agent_configs

                                for card in col.get("cards", []):
                                    card_id = card.get("id")
                                    agent_status = card.get("agent_status")

                                    # Case 1: Card with processing status (interrupted agent)
                                    if agent_status and agent_status.get("status") == "processing":
                                        agent_name = agent_status.get("agent_name", "unknown")
                                        started_at = agent_status.get("started_at", "unknown")

                                        original_task_id = agent_status.get("task_id")
                                        logger.warning(
                                            f"[{workspace_slug}] Found orphaned agent task: "
                                            f"card={card_id}, agent={agent_name}, task_id={original_task_id}, started_at={started_at}"
                                        )

                                        # Try to retrieve and re-queue the original task
                                        requeued = False
                                        if original_task_id:
                                            task_data = await self.redis.hget(f"task:{original_task_id}", "data")
                                            if task_data:
                                                try:
                                                    original_task = json.loads(task_data)
                                                    # Re-queue the task
                                                    new_task_id = await self._requeue_agent_task(original_task)
                                                    logger.info(
                                                        f"[{card_id}] Re-queued orphaned task as {new_task_id}"
                                                    )

                                                    # Add comment explaining the restart
                                                    comment_text = (
                                                        f"## Agent: {agent_name.title()}\n\n"
                                                        f"**Status:** Restarted\n\n"
                                                        f"The orchestrator restarted while this agent was running. "
                                                        f"The task has been automatically re-queued and will continue shortly."
                                                    )
                                                    await client.post(
                                                        f"{kanban_api_url}/cards/{card_id}/comments",
                                                        headers={"X-Service-Secret": cross_domain_secret},
                                                        json={"text": comment_text, "author_name": "Orchestrator"}
                                                    )
                                                    requeued = True
                                                except Exception as e:
                                                    logger.warning(f"[{card_id}] Failed to re-queue task: {e}")

                                        if not requeued:
                                            # Fallback: clear status and notify user if we couldn't re-queue
                                            logger.warning(f"[{card_id}] Could not re-queue task, clearing status")
                                            comment_text = (
                                                f"## Agent: {agent_name.title()}\n\n"
                                                f"**Status:** Failed (Interrupted)\n\n"
                                                f"The orchestrator restarted while this agent was running. "
                                                f"Could not automatically restart the task. "
                                                f"Please move the card back to trigger the agent again."
                                            )
                                            await client.post(
                                                f"{kanban_api_url}/cards/{card_id}/comments",
                                                headers={"X-Service-Secret": cross_domain_secret},
                                                json={"text": comment_text, "author_name": "Orchestrator"}
                                            )

                                            # Move to Development column if found
                                            if dev_column_id:
                                                await client.post(
                                                    f"{kanban_api_url}/cards/{card_id}/move",
                                                    headers={"X-Service-Secret": cross_domain_secret},
                                                    params={"column_id": dev_column_id, "position": 0}
                                                )
                                                logger.info(f"[{card_id}] Moved to Development column")

                                            # Clear agent_status only if not re-queued
                                            # Pass original_task_id to prevent race condition
                                            await client.delete(
                                                f"{kanban_api_url}/cards/{card_id}/agent-status",
                                                headers={"X-Service-Secret": cross_domain_secret},
                                                params={"task_id": original_task_id} if original_task_id else None
                                            )
                                            logger.info(f"[{card_id}] Cleared agent_status")

                                        recovered += 1

                                    # Case 2: Card in agent-managed column without agent_status
                                    # (card was moved but agent never triggered or was lost)
                                    elif column_has_agent and not agent_status:
                                        col_config = column_agent_configs[column_id]
                                        agent_config = col_config.get("agent_config", {})
                                        agent_name = agent_config.get("agent_name", "unknown")

                                        logger.info(
                                            f"[{workspace_slug}] Found card in agent-managed column without agent_status: "
                                            f"card={card_id}, column={column_name}, agent={agent_name}"
                                        )

                                        # Create a fresh agent task for this card
                                        try:
                                            new_task_id = await self._create_fresh_agent_task(
                                                card=card,
                                                column_name=column_name,
                                                agent_config=agent_config,
                                                workspace_slug=workspace_slug,
                                                workspace=ws,
                                                board_id=board_id,
                                                kanban_api_url=kanban_api_url,
                                            )

                                            if new_task_id:
                                                # Add comment explaining the recovery
                                                comment_text = (
                                                    f"## Agent: {agent_name.title()}\n\n"
                                                    f"**Status:** Triggered (Recovery)\n\n"
                                                    f"The orchestrator detected this card in an agent-managed column "
                                                    f"without a processing status. The agent has been triggered to process this card."
                                                )
                                                await client.post(
                                                    f"{kanban_api_url}/cards/{card_id}/comments",
                                                    headers={"X-Service-Secret": cross_domain_secret},
                                                    json={"text": comment_text, "author_name": "Orchestrator"}
                                                )
                                                logger.info(f"[{card_id}] Created fresh agent task: {new_task_id}")
                                                recovered += 1
                                        except Exception as e:
                                            logger.warning(f"[{card_id}] Failed to create fresh agent task: {e}")

                except Exception as e:
                    logger.warning(f"[{workspace_slug}] Failed to check for orphaned tasks: {e}")
                    continue

            if recovered > 0:
                logger.info(f"Recovered {recovered} orphaned agent task(s)")
            else:
                logger.info("No orphaned agent tasks found")

        except Exception as e:
            logger.error(f"Failed to recover orphaned agent tasks: {e}")

    async def _requeue_agent_task(self, original_task: dict) -> str:
        """Re-queue an agent task after orchestrator restart.

        Creates a new task with the same payload but fresh metadata,
        and adds it to the agent queue for processing.

        Args:
            original_task: The original task dict containing type and payload

        Returns:
            The new task_id
        """
        new_task_id = str(uuid.uuid4())
        payload = original_task.get("payload", {})
        user_id = original_task.get("user_id", "system")
        priority = original_task.get("priority", "normal")

        new_task = {
            "task_id": new_task_id,
            "type": "agent.process_card",
            "status": "pending",
            "payload": payload,
            "user_id": user_id,
            "priority": priority,
            "progress": {
                "current_step": 0,
                "total_steps": 0,
                "step_name": "Queued (restarted)",
                "percentage": 0
            },
            "created_at": datetime.utcnow().isoformat() + "Z",
            "started_at": None,
            "completed_at": None,
            "restarted_from": original_task.get("task_id"),
        }

        # Store task data in Redis
        await self.redis.hset(f"task:{new_task_id}", mapping={
            "data": json.dumps(new_task)
        })

        # Add to agent queue (high priority for restarts)
        queue_key = f"queue:agents:high"
        await self.redis.lpush(queue_key, new_task_id)

        logger.info(f"Re-queued agent task {new_task_id} (original: {original_task.get('task_id')})")
        return new_task_id

    async def _create_fresh_agent_task(
        self,
        card: dict,
        column_name: str,
        agent_config: dict,
        workspace_slug: str,
        workspace: dict,
        board_id: str,
        kanban_api_url: str,
    ) -> Optional[str]:
        """Create a fresh agent task for a card in an agent-managed column.

        This is used when recovery finds a card in an agent-managed column
        but no original task data exists (e.g., webhook was lost).

        Args:
            card: The card data from kanban API
            column_name: The column name the card is in
            agent_config: The agent configuration for the column
            workspace_slug: The workspace slug
            workspace: The workspace data from portal database
            board_id: The board ID
            kanban_api_url: The kanban API URL

        Returns:
            The new task_id, or None if creation failed
        """
        card_id = card.get("id")
        card_title = card.get("title", "Untitled")
        card_description = card.get("description", "")
        card_number = card.get("card_number")
        labels = card.get("labels", [])
        claude_session_id = card.get("claude_session_id")

        # Determine sandbox context from card
        sandbox_id = card.get("sandbox_id")
        sandbox_slug = None
        git_branch = "main"
        target_project_path = f"/data/repos/{workspace_slug}"

        # If card has a sandbox_id, look it up in the portal database
        if sandbox_id:
            portal_db_path = Path("/app/data/portal/portal.json")
            if portal_db_path.exists():
                try:
                    with open(portal_db_path, 'r') as f:
                        portal_data = json.load(f)

                    sandboxes = portal_data.get("sandboxes", {})
                    # Find sandbox by ID or full_slug
                    for sb_key, sb in sandboxes.items():
                        if sb.get("id") == sandbox_id or sb.get("full_slug") == sandbox_id:
                            full_slug = sb.get("full_slug", sandbox_id)
                            sandbox_slug = sb.get("slug")
                            git_branch = sb.get("git_branch", f"sandbox/{full_slug}")
                            target_project_path = f"/data/repos/{workspace_slug}/sandboxes/{full_slug}"
                            # Use actual UUID
                            sandbox_id = sb.get("id", sandbox_id)
                            break
                except Exception as e:
                    logger.warning(f"[{card_id}] Could not look up sandbox: {e}")

        # Create new task
        new_task_id = str(uuid.uuid4())
        agent_name = agent_config.get("agent_name", "developer")

        new_task = {
            "task_id": new_task_id,
            "type": "agent.process_card",
            "status": "pending",
            "payload": {
                "card_id": card_id,
                "card_number": card_number,
                "card_title": card_title,
                "card_description": card_description,
                "column_name": column_name,
                "agent_config": agent_config,
                "sandbox_id": sandbox_id or workspace_slug,
                "sandbox_slug": sandbox_slug,
                "claude_session_id": claude_session_id,
                "workspace_slug": workspace_slug,
                "git_branch": git_branch,
                "kanban_api_url": kanban_api_url,
                "target_project_path": target_project_path,
                "board_id": board_id,
                "labels": labels,
                "github_repo_url": workspace.get("github_repo_url"),
            },
            "user_id": "system",
            "priority": "high",
            "progress": {
                "current_step": 0,
                "total_steps": 0,
                "step_name": "Queued (recovery)",
                "percentage": 0
            },
            "created_at": datetime.utcnow().isoformat() + "Z",
            "started_at": None,
            "completed_at": None,
            "recovery_triggered": True,
        }

        # Store task data in Redis
        await self.redis.hset(f"task:{new_task_id}", mapping={
            "data": json.dumps(new_task)
        })

        # Add to agent queue (high priority for recovery)
        queue_key = "queue:agents:high"
        await self.redis.lpush(queue_key, new_task_id)

        logger.info(
            f"Created fresh agent task {new_task_id} for card {card_id} "
            f"(agent={agent_name}, column={column_name})"
        )
        return new_task_id

    async def process_task(self, task_id: str):
        """Process a provisioning task"""
        try:
            task_data = await self.redis.hget(f"task:{task_id}", "data")
            if not task_data:
                logger.error(f"Task {task_id} not found")
                return

            task = json.loads(task_data)
            task_type = task.get("type")

            if task_type == "team.provision":
                await self.provision_team(task)
            elif task_type == "team.delete":
                await self.delete_team(task)
            elif task_type == "team.restart":
                await self.restart_team(task)
            elif task_type == "team.start":
                await self.start_team(task)
            # App Factory - Workspace tasks
            elif task_type == "workspace.provision":
                await self.provision_workspace(task)
            elif task_type == "workspace.delete":
                await self.delete_workspace(task)
            elif task_type == "workspace.restart":
                await self.restart_workspace(task)
            elif task_type == "workspace.start":
                await self.start_workspace(task)
            elif task_type == "workspace.link_app":
                await self.link_app_to_workspace(task)
            elif task_type == "workspace.unlink_app":
                await self.unlink_app_from_workspace(task)
            # App Factory - Sandbox tasks
            elif task_type == "sandbox.provision":
                await self.provision_sandbox(task)
            elif task_type == "sandbox.delete":
                await self.delete_sandbox(task)
            elif task_type == "sandbox.restart":
                await self.restart_sandbox(task)
            elif task_type == "sandbox.pull_request":
                await self.sandbox_pull_request(task)
            # Agent tasks (on-demand AI processing)
            elif task_type == "agent.process_card":
                await self.process_agent_task(task)
            elif task_type == "agent.enhance_description":
                await self.enhance_description_task(task)
            else:
                logger.warning(f"Unknown task type: {task_type}")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)
            await self.fail_task(task_id, str(e))

    async def provision_team(self, task: dict):
        """Provision a new team environment"""
        task_id = task["task_id"]
        payload = task["payload"]
        team_slug = payload["team_slug"]
        team_id = payload["team_id"]

        # Store payload for access by step functions
        self._current_payload = payload

        logger.info(f"Provisioning team: {team_slug}")

        steps = [
            ("Validating team configuration", self._validate_team),
            ("Creating team directory", self._create_team_directory),
            ("Initializing database", self._init_database),
            ("Generating configuration", self._generate_config),
            ("Adding DNS record", self._add_dns_record),
            ("Waiting for DNS propagation", self._wait_dns),
            ("Issuing SSL certificate", self._issue_certificate),
            ("Updating Traefik config", self._update_traefik),
            ("Starting containers", self._start_containers),
            ("Running health check", self._health_check),
            ("Finalizing setup", self._finalize),
        ]

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(team_slug, team_id)
                logger.info(f"[{team_slug}] {step_name} - completed")

            await self.complete_task(task_id, {
                "action": "create_team",
                "team_slug": team_slug,
                "url": f"https://{team_slug}.{DOMAIN}"
            })

            logger.info(f"Team {team_slug} provisioned successfully")

        except Exception as e:
            logger.error(f"Provisioning failed: {e}")
            await self.fail_task(task_id, str(e))
            raise

    async def _validate_team(self, team_slug: str, team_id: str):
        """Validate team configuration"""
        if not team_slug or len(team_slug) < 3:
            raise ValueError("Invalid team slug")

    async def _create_team_directory(self, team_slug: str, team_id: str):
        """Create team directory structure"""
        team_dir = TEAMS_DIR / team_slug
        (team_dir / "db").mkdir(parents=True, exist_ok=True)
        (team_dir / "uploads" / "cards").mkdir(parents=True, exist_ok=True)
        (team_dir / "uploads" / "avatars").mkdir(parents=True, exist_ok=True)
        (team_dir / "cache" / "previews").mkdir(parents=True, exist_ok=True)
        (team_dir / "backups").mkdir(parents=True, exist_ok=True)
        (team_dir / "logs").mkdir(parents=True, exist_ok=True)

    async def _init_database(self, team_slug: str, team_id: str):
        """Initialize team database with creator as owner"""
        db_file = TEAMS_DIR / team_slug / "db" / "team.json"

        # Get owner info from payload
        owner_id = self._current_payload.get("owner_id")
        owner_email = self._current_payload.get("owner_email")
        owner_name = self._current_payload.get("owner_name") or (owner_email.split("@")[0] if owner_email else "Owner")

        # Initialize database with creator as owner
        initial_data = {
            "_default": {},
            "members": {
                "1": {
                    "id": owner_id,
                    "email": owner_email,
                    "name": owner_name,
                    "role": "owner",
                    "is_active": True,
                    "avatar_url": None,
                    "created_at": datetime.utcnow().isoformat(),
                    "last_seen": None
                }
            }
        }

        db_file.write_text(json.dumps(initial_data, indent=2))
        logger.info(f"[{team_slug}] Database initialized with {owner_email} as owner")

    async def _generate_config(self, team_slug: str, team_id: str):
        """Generate docker-compose and nginx config for team"""
        # Config is applied dynamically via container labels
        logger.info(f"[{team_slug}] Preparing container configuration")

    async def _add_dns_record(self, team_slug: str, team_id: str):
        """Add DNS record for team subdomain"""
        zone_file = DNS_DIR / "devkanban.io.db"
        if zone_file.exists():
            content = zone_file.read_text()
            new_record = f"{team_slug}    IN  A       {HOST_IP}\n"
            if team_slug not in content:
                zone_file.write_text(content + new_record)
        # For localhost development, DNS is handled by /etc/hosts or wildcard

    async def _wait_dns(self, team_slug: str, team_id: str):
        """Wait for DNS propagation"""
        # For localhost, no waiting needed
        await asyncio.sleep(0.5)

    async def _issue_certificate(self, team_slug: str, team_id: str):
        """Issue SSL certificate for team subdomain"""
        if CERT_MODE == "development":
            # Wildcard cert handles all subdomains in development
            logger.info(f"[{team_slug}] Using wildcard development certificate")
        else:
            # Would call certbot for production
            logger.info(f"[{team_slug}] Would request SSL certificate")

    async def _update_traefik(self, team_slug: str, team_id: str):
        """Update Traefik dynamic configuration"""
        # Traefik auto-discovers containers via labels, no manual config needed
        logger.info(f"[{team_slug}] Traefik will auto-discover containers via labels")

    async def _start_containers(self, team_slug: str, team_id: str):
        """Start team containers using Docker Compose as a stack"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        logger.info(f"[{team_slug}] Starting containers as stack...")

        # Project name for docker compose stack
        project_name = f"{team_slug}-kanban"

        # Host path for team data
        team_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{team_slug}"

        # Docker compose file path (mounted in orchestrator container)
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")

        # Environment variables for docker compose
        # These inherit from orchestrator's environment (which gets them from root .env via docker-compose.yml)
        env = os.environ.copy()

        # Get cross-domain secret from Key Vault (production) or environment (development)
        # This ensures team containers use the same secret as the portal API
        cross_domain_secret = keyvault_service.get_cross_domain_secret()

        env.update({
            "TEAM_SLUG": team_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": team_data_host_path,
            "CROSS_DOMAIN_SECRET": cross_domain_secret,
        })

        # Stop and remove existing stack if it exists
        logger.info(f"[{team_slug}] Removing any existing stack...")
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "down", "--remove-orphans"],
            capture_output=True,
            text=True,
            env=env,
            check=False
        )

        # Start the stack
        logger.info(f"[{team_slug}] Starting docker compose stack...")
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "up", "-d"],
            capture_output=True,
            text=True,
            env=env,
            check=True
        )

        if result.returncode != 0:
            logger.error(f"[{team_slug}] Docker compose failed: {result.stderr}")
            raise RuntimeError(f"Failed to start containers: {result.stderr}")

        logger.info(f"[{team_slug}] Stack started successfully")

    async def _health_check(self, team_slug: str, team_id: str):
        """Check team environment health"""
        if not self.docker_available:
            return

        # Docker compose creates containers with -1 suffix
        api_container_name = f"{team_slug}-kanban-api-1"
        web_container_name = f"{team_slug}-kanban-web-1"

        # Wait for containers to be running
        max_retries = 10
        for i in range(max_retries):
            result = run_docker_cmd([
                "inspect", "-f", "{{.State.Status}}",
                api_container_name, web_container_name
            ], check=False)

            if result.returncode == 0:
                statuses = result.stdout.strip().split("\n")
                if all(s == "running" for s in statuses):
                    logger.info(f"[{team_slug}] All containers are running")
                    return

            logger.info(f"[{team_slug}] Waiting for containers... (attempt {i+1}/{max_retries})")
            await asyncio.sleep(1)

        raise RuntimeError(f"Containers for {team_slug} failed to start")

    async def _finalize(self, team_slug: str, team_id: str):
        """Finalize team setup - update team status to active"""
        # Publish team status update for portal to process
        await self.redis.publish("team:status", json.dumps({
            "team_id": team_id,
            "team_slug": team_slug,
            "status": "active"
        }))
        await asyncio.sleep(0.5)

    async def delete_team(self, task: dict):
        """Delete a team environment"""
        task_id = task["task_id"]
        payload = task["payload"]
        team_slug = payload["team_slug"]
        team_id = payload.get("team_id")

        logger.info(f"Deleting team: {team_slug}")

        steps = [
            ("Stopping containers", self._delete_stop_containers),
            ("Removing containers", self._delete_remove_containers),
            ("Archiving data", self._delete_archive_data),
            ("Cleaning up", self._delete_cleanup),
        ]

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(team_slug, team_id)
                logger.info(f"[{team_slug}] {step_name} - completed")

            # Publish status update
            await self.redis.publish("team:status", json.dumps({
                "team_id": team_id,
                "team_slug": team_slug,
                "status": "deleted"
            }))

            await self.complete_task(task_id, {
                "action": "delete_team",
                "team_slug": team_slug,
                "deleted": True
            })

            logger.info(f"Team {team_slug} deleted successfully")

        except Exception as e:
            logger.error(f"Team deletion failed: {e}")
            await self.fail_task(task_id, str(e))
            raise

    async def _delete_stop_containers(self, team_slug: str, team_id: str):
        """Stop team containers using docker compose"""
        if not self.docker_available:
            logger.warning("Docker not available, skipping container stop")
            return

        project_name = f"{team_slug}-kanban"
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")
        team_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{team_slug}"

        env = os.environ.copy()
        env.update({
            "TEAM_SLUG": team_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": team_data_host_path,
        })

        # Stop the stack
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "stop"],
            capture_output=True,
            text=True,
            env=env,
            check=False
        )

        if result.returncode == 0:
            logger.info(f"[{team_slug}] Stack stopped")
        else:
            # Fallback: try stopping individual containers (legacy naming)
            for container in [f"{team_slug}-kanban-api", f"{team_slug}-kanban-web"]:
                run_docker_cmd(["stop", container], check=False)
            logger.info(f"[{team_slug}] Containers stopped (fallback)")

    async def _delete_remove_containers(self, team_slug: str, team_id: str):
        """Remove team containers using docker compose"""
        if not self.docker_available:
            logger.warning("Docker not available, skipping container removal")
            return

        project_name = f"{team_slug}-kanban"
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")
        team_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{team_slug}"

        env = os.environ.copy()
        env.update({
            "TEAM_SLUG": team_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": team_data_host_path,
        })

        # Remove the stack
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "down", "--remove-orphans"],
            capture_output=True,
            text=True,
            env=env,
            check=False
        )

        if result.returncode == 0:
            logger.info(f"[{team_slug}] Stack removed")
        else:
            # Fallback: try removing individual containers (legacy naming)
            for container in [f"{team_slug}-kanban-api", f"{team_slug}-kanban-web",
                              f"{team_slug}-kanban-api-1", f"{team_slug}-kanban-web-1"]:
                run_docker_cmd(["rm", "-f", container], check=False)
            logger.info(f"[{team_slug}] Containers removed (fallback)")

    async def _delete_archive_data(self, team_slug: str, team_id: str):
        """Archive team data before deletion"""
        team_dir = TEAMS_DIR / team_slug
        archive_dir = TEAMS_DIR / ".archived"

        if team_dir.exists():
            archive_dir.mkdir(parents=True, exist_ok=True)
            archived_name = f"{team_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            archived_path = archive_dir / archived_name

            shutil.move(str(team_dir), str(archived_path))
            logger.info(f"[{team_slug}] Data archived to {archived_path}")
        else:
            logger.warning(f"[{team_slug}] Team directory not found, nothing to archive")

    async def _delete_cleanup(self, team_slug: str, team_id: str):
        """Final cleanup tasks"""
        # Remove DNS record if exists
        zone_file = DNS_DIR / "devkanban.io.db"
        if zone_file.exists():
            content = zone_file.read_text()
            lines = content.split("\n")
            lines = [line for line in lines if not line.startswith(f"{team_slug} ")]
            zone_file.write_text("\n".join(lines))
            logger.info(f"[{team_slug}] DNS record removed")

        await asyncio.sleep(0.2)

    async def restart_team(self, task: dict):
        """Restart/rebuild a team's containers"""
        task_id = task["task_id"]
        payload = task["payload"]
        team_slug = payload["team_slug"]
        team_id = payload.get("team_id")
        rebuild = payload.get("rebuild", False)

        logger.info(f"Restarting team: {team_slug} (rebuild={rebuild})")

        if rebuild:
            steps = [
                ("Stopping containers", self._restart_stop_containers),
                ("Removing old images", self._restart_remove_images),
                ("Rebuilding containers", self._restart_rebuild_containers),
                ("Starting containers", self._restart_start_containers),
                ("Running health check", self._health_check),
            ]
        else:
            steps = [
                ("Stopping containers", self._restart_stop_containers),
                ("Starting containers", self._restart_start_containers),
                ("Running health check", self._health_check),
            ]

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(team_slug, team_id)
                logger.info(f"[{team_slug}] {step_name} - completed")

            # Publish status update
            await self.redis.publish("team:status", json.dumps({
                "team_id": team_id,
                "team_slug": team_slug,
                "status": "active"
            }))

            await self.complete_task(task_id, {
                "action": "restart_team",
                "team_slug": team_slug,
                "rebuild": rebuild,
                "url": f"https://{team_slug}.{DOMAIN}"
            })

            logger.info(f"Team {team_slug} restarted successfully")

        except Exception as e:
            logger.error(f"Team restart failed: {e}")
            await self.fail_task(task_id, str(e))
            raise

    async def _restart_stop_containers(self, team_slug: str, team_id: str):
        """Stop team containers"""
        if not self.docker_available:
            logger.warning("Docker not available, skipping container stop")
            return

        project_name = f"{team_slug}-kanban"
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")
        team_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{team_slug}"

        env = os.environ.copy()
        env.update({
            "TEAM_SLUG": team_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": team_data_host_path,
        })

        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "stop"],
            capture_output=True,
            text=True,
            env=env,
            check=False
        )

        if result.returncode == 0:
            logger.info(f"[{team_slug}] Containers stopped")
        else:
            logger.warning(f"[{team_slug}] Stop warning: {result.stderr}")

    async def _restart_remove_images(self, team_slug: str, team_id: str):
        """Remove team container images for rebuild"""
        if not self.docker_available:
            return

        project_name = f"{team_slug}-kanban"
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")
        team_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{team_slug}"

        env = os.environ.copy()
        env.update({
            "TEAM_SLUG": team_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": team_data_host_path,
        })

        # Remove containers and local images
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "down", "--rmi", "local", "--remove-orphans"],
            capture_output=True,
            text=True,
            env=env,
            check=False
        )

        logger.info(f"[{team_slug}] Old images removed")

    async def _restart_rebuild_containers(self, team_slug: str, team_id: str):
        """Rebuild team containers"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        project_name = f"{team_slug}-kanban"
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")
        team_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{team_slug}"

        env = os.environ.copy()
        env.update({
            "TEAM_SLUG": team_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": team_data_host_path,
        })

        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "build", "--no-cache"],
            capture_output=True,
            text=True,
            env=env,
            check=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to rebuild containers: {result.stderr}")

        logger.info(f"[{team_slug}] Containers rebuilt")

    async def _restart_start_containers(self, team_slug: str, team_id: str):
        """Start team containers"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        project_name = f"{team_slug}-kanban"
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")
        team_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{team_slug}"

        env = os.environ.copy()
        env.update({
            "TEAM_SLUG": team_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": team_data_host_path,
        })

        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "up", "-d"],
            capture_output=True,
            text=True,
            env=env,
            check=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to start containers: {result.stderr}")

        logger.info(f"[{team_slug}] Containers started")

    async def update_progress(
        self,
        task_id: str,
        current_step: int,
        total_steps: int,
        step_name: str
    ):
        """Update task progress"""
        task_data = await self.redis.hget(f"task:{task_id}", "data")
        if not task_data:
            return

        task = json.loads(task_data)
        percentage = int((current_step / total_steps) * 100)

        task["status"] = "in_progress"
        task["progress"] = {
            "current_step": current_step,
            "total_steps": total_steps,
            "step_name": step_name,
            "percentage": percentage
        }

        await self.redis.hset(f"task:{task_id}", "data", json.dumps(task))

        # Publish progress with payload info for frontend tracking
        payload = task.get("payload", {})
        await self.redis.publish(f"tasks:{task['user_id']}", json.dumps({
            "type": "task.progress",
            "task_id": task_id,
            "step": current_step,
            "total_steps": total_steps,
            "step_name": step_name,
            "percentage": percentage,
            "payload": {
                "action": payload.get("action"),
                "workspace_id": payload.get("workspace_id"),
                "workspace_slug": payload.get("workspace_slug"),
                "sandbox_id": payload.get("sandbox_id"),
                "sandbox_slug": payload.get("sandbox_slug"),
            }
        }))

    async def complete_task(self, task_id: str, result: dict):
        """Mark task as completed"""
        task_data = await self.redis.hget(f"task:{task_id}", "data")
        if not task_data:
            return

        task = json.loads(task_data)
        task["status"] = "completed"
        task["result"] = result
        task["progress"]["percentage"] = 100

        await self.redis.hset(f"task:{task_id}", "data", json.dumps(task))

        await self.redis.publish(f"tasks:{task['user_id']}", json.dumps({
            "type": "task.completed",
            "task_id": task_id,
            "result": result
        }))

    async def fail_task(self, task_id: str, error: str):
        """Mark task as failed"""
        task_data = await self.redis.hget(f"task:{task_id}", "data")
        if not task_data:
            return

        task = json.loads(task_data)
        task["status"] = "failed"
        task["error"] = error

        await self.redis.hset(f"task:{task_id}", "data", json.dumps(task))

        await self.redis.publish(f"tasks:{task['user_id']}", json.dumps({
            "type": "task.failed",
            "task_id": task_id,
            "error": error
        }))

    # ========== Auto-scaling: Idle Team Management ==========

    async def check_idle_teams(self):
        """Background task to check for idle teams and suspend them.

        Runs every IDLE_CHECK_INTERVAL seconds and suspends teams that have
        no WebSocket activity for more than IDLE_THRESHOLD seconds.
        """
        logger.info("Starting idle team checker...")

        while self.running:
            try:
                # Wait for the check interval
                await asyncio.sleep(IDLE_CHECK_INTERVAL)

                if not self.running:
                    break

                logger.info("Checking for idle teams...")

                # Get all running team containers
                running_teams = await self._get_running_teams()
                logger.info(f"Found {len(running_teams)} running teams: {running_teams}")

                current_time = int(time.time())

                for team_slug in running_teams:
                    # Check last activity from Redis
                    last_activity = await self.redis.get(f"team:{team_slug}:last_activity")

                    if last_activity is None:
                        # No activity recorded - suspend the team
                        logger.info(f"[{team_slug}] No activity recorded, suspending")
                        await self.suspend_team(team_slug)
                    else:
                        last_activity_time = int(last_activity)
                        idle_time = current_time - last_activity_time

                        if idle_time > IDLE_THRESHOLD:
                            logger.info(f"[{team_slug}] Idle for {idle_time}s (threshold: {IDLE_THRESHOLD}s), suspending")
                            await self.suspend_team(team_slug)
                        else:
                            logger.debug(f"[{team_slug}] Active ({idle_time}s since last activity)")

            except Exception as e:
                logger.error(f"Idle check error: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait a minute before retrying

        logger.info("Idle team checker stopped")

    async def process_health_checks(self):
        """Background task to process workspace health check requests.

        Listens on Redis list 'health_check:requests' for health check requests
        and writes results to 'health_check:{request_id}:result' keys.
        """
        logger.info("Starting health check processor...")

        while self.running:
            try:
                # Wait for a health check request with 1 second timeout
                result = await self.redis.brpop("health_check:requests", timeout=1)

                if result:
                    _, request_data = result
                    request = json.loads(request_data)
                    request_id = request.get("request_id")
                    workspace_slugs = request.get("workspace_slugs", [])

                    logger.debug(f"Processing health check request {request_id} for {len(workspace_slugs)} workspaces")

                    # Check health for each workspace
                    health_results = {}
                    for workspace_slug in workspace_slugs:
                        health_results[workspace_slug] = self._check_workspace_container_health(workspace_slug)

                    # Write result to Redis with 60 second expiry
                    await self.redis.setex(
                        f"health_check:{request_id}:result",
                        60,
                        json.dumps(health_results)
                    )

                    logger.debug(f"Health check {request_id} completed")

            except Exception as e:
                logger.error(f"Health check processor error: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info("Health check processor stopped")

    def _check_workspace_container_health(self, workspace_slug: str) -> dict:
        """Check container health for a workspace (synchronous).

        Returns dict with:
        - kanban_running: bool
        - app_running: bool | None (None if no app)
        - sandboxes: list[{slug, running}]
        - all_healthy: bool
        """
        if not self.docker_available:
            return {
                "kanban_running": False,
                "app_running": None,
                "sandboxes": [],
                "all_healthy": False,
                "error": "Docker not available"
            }

        # Check if this workspace has an app
        app_compose = Path(f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/docker-compose.app.yml")
        legacy_app_compose = Path(f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/app/docker-compose.yml")
        has_app = app_compose.exists() or legacy_app_compose.exists()

        # Check kanban containers - project name is "{slug}-kanban" so containers are {slug}-kanban-api-1
        kanban_running = self._is_container_running(f"{workspace_slug}-kanban-api")

        # Check app containers if workspace has app template
        app_running = None
        if has_app:
            # App containers are named {slug}-api, {slug}-web, etc.
            app_running = self._is_container_running(f"{workspace_slug}-api")

        # Check sandbox containers
        sandboxes = []
        sandbox_slugs = self._get_workspace_sandboxes(workspace_slug)
        for full_slug in sandbox_slugs:
            # Sandbox containers are named {full_slug}-api, not {full_slug}-app
            sandbox_running = self._is_container_running(f"{full_slug}-api")
            sandboxes.append({
                "slug": full_slug.replace(f"{workspace_slug}-", ""),
                "full_slug": full_slug,
                "running": sandbox_running
            })

        # Determine if all healthy
        all_healthy = kanban_running
        if app_running is not None:
            all_healthy = all_healthy and app_running
        for sandbox in sandboxes:
            all_healthy = all_healthy and sandbox["running"]

        return {
            "kanban_running": kanban_running,
            "app_running": app_running,
            "sandboxes": sandboxes,
            "all_healthy": all_healthy
        }

    def _is_container_running(self, container_name_prefix: str) -> bool:
        """Check if any container with the given prefix is running."""
        try:
            result = run_docker_cmd([
                "ps", "--filter", f"name={container_name_prefix}",
                "--format", "{{.Names}}"
            ], check=False)

            if result.returncode != 0:
                return False

            # Check if any matching container is running
            return bool(result.stdout.strip())
        except Exception as e:
            logger.error(f"Error checking container {container_name_prefix}: {e}")
            return False

    async def _get_running_teams(self) -> list[str]:
        """Get list of team slugs with running containers."""
        if not self.docker_available:
            return []

        try:
            result = run_docker_cmd([
                "ps", "--filter", "name=-kanban-",
                "--format", "{{.Names}}"
            ], check=False)

            if result.returncode != 0:
                return []

            teams = set()
            for line in result.stdout.strip().split('\n'):
                if line and '-kanban-' in line:
                    # Extract team slug from container name
                    # Format: {slug}-kanban-api-1 or {slug}-kanban-web-1
                    # Remove suffix "-kanban-api-1" or "-kanban-web-1"
                    if line.endswith('-kanban-api-1'):
                        slug = line[:-13]
                    elif line.endswith('-kanban-web-1'):
                        slug = line[:-13]
                    else:
                        # Unknown format, try to extract slug
                        parts = line.split('-kanban-')
                        slug = parts[0] if parts else None

                    if slug:
                        teams.add(slug)

            return list(teams)
        except Exception as e:
            logger.error(f"Failed to get running teams: {e}")
            return []

    async def suspend_team(self, team_slug: str):
        """Suspend a team by removing its containers (not deleting data).

        This is called when a team has been idle for too long.
        The team can be restarted on-demand when a user accesses it.
        Data is preserved in the data directory.
        """
        if not self.docker_available:
            return

        logger.info(f"[{team_slug}] Suspending team - removing containers...")

        project_name = f"{team_slug}-kanban"
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")
        team_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{team_slug}"

        env = os.environ.copy()
        env.update({
            "TEAM_SLUG": team_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": team_data_host_path,
        })

        # Remove containers (down instead of stop) - data is preserved
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "down"],
            capture_output=True,
            text=True,
            env=env,
            check=False
        )

        if result.returncode == 0:
            logger.info(f"[{team_slug}] Containers removed successfully")

            # Publish team status update for portal to process
            await self.redis.publish("team:status", json.dumps({
                "team_slug": team_slug,
                "status": "suspended"
            }))
        else:
            logger.error(f"[{team_slug}] Failed to suspend: {result.stderr}")

    # ========== Auto-scaling: On-Demand Team Start ==========

    async def start_team(self, task: dict):
        """Start a suspended team's containers.

        This is called when a user tries to access a suspended team.
        """
        task_id = task["task_id"]
        payload = task["payload"]
        team_slug = payload["team_slug"]
        team_id = payload.get("team_id")

        logger.info(f"Starting suspended team: {team_slug}")

        steps = [
            ("Checking team data", self._start_check_data),
            ("Starting containers", self._restart_start_containers),
            ("Running health check", self._health_check),
            ("Activating team", self._start_activate),
        ]

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(team_slug, team_id)
                logger.info(f"[{team_slug}] {step_name} - completed")

            await self.complete_task(task_id, {
                "action": "start_team",
                "team_slug": team_slug,
                "url": f"https://{team_slug}.{DOMAIN}"
            })

            logger.info(f"Team {team_slug} started successfully")

        except Exception as e:
            logger.error(f"Team start failed: {e}")
            await self.fail_task(task_id, str(e))
            raise

    async def _start_check_data(self, team_slug: str, team_id: str):
        """Verify team data directory exists."""
        team_dir = TEAMS_DIR / team_slug
        if not team_dir.exists():
            raise RuntimeError(f"Team data directory not found: {team_dir}")

        db_file = team_dir / "db" / "team.json"
        if not db_file.exists():
            raise RuntimeError(f"Team database not found: {db_file}")

        logger.info(f"[{team_slug}] Team data verified")

    async def _start_activate(self, team_slug: str, team_id: str):
        """Activate team and update status."""
        # Publish team status update for portal to process
        await self.redis.publish("team:status", json.dumps({
            "team_id": team_id,
            "team_slug": team_slug,
            "status": "active"
        }))
        await asyncio.sleep(0.5)


    # ========== App Factory: Workspace Provisioning ==========

    async def provision_workspace(self, task: dict):
        """Provision a new workspace (kanban team + optional app)"""
        task_id = task["task_id"]
        payload = task["payload"]
        workspace_id = payload["workspace_id"]
        workspace_slug = payload["workspace_slug"]
        app_template_id = payload.get("app_template_id")

        self._current_payload = payload

        logger.info(f"Provisioning workspace: {workspace_slug} (app_template: {app_template_id or 'kanban-only'})")

        # Build steps based on whether we have an app template
        steps = [
            ("Validating workspace configuration", self._workspace_validate),
            ("Creating kanban team", self._workspace_create_team),
            ("Creating default boards", self._workspace_create_default_boards),
        ]

        if app_template_id:
            steps.extend([
                ("Creating GitHub repository", self._workspace_create_github_repo),
                ("Creating Azure app registration", self._workspace_create_azure_app),
                ("Cloning repository", self._workspace_clone_repo),
                ("Issuing SSL certificate", self._workspace_issue_certificate),
                ("Creating app database", self._workspace_create_database),
                ("Deploying app containers", self._workspace_deploy_app),
                ("Creating foundation sandbox", self._workspace_create_foundation_sandbox),
            ])

        steps.extend([
            ("Running health check", self._workspace_health_check),
            ("Finalizing workspace", self._workspace_finalize),
        ])

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(workspace_slug, workspace_id)
                logger.info(f"[{workspace_slug}] {step_name} - completed")

            await self.complete_task(task_id, {
                "action": "create_workspace",
                "workspace_slug": workspace_slug,
                "workspace_id": workspace_id,
                "has_app": app_template_id is not None,
            })

            logger.info(f"Workspace {workspace_slug} provisioned successfully")

        except Exception as e:
            logger.error(f"Workspace provisioning failed: {e}")
            await self.fail_task(task_id, str(e))
            raise

    async def _workspace_validate(self, workspace_slug: str, workspace_id: str):
        """Validate workspace configuration"""
        if not workspace_slug or len(workspace_slug) < 3:
            raise ValueError("Invalid workspace slug")

    async def _workspace_create_team(self, workspace_slug: str, workspace_id: str):
        """Create the kanban team for this workspace"""
        # Reuse existing team provisioning logic
        payload = self._current_payload
        owner_id = payload.get("owner_id")
        owner_email = payload.get("owner_email")
        owner_name = payload.get("owner_name")

        # Create team directory and database
        await self._create_team_directory(workspace_slug, workspace_id)

        # Set up payload for database init
        self._current_payload = {
            "owner_id": owner_id,
            "owner_email": owner_email,
            "owner_name": owner_name,
        }
        await self._init_database(workspace_slug, workspace_id)

        # Restore original payload
        self._current_payload = payload

        # Start team containers
        await self._start_containers(workspace_slug, workspace_id)

        logger.info(f"[{workspace_slug}] Kanban team created")

    async def _workspace_create_default_boards(self, workspace_slug: str, workspace_id: str):
        """Create default boards from templates in the kanban team"""
        import httpx

        # Build kanban API URL
        if PORT == "443":
            kanban_api_url = f"https://{workspace_slug}.{DOMAIN}/api"
        else:
            kanban_api_url = f"https://{workspace_slug}.{DOMAIN}:{PORT}/api"

        logger.info(f"[{workspace_slug}] Creating default boards at {kanban_api_url}")

        # Default board templates to create (template_id, board_name, board_key, position)
        # board_key is used as prefix for card numbers (e.g., IDEA-1, FEAT-2, BUG-3)
        # position determines display order (lower = first)
        default_boards = [
            ("ideas-pipeline", "Ideas Pipeline", "IDEA", 0),
            ("feature-request", "Feature Request", "FEAT", 1),
            ("bug-tracking", "Bug Tracking", "BUG", 2),
        ]

        ideas_board_id = None

        # Headers for internal service authentication
        headers = {
            "X-Service-Secret": CROSS_DOMAIN_SECRET
        }

        # Wait for kanban API to be ready (containers just started)
        async with httpx.AsyncClient(timeout=30.0, verify=False, headers=headers) as client:
            # Health check with retries
            for attempt in range(10):
                try:
                    response = await client.get(f"{kanban_api_url}/health")
                    if response.status_code == 200:
                        logger.info(f"[{workspace_slug}] Kanban API is ready")
                        break
                except Exception:
                    pass
                await asyncio.sleep(2)
            else:
                logger.warning(f"[{workspace_slug}] Kanban API not responding, skipping board creation")
                return

            # Create boards from templates
            for template_id, board_name, board_key, position in default_boards:
                try:
                    response = await client.post(
                        f"{kanban_api_url}/templates/{template_id}/apply",
                        params={"board_name": board_name, "board_key": board_key, "position": position},
                    )

                    if response.status_code < 400:
                        board_data = response.json()
                        logger.info(f"[{workspace_slug}] Created board '{board_name}' (id: {board_data.get('id')})")

                        # Save Ideas Pipeline board ID for creating initial card
                        if template_id == "ideas-pipeline":
                            ideas_board_id = board_data.get("id")
                    else:
                        logger.warning(
                            f"[{workspace_slug}] Failed to create board '{board_name}': "
                            f"{response.status_code} - {response.text}"
                        )

                except Exception as e:
                    logger.warning(f"[{workspace_slug}] Error creating board '{board_name}': {e}")
                    # Continue with other boards even if one fails

            # Create initial card in Ideas Pipeline board
            if ideas_board_id:
                try:
                    # Get the board with columns (columns are included in the response)
                    board_response = await client.get(f"{kanban_api_url}/boards/{ideas_board_id}")
                    if board_response.status_code == 200:
                        board_data = board_response.json()
                        columns = board_data.get("columns", [])
                        if columns:
                            first_column_id = columns[0].get("id")

                            # Create the initial card via POST /cards
                            card_data = {
                                "column_id": first_column_id,
                                "title": "Welcome! Start here with your first idea",
                                "description": """## How to use the Ideas Pipeline

This board helps you explore and develop ideas from concept to implementation-ready.

### Getting Started

1. **Describe your idea** - Edit this card and explain what you want to build
2. **Be specific** - Include details about the problem you're solving and how
3. **Move to next step** - When ready, drag this card to the next column

### The AI agents will help you:
- **Idea Triage**: Analyze feasibility and potential
- **Product Owner**: Define requirements and user stories
- **UX Designer**: Create user flows and wireframes
- **Architect**: Design the technical solution

### Example idea format:

**Problem**: Users struggle to track their expenses across multiple accounts

**Solution**: A mobile app that automatically categorizes transactions and shows spending insights

**Target users**: Young professionals aged 25-40

---

*Delete this card once you understand the process, or edit it with your first real idea!*""",
                            }

                            card_response = await client.post(
                                f"{kanban_api_url}/cards",
                                json=card_data,
                            )

                            if card_response.status_code < 400:
                                logger.info(f"[{workspace_slug}] Created welcome card in Ideas Pipeline")
                            else:
                                logger.warning(f"[{workspace_slug}] Failed to create welcome card: {card_response.text}")

                except Exception as e:
                    logger.warning(f"[{workspace_slug}] Error creating welcome card: {e}")

        logger.info(f"[{workspace_slug}] Default boards created")

    async def _workspace_create_github_repo(self, workspace_slug: str, workspace_id: str):
        """Create GitHub repository from app template"""
        payload = self._current_payload
        github_org = payload.get("github_org", "hckmseduardo")
        template_owner = payload.get("template_owner", "hckmseduardo")
        template_repo = payload.get("template_repo", "basic-app")
        new_repo_name = f"{workspace_slug}-app"

        logger.info(f"[{workspace_slug}] Creating GitHub repo: {github_org}/{new_repo_name} from {template_owner}/{template_repo}")

        try:
            # First check if repo already exists (for retry scenarios)
            existing_repo = await github_service.get_repository(github_org, new_repo_name)
            if existing_repo:
                logger.info(f"[{workspace_slug}] Repository already exists, using existing: {existing_repo.get('html_url')}")
                self._current_payload["github_repo_url"] = existing_repo.get("html_url")
                self._current_payload["github_repo_name"] = new_repo_name
                self._current_payload["github_clone_url"] = existing_repo.get("clone_url")
                return  # Skip creation, repo already exists

            repo_data = await github_service.create_repo_from_template(
                template_owner=template_owner,
                template_repo=template_repo,
                new_owner=github_org,
                new_repo=new_repo_name,
                description=f"App for workspace {workspace_slug}",
                private=True,
            )

            # Store repo info in payload for later steps
            self._current_payload["github_repo_url"] = repo_data.get("html_url")
            self._current_payload["github_repo_name"] = new_repo_name
            self._current_payload["github_clone_url"] = repo_data.get("clone_url")

            logger.info(f"[{workspace_slug}] Repository created: {repo_data.get('html_url')}")

            # Wait for GitHub to finish generating the repository from template
            # Template generation is asynchronous, so we need to wait for it to have content
            logger.info(f"[{workspace_slug}] Waiting for repository generation to complete...")
            for attempt in range(30):  # Max 30 seconds
                await asyncio.sleep(1)
                repo_status = await github_service.get_repository(github_org, new_repo_name)
                if repo_status and repo_status.get("size", 0) > 0:
                    logger.info(f"[{workspace_slug}] Repository ready (size: {repo_status.get('size')} KB)")
                    break
            else:
                logger.warning(f"[{workspace_slug}] Repository may still be generating, proceeding anyway")

        except Exception as e:
            logger.error(f"[{workspace_slug}] Failed to create GitHub repository: {e}")
            raise

    async def _workspace_create_azure_app(self, workspace_slug: str, workspace_id: str):
        """Create Entra External ID (CIAM) app registration for the workspace app"""
        # Generate redirect URIs based on app subdomain
        base_domain = DOMAIN
        if base_domain.startswith("kanban."):
            base_domain = base_domain[7:]  # Remove kanban. prefix

        if PORT == "443":
            app_url = f"https://{workspace_slug}.app.{base_domain}"
        else:
            app_url = f"https://{workspace_slug}.app.{base_domain}:{PORT}"

        redirect_uris = [
            f"{app_url}/api/auth/callback",
        ]

        display_name = f"Workspace {workspace_slug} App"

        logger.info(f"[{workspace_slug}] Creating Entra External ID app registration: {display_name}")

        try:
            result = await azure_service.create_app_registration(
                display_name=display_name,
                redirect_uris=redirect_uris,
                homepage_url=app_url,
            )

            # Store Entra CIAM credentials in payload for later steps
            # Use entra_* naming to match template expectations
            self._current_payload["entra_tenant_id"] = result.tenant_id
            self._current_payload["entra_authority"] = result.authority
            self._current_payload["entra_client_id"] = result.app_id
            self._current_payload["entra_client_secret"] = result.client_secret
            self._current_payload["entra_object_id"] = result.object_id

            # Also keep azure_* for backwards compatibility with status updates
            self._current_payload["azure_app_id"] = result.app_id
            self._current_payload["azure_object_id"] = result.object_id
            self._current_payload["azure_client_secret"] = result.client_secret
            self._current_payload["azure_tenant_id"] = result.tenant_id

            logger.info(f"[{workspace_slug}] Entra External ID app created: {result.app_id} (authority: {result.authority})")

        except Exception as e:
            logger.error(f"[{workspace_slug}] Failed to create Entra External ID app registration: {e}")
            raise

    async def _workspace_clone_repo(self, workspace_slug: str, workspace_id: str):
        """Clone the workspace's GitHub repository"""
        payload = self._current_payload
        github_org = payload.get("github_org", "hckmseduardo")
        github_repo = payload.get("github_repo_name", f"{workspace_slug}-app")
        github_pat = payload.get("github_pat")  # Optional custom PAT

        # Use workspaces directory for app code
        workspace_dir = WORKSPACES_DIR / workspace_slug / "app"
        workspace_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[{workspace_slug}] Cloning repository to {workspace_dir}")

        try:
            # Get authenticated clone URL (use custom PAT if provided)
            clone_url = await github_service.clone_repository_url(
                owner=github_org,
                repo=github_repo,
                use_ssh=False,  # Use HTTPS with token
                token=github_pat,
            )

            # Clone the repository
            result = subprocess.run(
                ["git", "clone", clone_url, str(workspace_dir)],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                # If directory already exists and has content, try pull instead
                if "already exists" in result.stderr:
                    logger.info(f"[{workspace_slug}] Directory exists, pulling latest...")
                    result = subprocess.run(
                        ["git", "-C", str(workspace_dir), "pull"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                else:
                    raise RuntimeError(f"Git clone failed: {result.stderr}")

            logger.info(f"[{workspace_slug}] Repository cloned successfully")

        except Exception as e:
            logger.error(f"[{workspace_slug}] Failed to clone repository: {e}")
            raise

    async def _workspace_issue_certificate(self, workspace_slug: str, workspace_id: str):
        """Issue SSL certificate for workspace app subdomain"""
        logger.info(f"[{workspace_slug}] Issuing SSL certificate for app subdomain")

        try:
            cert_info = await certificate_service.issue_workspace_certificate(workspace_slug)
            self._current_payload["cert_info"] = cert_info
            logger.info(f"[{workspace_slug}] SSL certificate issued: {cert_info.get('domain', 'unknown')}")
        except Exception as e:
            logger.warning(f"[{workspace_slug}] Certificate issuance failed (non-fatal): {e}")
            # Continue without certificate - Traefik may handle it

    async def _workspace_create_database(self, workspace_slug: str, workspace_id: str):
        """Create PostgreSQL database for the app - handled by docker compose"""
        db_name = workspace_slug.replace("-", "_") + "_app"
        logger.info(f"[{workspace_slug}] Database {db_name} will be created by PostgreSQL container")
        # The database is created automatically when the postgres container starts
        # with POSTGRES_DB environment variable

    async def _workspace_deploy_app(self, workspace_slug: str, workspace_id: str):
        """Deploy app containers using the workspace-app-compose template or Claude-generated config"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        payload = self._current_payload
        database_name = workspace_slug.replace("-", "_") + "_app"

        logger.info(f"[{workspace_slug}] Deploying app containers")

        # Paths
        workspace_data_path = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}"
        app_source_path = f"{workspace_data_path}/app"

        # Check if Claude generated a docker-compose.yml (for existing repo mode)
        claude_compose_path = Path(f"/app/data/workspaces/{workspace_slug}/app/docker-compose.yml")
        claude_compose_host = f"{app_source_path}/docker-compose.yml"

        if payload.get("claude_configured") and claude_compose_path.exists():
            # Use Claude-generated compose file
            compose_file_host = claude_compose_host
            logger.info(f"[{workspace_slug}] Using Claude-generated docker-compose.yml")
        else:
            # Use template-based compose (for template mode)
            # Generate secrets
            postgres_password = secrets.token_hex(16)
            app_secret_key = secrets.token_hex(32)

            # Store secrets in payload
            self._current_payload["postgres_password"] = postgres_password
            self._current_payload["app_secret_key"] = app_secret_key

            # Render workspace app compose template
            try:
                template = self.app_factory_jinja.get_template("workspace-app-compose.yml.j2")
                compose_content = template.render(
                    workspace_slug=workspace_slug,
                    app_template_slug=payload.get("app_template_slug", "basic-app"),
                    database_name=database_name,
                    postgres_password=postgres_password,
                    app_secret_key=app_secret_key,
                    data_path=workspace_data_path,
                    app_source_path=app_source_path,
                    domain=DOMAIN,
                    port=PORT,
                    network_name=NETWORK_NAME,
                    # Entra External ID (CIAM) credentials
                    entra_tenant_id=payload.get("entra_tenant_id", ""),
                    entra_authority=payload.get("entra_authority", ""),
                    entra_client_id=payload.get("entra_client_id", ""),
                    entra_client_secret=payload.get("entra_client_secret", ""),
                )
            except Exception as e:
                logger.error(f"[{workspace_slug}] Failed to render workspace app template: {e}")
                raise

            # Write compose file to persistent location in workspace directory
            # Using HOST_PROJECT_PATH for the compose file since docker compose uses host paths
            compose_file_host = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/docker-compose.app.yml"
            compose_file = Path(f"/app/data/workspaces/{workspace_slug}/docker-compose.app.yml")

            # Ensure workspace directory exists
            compose_file.parent.mkdir(parents=True, exist_ok=True)
            compose_file.write_text(compose_content)
            logger.info(f"[{workspace_slug}] Saved compose file to {compose_file_host}")

        project_name = f"{workspace_slug}-app"

        try:
            # Create workspace data directory
            Path(workspace_data_path).mkdir(parents=True, exist_ok=True)

            # Stop and remove existing stack if it exists
            subprocess.run(
                ["docker", "compose", "-f", compose_file_host, "-p", project_name, "down", "--remove-orphans"],
                capture_output=True,
                text=True,
                check=False
            )

            # Clean up postgres data on the HOST to prevent password mismatch issues
            # We use docker run with alpine to access the host path directly, avoiding
            # mount propagation issues where the orchestrator can't see directories
            # created by other containers
            postgres_host_path = f"{workspace_data_path}/postgres"
            cleanup_result = subprocess.run(
                [
                    "docker", "run", "--rm",
                    "-v", f"{workspace_data_path}:{workspace_data_path}",
                    "alpine:latest",
                    "sh", "-c", f"rm -rf {postgres_host_path} && echo 'Postgres data cleaned'"
                ],
                capture_output=True,
                text=True,
                check=False
            )
            if cleanup_result.returncode == 0 and "cleaned" in cleanup_result.stdout:
                logger.info(f"[{workspace_slug}] Cleaned up existing postgres data on host")

            # Build and start the stack
            logger.info(f"[{workspace_slug}] Building and starting app containers...")
            result = subprocess.run(
                ["docker", "compose", "-f", compose_file_host, "-p", project_name, "up", "-d", "--build"],
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode != 0:
                logger.error(f"[{workspace_slug}] Docker compose stderr: {result.stderr}")
                logger.error(f"[{workspace_slug}] Docker compose stdout: {result.stdout}")
                raise RuntimeError(f"Failed to build/start app containers: {result.stderr}")

            logger.info(f"[{workspace_slug}] App containers deployed")

        except Exception as e:
            logger.error(f"[{workspace_slug}] App deployment failed: {e}")
            raise

    async def _workspace_create_foundation_sandbox(self, workspace_slug: str, workspace_id: str):
        """Create a foundation sandbox for the workspace via portal API"""
        import httpx

        sandbox_slug = "foundation"
        full_slug = f"{workspace_slug}-{sandbox_slug}"

        logger.info(f"[{workspace_slug}] Creating foundation sandbox: {full_slug}")

        # Call portal API to create sandbox (this queues the provisioning task)
        portal_api_url = "http://kanban-portal-api:8000"
        headers = {
            "X-Service-Secret": CROSS_DOMAIN_SECRET,
            "Content-Type": "application/json"
        }

        sandbox_request = {
            "slug": sandbox_slug,
            "name": "Foundation",
            "description": "Main development sandbox",
            "source_branch": "main"
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{portal_api_url}/workspaces/{workspace_slug}/sandboxes",
                    json=sandbox_request,
                    headers=headers
                )

                if response.status_code < 400:
                    sandbox_data = response.json()
                    logger.info(f"[{workspace_slug}] Created foundation sandbox via portal API: {sandbox_data.get('id')}")
                else:
                    logger.warning(
                        f"[{workspace_slug}] Failed to create foundation sandbox: "
                        f"{response.status_code} - {response.text}"
                    )

        except Exception as e:
            logger.warning(f"[{workspace_slug}] Failed to create foundation sandbox (non-fatal): {e}")
            # Don't fail workspace provisioning if sandbox creation fails

    async def _workspace_health_check(self, workspace_slug: str, workspace_id: str):
        """Health check for workspace components"""
        # Check kanban team containers
        await self._health_check(workspace_slug, workspace_id)
        # TODO: Also check app containers if deployed

    async def _workspace_finalize(self, workspace_slug: str, workspace_id: str):
        """Finalize workspace setup"""
        # The kanban team uses the same ID as the workspace for simplicity
        # In the future, teams could have separate IDs
        kanban_team_id = workspace_id

        # Debug: log current payload keys
        logger.info(f"[{workspace_slug}] Finalize payload keys: {list(self._current_payload.keys())}")

        # Publish workspace status update with team_id and GitHub info
        status_payload = {
            "workspace_id": workspace_id,
            "workspace_slug": workspace_slug,
            "kanban_team_id": kanban_team_id,
            "owner_id": self._current_payload.get("owner_id"),
            "status": "active"
        }

        # Include GitHub repo info if present (for app workspaces)
        if self._current_payload.get("github_repo_name"):
            status_payload["github_repo_name"] = self._current_payload["github_repo_name"]
        if self._current_payload.get("github_repo_url"):
            status_payload["github_repo_url"] = self._current_payload["github_repo_url"]

        # Include Azure AD credentials if present (for app workspaces)
        if self._current_payload.get("azure_app_id"):
            logger.info(f"[{workspace_slug}] Including Azure credentials in status")
            status_payload["azure_app_id"] = self._current_payload["azure_app_id"]
            status_payload["azure_object_id"] = self._current_payload["azure_object_id"]
            # Note: client_secret is stored but not exposed in API responses
            status_payload["azure_client_secret"] = self._current_payload["azure_client_secret"]
            status_payload["azure_tenant_id"] = self._current_payload["azure_tenant_id"]
        else:
            logger.warning(f"[{workspace_slug}] No azure_app_id in payload")

        await self.redis.publish("workspace:status", json.dumps(status_payload))
        await asyncio.sleep(0.5)

    async def restart_workspace(self, task: dict):
        """Restart/rebuild workspace containers (kanban + app)"""
        task_id = task["task_id"]
        payload = task["payload"]
        workspace_id = payload["workspace_id"]
        workspace_slug = payload["workspace_slug"]
        rebuild = payload.get("rebuild", False)
        restart_app = payload.get("restart_app", True)

        logger.info(f"Restarting workspace: {workspace_slug} (rebuild={rebuild}, restart_app={restart_app})")

        # Store payload for step functions
        self._current_payload = payload

        # Build steps list based on options
        steps = []

        if rebuild:
            steps.extend([
                ("Stopping kanban containers", self._workspace_restart_stop_kanban),
                ("Rebuilding kanban containers", self._workspace_restart_rebuild_kanban),
                ("Starting kanban containers", self._workspace_restart_start_kanban),
            ])
        else:
            steps.extend([
                ("Stopping kanban containers", self._workspace_restart_stop_kanban),
                ("Starting kanban containers", self._workspace_restart_start_kanban),
            ])

        if restart_app:
            app_compose = Path(f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/docker-compose.app.yml")
            if app_compose.exists():
                if rebuild:
                    steps.extend([
                        ("Stopping app containers", self._workspace_restart_stop_app),
                        ("Rebuilding app containers", self._workspace_restart_rebuild_app),
                    ])
                else:
                    steps.extend([
                        ("Restarting app containers", self._workspace_restart_app),
                    ])

            # Also rebuild sandboxes if restart_app is enabled
            sandboxes = self._get_workspace_sandboxes(workspace_slug)
            if sandboxes:
                if rebuild:
                    steps.append(("Rebuilding sandbox containers", self._workspace_start_rebuild_sandboxes))
                else:
                    steps.append(("Restarting sandbox containers", self._workspace_restart_sandboxes))

        steps.append(("Running health check", self._workspace_health_check))

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(workspace_slug, workspace_id)
                logger.info(f"[{workspace_slug}] {step_name} - completed")

            # Publish status update
            await self.redis.publish("workspace:status", json.dumps({
                "workspace_id": workspace_id,
                "workspace_slug": workspace_slug,
                "status": "active"
            }))

            await self.complete_task(task_id, {
                "action": "restart_workspace",
                "workspace_slug": workspace_slug,
                "rebuild": rebuild,
                "url": f"https://{workspace_slug}.{DOMAIN}"
            })

            logger.info(f"Workspace {workspace_slug} restarted successfully")

        except Exception as e:
            logger.error(f"Workspace restart failed: {e}")
            await self.fail_task(task_id, str(e))
            raise

    async def start_workspace(self, task: dict):
        """Start/rebuild workspace components (kanban, and optionally app/sandboxes)"""
        task_id = task["task_id"]
        payload = task["payload"]
        workspace_id = payload["workspace_id"]
        workspace_slug = payload["workspace_slug"]
        kanban_only = payload.get("kanban_only", False)

        if kanban_only:
            logger.info(f"Starting workspace kanban only: {workspace_slug}")
        else:
            logger.info(f"Starting workspace: {workspace_slug}")

        # Store payload for step functions
        self._current_payload = payload

        # Build steps list - always rebuild for fresh start
        steps = [
            ("Validating workspace", self._workspace_start_validate),
            ("Rebuilding kanban containers", self._workspace_start_rebuild_kanban),
        ]

        # Only include app/sandbox steps if not kanban_only mode
        if not kanban_only:
            # Check if app exists (handle both new and legacy template structures)
            app_compose = Path(f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/docker-compose.app.yml")
            legacy_app_compose = Path(f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/app/docker-compose.yml")
            if app_compose.exists() or legacy_app_compose.exists():
                steps.append(("Rebuilding app containers", self._workspace_start_rebuild_app))

            # Get sandboxes for this workspace
            sandboxes = self._get_workspace_sandboxes(workspace_slug)
            if sandboxes:
                steps.append(("Rebuilding sandbox containers", self._workspace_start_rebuild_sandboxes))

        steps.append(("Running health check", self._workspace_health_check))

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(workspace_slug, workspace_id)
                logger.info(f"[{workspace_slug}] {step_name} - completed")

            # Publish status update
            await self.redis.publish("workspace:status", json.dumps({
                "workspace_id": workspace_id,
                "workspace_slug": workspace_slug,
                "status": "active"
            }))

            await self.complete_task(task_id, {
                "action": "start_workspace",
                "workspace_slug": workspace_slug,
                "url": f"https://{workspace_slug}.{DOMAIN}"
            })

            logger.info(f"Workspace {workspace_slug} started successfully")

        except Exception as e:
            logger.error(f"Workspace start failed: {e}")
            await self.fail_task(task_id, str(e))
            raise

    def _get_workspace_sandboxes(self, workspace_slug: str) -> list[str]:
        """Get list of sandbox full_slugs for a workspace"""
        sandboxes_dir = Path(f"{HOST_PROJECT_PATH}/data/sandboxes")
        if not sandboxes_dir.exists():
            return []

        sandboxes = []
        for sandbox_dir in sandboxes_dir.iterdir():
            if sandbox_dir.is_dir() and sandbox_dir.name.startswith(f"{workspace_slug}-"):
                # Check if compose file exists (indicates valid sandbox)
                compose_file = sandbox_dir / "docker-compose.app.yml"
                if compose_file.exists():
                    sandboxes.append(sandbox_dir.name)

        return sandboxes

    async def _workspace_start_validate(self, workspace_slug: str, workspace_id: str):
        """Validate workspace exists and can be started"""
        workspace_dir = Path(f"/app/data/workspaces/{workspace_slug}")
        if not workspace_dir.exists():
            raise RuntimeError(f"Workspace directory not found: {workspace_dir}")
        logger.info(f"[{workspace_slug}] Workspace validated")

    async def _workspace_start_rebuild_kanban(self, workspace_slug: str, workspace_id: str):
        """Rebuild and start kanban containers"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        project_name = f"{workspace_slug}-kanban"
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")
        # Use data/teams/ to match provisioning (kanban data lives in teams, not workspaces)
        workspace_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{workspace_slug}"

        # Get cross-domain secret from Key Vault (production) or environment (development)
        cross_domain_secret = keyvault_service.get_cross_domain_secret()

        env = os.environ.copy()
        env.update({
            "TEAM_SLUG": workspace_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": workspace_data_host_path,
            "CROSS_DOMAIN_SECRET": cross_domain_secret,
        })

        # Build and start containers
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "up", "-d", "--build", "api", "web"],
            capture_output=True,
            text=True,
            env=env,
            check=False
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to start kanban containers: {result.stderr}")

        logger.info(f"[{workspace_slug}] Kanban containers rebuilt and started")

    async def _workspace_start_rebuild_app(self, workspace_slug: str, workspace_id: str):
        """Rebuild and start app containers (handles both new and legacy template structures)"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        # Check for new structure first, then legacy
        compose_file = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/docker-compose.app.yml"
        legacy_compose_file = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/app/docker-compose.yml"
        is_legacy = False

        if not Path(compose_file).exists():
            if Path(legacy_compose_file).exists():
                compose_file = legacy_compose_file
                is_legacy = True
            else:
                logger.warning(f"[{workspace_slug}] No app compose file found, skipping")
                return

        project_name = f"{workspace_slug}-app"

        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "up", "-d", "--build"],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            logger.warning(f"[{workspace_slug}] App containers failed to start: {result.stderr}")
            return

        logger.info(f"[{workspace_slug}] App containers rebuilt and started")

        # For legacy apps, connect key containers to kanban-global network for Traefik routing
        if is_legacy:
            await self._connect_legacy_app_to_network(workspace_slug)

    async def _connect_legacy_app_to_network(self, workspace_slug: str):
        """Connect legacy app containers to kanban-global network for Traefik routing"""
        containers_to_connect = [
            f"{workspace_slug}-app-frontend",
            f"{workspace_slug}-app-backend",
        ]

        for container in containers_to_connect:
            result = subprocess.run(
                ["docker", "network", "connect", NETWORK_NAME, container],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                logger.info(f"[{workspace_slug}] Connected {container} to {NETWORK_NAME}")
            elif "already exists" in result.stderr.lower():
                logger.debug(f"[{workspace_slug}] {container} already connected to {NETWORK_NAME}")
            else:
                logger.warning(f"[{workspace_slug}] Failed to connect {container} to {NETWORK_NAME}: {result.stderr}")

    async def _workspace_start_rebuild_sandboxes(self, workspace_slug: str, workspace_id: str):
        """Rebuild and start all sandbox containers for this workspace"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        sandboxes = self._get_workspace_sandboxes(workspace_slug)
        for full_slug in sandboxes:
            compose_file = f"{HOST_PROJECT_PATH}/data/sandboxes/{full_slug}/docker-compose.app.yml"
            project_name = f"{full_slug}-app"

            result = subprocess.run(
                ["docker", "compose", "-f", compose_file, "-p", project_name, "up", "-d", "--build"],
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode != 0:
                logger.warning(f"[{full_slug}] Sandbox containers failed to start: {result.stderr}")
            else:
                logger.info(f"[{full_slug}] Sandbox containers rebuilt and started")

    async def _workspace_restart_stop_kanban(self, workspace_slug: str, workspace_id: str):
        """Stop workspace kanban containers"""
        if not self.docker_available:
            return

        project_name = f"{workspace_slug}-kanban"
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")
        # Use data/teams/ to match provisioning (kanban data lives in teams, not workspaces)
        workspace_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{workspace_slug}"

        env = os.environ.copy()
        env.update({
            "TEAM_SLUG": workspace_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": workspace_data_host_path,
        })

        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "stop"],
            capture_output=True,
            text=True,
            env=env,
            check=False
        )

        if result.returncode == 0:
            logger.info(f"[{workspace_slug}] Kanban containers stopped")
        else:
            logger.warning(f"[{workspace_slug}] Stop warning: {result.stderr}")

    async def _workspace_restart_rebuild_kanban(self, workspace_slug: str, workspace_id: str):
        """Rebuild workspace kanban containers"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        project_name = f"{workspace_slug}-kanban"
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")
        # Use data/teams/ to match provisioning (kanban data lives in teams, not workspaces)
        workspace_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{workspace_slug}"

        # Get cross-domain secret from Key Vault (production) or environment (development)
        cross_domain_secret = keyvault_service.get_cross_domain_secret()

        env = os.environ.copy()
        env.update({
            "TEAM_SLUG": workspace_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": workspace_data_host_path,
            "CROSS_DOMAIN_SECRET": cross_domain_secret,
        })

        # Remove containers and rebuild
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "down", "--rmi", "local"],
            capture_output=True,
            text=True,
            env=env,
            check=False
        )

        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "build", "--no-cache"],
            capture_output=True,
            text=True,
            env=env,
            check=False
        )

        if result.returncode != 0:
            logger.warning(f"[{workspace_slug}] Rebuild warning: {result.stderr}")

        logger.info(f"[{workspace_slug}] Kanban containers rebuilt")

    async def _workspace_restart_start_kanban(self, workspace_slug: str, workspace_id: str):
        """Start workspace kanban containers"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        project_name = f"{workspace_slug}-kanban"
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")
        # Use data/teams/ to match provisioning (kanban data lives in teams, not workspaces)
        workspace_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{workspace_slug}"

        # Get cross-domain secret from Key Vault (production) or environment (development)
        cross_domain_secret = keyvault_service.get_cross_domain_secret()

        env = os.environ.copy()
        env.update({
            "TEAM_SLUG": workspace_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": workspace_data_host_path,
            "CROSS_DOMAIN_SECRET": cross_domain_secret,
        })

        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "up", "-d", "api", "web"],
            capture_output=True,
            text=True,
            env=env,
            check=False
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to start kanban containers: {result.stderr}")

        logger.info(f"[{workspace_slug}] Kanban containers started")

    async def _workspace_restart_stop_app(self, workspace_slug: str, workspace_id: str):
        """Stop workspace app containers"""
        if not self.docker_available:
            return

        compose_file = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/docker-compose.app.yml"
        project_name = f"{workspace_slug}-app"

        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "stop"],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode == 0:
            logger.info(f"[{workspace_slug}] App containers stopped")
        else:
            logger.warning(f"[{workspace_slug}] App stop warning: {result.stderr}")

    async def _workspace_restart_rebuild_app(self, workspace_slug: str, workspace_id: str):
        """Rebuild and start workspace app containers"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        compose_file = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/docker-compose.app.yml"
        project_name = f"{workspace_slug}-app"

        # Down with image removal, then rebuild
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "down", "--rmi", "local"],
            capture_output=True,
            text=True,
            check=False
        )

        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "up", "-d", "--build"],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            logger.warning(f"[{workspace_slug}] App rebuild warning: {result.stderr}")

        logger.info(f"[{workspace_slug}] App containers rebuilt and started")

    async def _workspace_restart_app(self, workspace_slug: str, workspace_id: str):
        """Restart workspace app containers (no rebuild)"""
        if not self.docker_available:
            return

        compose_file = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/docker-compose.app.yml"
        project_name = f"{workspace_slug}-app"

        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "restart"],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode == 0:
            logger.info(f"[{workspace_slug}] App containers restarted")
        else:
            logger.warning(f"[{workspace_slug}] App restart warning: {result.stderr}")

    async def _workspace_restart_sandboxes(self, workspace_slug: str, workspace_id: str):
        """Restart all sandbox containers for this workspace (no rebuild)"""
        if not self.docker_available:
            return

        sandboxes = self._get_workspace_sandboxes(workspace_slug)
        for full_slug in sandboxes:
            compose_file = f"{HOST_PROJECT_PATH}/data/sandboxes/{full_slug}/docker-compose.app.yml"
            project_name = full_slug

            result = subprocess.run(
                ["docker", "compose", "-f", compose_file, "-p", project_name, "restart"],
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode == 0:
                logger.info(f"[{full_slug}] Sandbox containers restarted")
            else:
                logger.warning(f"[{full_slug}] Sandbox restart warning: {result.stderr}")

    # =========================================================================
    # Link/Unlink App Handlers
    # =========================================================================

    async def link_app_to_workspace(self, task: dict):
        """Link an app to an existing kanban-only workspace"""
        task_id = task["task_id"]
        payload = task["payload"]
        workspace_id = payload["workspace_id"]
        workspace_slug = payload["workspace_slug"]
        app_template_id = payload.get("app_template_id")

        self._current_payload = payload

        logger.info(f"Linking app to workspace: {workspace_slug} (template: {app_template_id or 'existing-repo'})")

        # Build steps based on mode (template vs existing repo)
        steps = []

        if app_template_id:
            # From template mode - create new repo with known structure
            steps.append(("Creating GitHub repository", self._workspace_create_github_repo))
            steps.extend([
                ("Creating Azure app registration", self._workspace_create_azure_app),
                ("Cloning repository", self._workspace_clone_repo),
                ("Issuing SSL certificate", self._workspace_issue_certificate),
                ("Creating app database", self._workspace_create_database),
                ("Deploying app containers", self._workspace_deploy_app),
            ])
        else:
            # Existing repo mode - use Claude CLI to configure the app
            steps.extend([
                ("Validating GitHub repository", self._link_app_validate_existing_repo),
                ("Creating Azure app registration", self._workspace_create_azure_app),
                ("Cloning repository", self._workspace_clone_repo),
                ("Configuring app with Claude", self._link_app_configure_with_claude),
                ("Issuing SSL certificate", self._workspace_issue_certificate),
                # Skip "Creating app database" - Claude handles db in docker-compose if needed
                ("Deploying app containers", self._workspace_deploy_app),
            ])

        # Common steps for both modes
        steps.extend([
            # Update workspace with app fields BEFORE sandbox creation
            # (portal API requires app_template_id to be set for sandbox creation)
            ("Updating workspace", self._link_app_update_workspace),
            ("Creating foundation sandbox", self._workspace_create_foundation_sandbox),
            ("Running health check", self._workspace_health_check),
            ("Finalizing", self._link_app_finalize),
        ])

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(workspace_slug, workspace_id)
                logger.info(f"[{workspace_slug}] {step_name} - completed")

            await self.complete_task(task_id, {
                "action": "link_app",
                "workspace_slug": workspace_slug,
                "workspace_id": workspace_id,
            })

            logger.info(f"App linked to workspace {workspace_slug} successfully")

        except Exception as e:
            logger.error(f"Link app failed: {e}")
            # Revert workspace status to active on failure
            await self.redis.publish("workspace:status", json.dumps({
                "workspace_id": workspace_id,
                "workspace_slug": workspace_slug,
                "status": "active"
            }))
            await self.fail_task(task_id, str(e))
            raise

    async def _link_app_validate_existing_repo(self, workspace_slug: str, workspace_id: str):
        """Validate and prepare existing GitHub repository"""
        import re

        payload = self._current_payload
        github_repo_url = payload.get("github_repo_url")
        github_pat = payload.get("github_pat")  # Optional custom PAT

        # Parse org and repo from URL
        match = re.match(r"https://github\.com/([\w-]+)/([\w.-]+)", github_repo_url)
        if not match:
            raise ValueError(f"Invalid GitHub URL: {github_repo_url}")

        github_org = match.group(1)
        github_repo_name = match.group(2)

        # Verify repo exists and is accessible (use custom PAT if provided)
        repo_data = await github_service.get_repository(
            github_org, github_repo_name, token=github_pat
        )
        if not repo_data:
            raise ValueError(f"Repository not found or not accessible: {github_repo_url}")

        # Store for later steps
        self._current_payload["github_org"] = github_org
        self._current_payload["github_repo_name"] = github_repo_name
        self._current_payload["github_repo_url"] = repo_data.get("html_url")
        # Keep github_pat in payload for cloning and workspace storage

        logger.info(f"[{workspace_slug}] Validated existing repo: {github_repo_url}")

    async def _link_app_configure_with_claude(self, workspace_slug: str, workspace_id: str):
        """Configure existing repository using Claude CLI before deployment.

        This step analyzes the repository structure and generates appropriate
        Docker configuration (Dockerfile, docker-compose.yml) so the app can
        run on a single port behind the workspace app domain.
        """
        payload = self._current_payload

        # Only run for existing repo mode (no template)
        if payload.get("app_template_id"):
            logger.info(f"[{workspace_slug}] Skipping Claude config - using template")
            return

        app_source_path = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/app"
        base_domain = DOMAIN.replace("kanban.", "")
        app_domain = f"{workspace_slug}.app.{base_domain}"

        prompt = f"""Analyze this repository and configure it to run as a Docker application.

Requirements:
1. The app must expose a SINGLE port (8000) for HTTP traffic
2. Create a docker-compose.yml in the root with:
   - Service name: {workspace_slug}-app
   - Container name: {workspace_slug}-app
   - Build context: . (current directory)
   - Expose port 8000 internally (do NOT expose to host)
   - Network: {workspace_slug}-network (external: false) AND {NETWORK_NAME} (external: true)
   - Traefik labels for HTTPS routing:
     - traefik.enable=true
     - traefik.http.routers.{workspace_slug}-app.rule=Host(`{app_domain}`)
     - traefik.http.routers.{workspace_slug}-app.entrypoints=websecure
     - traefik.http.routers.{workspace_slug}-app.tls=true
     - traefik.http.services.{workspace_slug}-app.loadbalancer.server.port=8000
   - Restart policy: unless-stopped
3. Create or modify Dockerfile to:
   - Build the application for production
   - Expose port 8000
   - Set appropriate CMD/ENTRYPOINT
4. If the app needs environment variables, use environment section in docker-compose

The app will be accessible at: https://{app_domain}

Important:
- Keep it minimal - only add services the app actually needs
- Analyze the codebase to determine if postgres/redis are needed:
  - Look for database connection strings, ORM usage, SQL files
  - If database is needed, add a postgres service on the internal network
  - If not needed, omit it entirely
- Use multi-stage builds for smaller images where appropriate
- The external Traefik network is: {NETWORK_NAME}
- Make sure the docker-compose.yml networks section includes both:
  - {workspace_slug}-network (internal, for inter-service communication)
  - {NETWORK_NAME} (external: true, for Traefik routing)

Generate the configuration files now."""

        logger.info(f"[{workspace_slug}] Configuring app with Claude CLI...")

        result = await claude_runner.run(
            prompt=prompt,
            working_dir=app_source_path,
            tool_profile="developer",
            timeout=600,  # 10 minutes
        )

        if not result.success:
            raise RuntimeError(f"Claude configuration failed: {result.error}")

        # Verify docker-compose.yml was created
        compose_path = Path(app_source_path) / "docker-compose.yml"
        if not compose_path.exists():
            raise RuntimeError("Claude did not generate docker-compose.yml")

        # Mark that we're using Claude-generated config
        self._current_payload["claude_configured"] = True

        logger.info(f"[{workspace_slug}] App configured successfully by Claude")

    async def _link_app_update_workspace(self, workspace_slug: str, workspace_id: str):
        """Update workspace with app fields (before sandbox creation)

        This must run BEFORE sandbox creation because the portal API
        requires app_template_id to be set for sandbox operations.
        """
        payload = self._current_payload

        # Calculate app subdomain (strips kanban. prefix from domain)
        base_domain = DOMAIN.replace("kanban.", "")
        app_subdomain = f"https://{workspace_slug}.app.{base_domain}"

        # Build update payload with app fields (but keep linking_app status)
        update_payload = {
            "workspace_id": workspace_id,
            "workspace_slug": workspace_slug,
            "app_template_id": payload.get("app_template_id"),
            "app_subdomain": app_subdomain,
        }

        # Include GitHub repo info
        if payload.get("github_repo_name"):
            update_payload["github_repo_name"] = payload["github_repo_name"]
        if payload.get("github_repo_url"):
            update_payload["github_repo_url"] = payload["github_repo_url"]
        if payload.get("github_org"):
            update_payload["github_org"] = payload["github_org"]
        if payload.get("github_pat"):
            update_payload["github_pat"] = payload["github_pat"]  # Custom PAT for this repo

        # Include Azure AD credentials
        if payload.get("azure_app_id"):
            update_payload["azure_app_id"] = payload["azure_app_id"]
            update_payload["azure_object_id"] = payload["azure_object_id"]
            update_payload["azure_client_secret"] = payload["azure_client_secret"]
            update_payload["azure_tenant_id"] = payload["azure_tenant_id"]

        await self.redis.publish("workspace:status", json.dumps(update_payload))
        await asyncio.sleep(0.5)

        logger.info(f"[{workspace_slug}] Workspace updated with app fields (subdomain: {app_subdomain})")

    async def _link_app_finalize(self, workspace_slug: str, workspace_id: str):
        """Finalize link app - set status to active"""
        await self.redis.publish("workspace:status", json.dumps({
            "workspace_id": workspace_id,
            "workspace_slug": workspace_slug,
            "status": "active",
        }))
        await asyncio.sleep(0.5)

        logger.info(f"[{workspace_slug}] App link finalized")

    async def unlink_app_from_workspace(self, task: dict):
        """Unlink app from workspace, keeping kanban team intact"""
        task_id = task["task_id"]
        payload = task["payload"]
        workspace_id = payload["workspace_id"]
        workspace_slug = payload["workspace_slug"]
        delete_github_repo = payload.get("delete_github_repo", False)

        self._current_payload = payload

        logger.info(f"Unlinking app from workspace: {workspace_slug} (delete_repo={delete_github_repo})")

        steps = [
            ("Deleting sandboxes", self._unlink_app_delete_sandboxes),
            ("Stopping app containers", self._workspace_stop_app),
            ("Removing app containers", self._unlink_app_remove_containers),
            ("Deleting Azure app registration", self._workspace_delete_azure_app),
        ]

        if delete_github_repo:
            steps.append(("Deleting GitHub repository", self._workspace_delete_github_repo))

        steps.extend([
            ("Cleaning up app data", self._unlink_app_cleanup_data),
            ("Finalizing", self._unlink_app_finalize),
        ])

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(workspace_slug, workspace_id)
                logger.info(f"[{workspace_slug}] {step_name} - completed")

            await self.complete_task(task_id, {
                "action": "unlink_app",
                "workspace_slug": workspace_slug,
                "workspace_id": workspace_id,
            })

            logger.info(f"App unlinked from workspace {workspace_slug} successfully")

        except Exception as e:
            logger.error(f"Unlink app failed: {e}")
            # Revert workspace status to active on failure
            await self.redis.publish("workspace:status", json.dumps({
                "workspace_id": workspace_id,
                "workspace_slug": workspace_slug,
                "status": "active"
            }))
            await self.fail_task(task_id, str(e))
            raise

    async def _unlink_app_delete_sandboxes(self, workspace_slug: str, workspace_id: str):
        """Delete all sandboxes associated with the app"""
        sandboxes = self._get_workspace_sandboxes(workspace_slug)

        if not sandboxes:
            logger.info(f"[{workspace_slug}] No sandboxes to delete")
            return

        logger.info(f"[{workspace_slug}] Deleting {len(sandboxes)} sandbox(es)")

        for full_slug in sandboxes:
            try:
                # Use full_slug as sandbox_id for cleanup functions
                sandbox_id = full_slug
                await self._sandbox_stop_containers(full_slug, sandbox_id)
                await self._sandbox_remove_containers(full_slug, sandbox_id)
                await self._sandbox_delete_branch(full_slug, sandbox_id)
                await self._sandbox_archive_data(full_slug, sandbox_id)

                # Publish sandbox deleted status
                await self.redis.publish("sandbox:status", json.dumps({
                    "sandbox_id": sandbox_id,
                    "full_slug": full_slug,
                    "status": "deleted"
                }))

                logger.info(f"[{workspace_slug}] Sandbox {full_slug} deleted")
            except Exception as e:
                logger.error(f"[{workspace_slug}] Error deleting sandbox {full_slug}: {e}")
                # Continue with other sandboxes

    async def _unlink_app_remove_containers(self, workspace_slug: str, workspace_id: str):
        """Remove app containers and volumes"""
        if not self.docker_available:
            return

        # Check both new and legacy compose file locations
        compose_file = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/docker-compose.app.yml"
        legacy_compose_file = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/app/docker-compose.yml"

        compose_path = None
        if Path(compose_file).exists():
            compose_path = compose_file
        elif Path(legacy_compose_file).exists():
            compose_path = legacy_compose_file

        if not compose_path:
            logger.info(f"[{workspace_slug}] No app compose file found")
            return

        project_name = f"{workspace_slug}-app"

        # Down with volumes to clean up database
        result = subprocess.run(
            ["docker", "compose", "-f", compose_path, "-p", project_name,
             "down", "--remove-orphans", "--rmi", "local", "-v"],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode == 0:
            logger.info(f"[{workspace_slug}] App containers and volumes removed")
        else:
            logger.warning(f"[{workspace_slug}] Container removal warning: {result.stderr}")

    async def _unlink_app_cleanup_data(self, workspace_slug: str, workspace_id: str):
        """Clean up app-related data files"""
        from datetime import datetime

        workspace_dir = WORKSPACES_DIR / workspace_slug

        # Archive app directory if it exists
        app_dir = workspace_dir / "app"
        if app_dir.exists():
            archive_dir = workspace_dir / ".archived-app"
            archive_dir.mkdir(parents=True, exist_ok=True)
            archived_name = f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.move(str(app_dir), str(archive_dir / archived_name))
            logger.info(f"[{workspace_slug}] App directory archived")

        # Remove compose file
        compose_file = workspace_dir / "docker-compose.app.yml"
        if compose_file.exists():
            compose_file.unlink()
            logger.info(f"[{workspace_slug}] App compose file removed")

    async def _unlink_app_finalize(self, workspace_slug: str, workspace_id: str):
        """Finalize unlink - clear app fields from workspace"""
        status_payload = {
            "workspace_id": workspace_id,
            "workspace_slug": workspace_slug,
            "status": "active",
            # Clear app-related fields by setting them to None
            "app_template_id": None,
            "github_repo_url": None,
            "github_repo_name": None,
            "github_org": None,
            "app_subdomain": None,
            "app_database_name": None,
            "azure_app_id": None,
            "azure_object_id": None,
            "azure_client_secret": None,
        }

        await self.redis.publish("workspace:status", json.dumps(status_payload))
        await asyncio.sleep(0.5)

        logger.info(f"[{workspace_slug}] App unlink finalized")

    async def delete_workspace(self, task: dict):
        """Delete a workspace and all its resources"""
        task_id = task["task_id"]
        payload = task["payload"]
        workspace_id = payload["workspace_id"]
        workspace_slug = payload["workspace_slug"]
        delete_github_repo = payload.get("delete_github_repo", False)

        logger.info(f"Deleting workspace: {workspace_slug} (delete_github_repo={delete_github_repo})")

        # Store payload for step functions
        self._current_payload = payload

        steps = [
            ("Deleting sandboxes", self._workspace_delete_sandboxes),
            ("Stopping app containers", self._workspace_stop_app),
        ]

        # Only delete GitHub repo if explicitly requested
        if delete_github_repo:
            steps.append(("Deleting GitHub repository", self._workspace_delete_github_repo))

        steps.extend([
            ("Deleting Azure app registration", self._workspace_delete_azure_app),
            ("Archiving workspace data", self._workspace_archive_data),
            ("Stopping kanban team", self._delete_stop_containers),
            ("Removing containers", self._delete_remove_containers),
            ("Archiving data", self._delete_archive_data),
            ("Cleaning up", self._delete_cleanup),
        ])

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(workspace_slug, workspace_id)
                logger.info(f"[{workspace_slug}] {step_name} - completed")

            # Publish status update
            await self.redis.publish("workspace:status", json.dumps({
                "workspace_id": workspace_id,
                "workspace_slug": workspace_slug,
                "status": "deleted"
            }))

            await self.complete_task(task_id, {
                "action": "delete_workspace",
                "workspace_slug": workspace_slug,
                "deleted": True
            })

            logger.info(f"Workspace {workspace_slug} deleted successfully")

        except Exception as e:
            logger.error(f"Workspace deletion failed: {e}")
            await self.fail_task(task_id, str(e))
            raise

    async def _workspace_delete_sandboxes(self, workspace_slug: str, workspace_id: str):
        """Delete all sandboxes for this workspace"""
        sandboxes = self._current_payload.get("sandboxes", [])

        if not sandboxes:
            logger.info(f"[{workspace_slug}] No sandboxes to delete")
            return

        logger.info(f"[{workspace_slug}] Deleting {len(sandboxes)} sandbox(es)")

        for sandbox in sandboxes:
            full_slug = sandbox["full_slug"]
            sandbox_id = sandbox["id"]

            logger.info(f"[{workspace_slug}] Deleting sandbox: {full_slug}")

            try:
                # Stop and remove sandbox resources
                await self._sandbox_stop_containers(full_slug, sandbox_id)
                await self._sandbox_remove_containers(full_slug, sandbox_id)
                await self._sandbox_delete_branch(full_slug, sandbox_id)
                await self._sandbox_archive_data(full_slug, sandbox_id)

                # Publish sandbox deleted status
                await self.redis.publish("sandbox:status", json.dumps({
                    "sandbox_id": sandbox_id,
                    "full_slug": full_slug,
                    "status": "deleted"
                }))

                logger.info(f"[{workspace_slug}] Sandbox {full_slug} deleted")
            except Exception as e:
                logger.error(f"[{workspace_slug}] Error deleting sandbox {full_slug}: {e}")
                # Continue with other sandboxes

    async def _workspace_stop_app(self, workspace_slug: str, workspace_id: str):
        """Stop and remove app containers if deployed"""
        if not self.docker_available:
            logger.warning(f"[{workspace_slug}] Docker not available, skipping app container stop")
            return

        # Check if app compose file exists
        compose_file = Path(f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/app/docker-compose.yml")
        if not compose_file.exists():
            logger.info(f"[{workspace_slug}] No app compose file found, skipping")
            return

        project_name = f"{workspace_slug}-app"
        logger.info(f"[{workspace_slug}] Stopping app containers (project: {project_name})")

        # Stop and remove containers
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "-p", project_name, "down", "--remove-orphans", "--rmi", "local"],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode == 0:
            logger.info(f"[{workspace_slug}] App containers stopped and removed")
        else:
            logger.warning(f"[{workspace_slug}] Docker compose down returned {result.returncode}: {result.stderr}")
            # Fallback: force remove containers by name
            for suffix in ["api", "web", "postgres", "redis"]:
                container_name = f"{workspace_slug}-{suffix}"
                run_docker_cmd(["rm", "-f", container_name], check=False)
            logger.info(f"[{workspace_slug}] App containers removed (fallback)")

    async def _workspace_delete_github_repo(self, workspace_slug: str, workspace_id: str):
        """Delete GitHub repository for the workspace app"""
        github_org = self._current_payload.get("github_org")
        github_repo_name = self._current_payload.get("github_repo_name")

        if not github_org or not github_repo_name:
            logger.warning(f"[{workspace_slug}] No GitHub repo info, skipping deletion")
            return

        logger.info(f"[{workspace_slug}] Deleting GitHub repository: {github_org}/{github_repo_name}")

        try:
            deleted = await github_service.delete_repository(
                owner=github_org,
                repo=github_repo_name,
            )
            if deleted:
                logger.info(f"[{workspace_slug}] GitHub repository deleted")
            else:
                logger.warning(f"[{workspace_slug}] GitHub repository not found (may have been deleted already)")
        except Exception as e:
            logger.warning(f"[{workspace_slug}] Failed to delete GitHub repository (non-fatal): {e}")

    async def _workspace_delete_azure_app(self, workspace_slug: str, workspace_id: str):
        """Delete Azure AD app registration if it exists"""
        azure_object_id = self._current_payload.get("azure_object_id")

        if not azure_object_id:
            logger.info(f"[{workspace_slug}] No Azure app registration to delete")
            return

        logger.info(f"[{workspace_slug}] Deleting Azure app registration: {azure_object_id}")

        try:
            deleted = await azure_service.delete_app_registration(azure_object_id)
            if deleted:
                logger.info(f"[{workspace_slug}] Azure app registration deleted successfully")
            else:
                logger.warning(f"[{workspace_slug}] Azure app registration not found (may have been deleted manually)")
        except Exception as e:
            logger.error(f"[{workspace_slug}] Failed to delete Azure app registration: {e}")
            # Don't raise - continue with deletion even if Azure cleanup fails

    async def _workspace_archive_data(self, workspace_slug: str, workspace_id: str):
        """Archive workspace data directory before deletion.

        This includes postgres data, redis data, uploads, etc.
        Archiving prevents orphaned data from causing issues if the workspace is recreated.
        """
        workspace_dir = WORKSPACES_DIR / workspace_slug
        archive_dir = WORKSPACES_DIR / ".archived"

        if not workspace_dir.exists():
            logger.info(f"[{workspace_slug}] Workspace data directory not found, nothing to archive")
            return

        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            archived_name = f"{workspace_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            archived_path = archive_dir / archived_name

            shutil.move(str(workspace_dir), str(archived_path))
            logger.info(f"[{workspace_slug}] Workspace data archived to {archived_path}")
        except Exception as e:
            logger.error(f"[{workspace_slug}] Failed to archive workspace data: {e}")
            # Try to delete instead if move fails
            try:
                shutil.rmtree(str(workspace_dir))
                logger.info(f"[{workspace_slug}] Workspace data deleted (archive failed)")
            except Exception as e2:
                logger.error(f"[{workspace_slug}] Failed to delete workspace data: {e2}")
                # Don't raise - continue with deletion

    # ========== App Factory: Sandbox Provisioning ==========

    async def provision_sandbox(self, task: dict):
        """Provision a new sandbox environment"""
        task_id = task["task_id"]
        payload = task["payload"]
        sandbox_id = payload["sandbox_id"]
        workspace_slug = payload["workspace_slug"]
        sandbox_slug = payload["sandbox_slug"]
        full_slug = payload["full_slug"]
        source_branch = payload.get("source_branch", "main")

        # Map azure_* credentials from portal to entra_* for templates
        # Portal stores as azure_*, templates expect entra_*
        if payload.get("azure_tenant_id") and not payload.get("entra_tenant_id"):
            payload["entra_tenant_id"] = payload["azure_tenant_id"]
            payload["entra_client_id"] = payload.get("azure_app_id", "")
            payload["entra_client_secret"] = payload.get("azure_client_secret", "")
            # Use CIAM authority from environment
            payload["entra_authority"] = ENTRA_CIAM_AUTHORITY

        self._current_payload = payload

        logger.info(f"Provisioning sandbox: {full_slug} (from branch: {source_branch})")

        steps = [
            ("Validating sandbox configuration", self._sandbox_validate),
            ("Updating Azure redirect URIs", self._sandbox_update_azure_redirect_uris),
            ("Creating git branch", self._sandbox_create_branch),
            ("Issuing SSL certificate", self._sandbox_issue_certificate),
            ("Cloning workspace database", self._sandbox_clone_database),
            ("Creating sandbox directory", self._sandbox_create_directory),
            ("Configuring sandbox with Claude", self._sandbox_configure_with_claude),
            ("Deploying sandbox containers", self._sandbox_deploy_containers),
            ("Running health check", self._sandbox_health_check),
            ("Finalizing sandbox", self._sandbox_finalize),
        ]

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(full_slug, sandbox_id)
                logger.info(f"[{full_slug}] {step_name} - completed")

            await self.complete_task(task_id, {
                "action": "create_sandbox",
                "sandbox_id": sandbox_id,
                "full_slug": full_slug,
                "git_branch": f"sandbox/{full_slug}",
            })

            logger.info(f"Sandbox {full_slug} provisioned successfully")

        except Exception as e:
            logger.error(f"Sandbox provisioning failed: {e}")
            # Publish failure status to Redis so the portal worker updates the database
            await self.redis.publish("sandbox:status", json.dumps({
                "sandbox_id": sandbox_id,
                "full_slug": full_slug,
                "status": "failed",
                "error": str(e)
            }))
            await self.fail_task(task_id, str(e))
            raise

    async def _sandbox_validate(self, full_slug: str, sandbox_id: str):
        """Validate sandbox configuration"""
        if not full_slug or len(full_slug) < 5:
            raise ValueError("Invalid sandbox full_slug")

    async def _sandbox_update_azure_redirect_uris(self, full_slug: str, sandbox_id: str):
        """Add sandbox redirect URI to Azure app registration"""
        azure_object_id = self._current_payload.get("azure_object_id")
        workspace_slug = self._current_payload.get("workspace_slug")

        if not azure_object_id:
            logger.warning(f"[{full_slug}] No Azure object ID provided, skipping redirect URI update")
            return

        # Build the sandbox redirect URI
        # Domain format: {full_slug}.sandbox.{base_domain}/api/auth/callback
        base_domain = DOMAIN.replace("kanban.", "") if DOMAIN.startswith("kanban.") else DOMAIN
        sandbox_redirect_uri = f"https://{full_slug}.sandbox.{base_domain}"
        if PORT and PORT != "443":
            sandbox_redirect_uri += f":{PORT}"
        sandbox_redirect_uri += "/api/auth/callback"

        logger.info(f"[{full_slug}] Adding redirect URI to Azure app: {sandbox_redirect_uri}")

        try:
            # Get existing redirect URIs
            app = await azure_service.get_app_registration(azure_object_id)
            if not app:
                logger.error(f"[{full_slug}] Azure app registration not found: {azure_object_id}")
                raise Exception("Azure app registration not found")

            existing_uris = app.get("web", {}).get("redirectUris", [])

            # Check if already present
            if sandbox_redirect_uri in existing_uris:
                logger.info(f"[{full_slug}] Redirect URI already present, skipping")
                return

            # Add new URI to existing list
            updated_uris = existing_uris + [sandbox_redirect_uri]

            # Update app registration
            success = await azure_service.update_redirect_uris(azure_object_id, updated_uris)
            if not success:
                raise Exception("Failed to update Azure redirect URIs")

            logger.info(f"[{full_slug}] Redirect URI added successfully")

        except Exception as e:
            logger.error(f"[{full_slug}] Failed to update Azure redirect URIs: {e}")
            # This is not fatal - continue with provisioning
            # The user can manually add the redirect URI later

    async def _sandbox_create_branch(self, full_slug: str, sandbox_id: str):
        """Create git branch for sandbox"""
        workspace_slug = self._current_payload["workspace_slug"]
        github_org = self._current_payload.get("github_org", "hckmseduardo")
        github_repo = self._current_payload.get("github_repo_name", f"{workspace_slug}-app")
        source_branch = self._current_payload.get("source_branch", "main")
        github_pat = self._current_payload.get("github_pat")  # Custom PAT for private repos
        branch_name = f"sandbox/{full_slug}"

        logger.info(f"[{full_slug}] Creating branch: {branch_name} from {source_branch}")

        try:
            result = await github_service.create_branch(
                owner=github_org,
                repo=github_repo,
                branch_name=branch_name,
                source_branch=source_branch,
                token=github_pat,
            )

            if result.get("already_exists"):
                logger.warning(f"[{full_slug}] Branch already exists, continuing...")
            else:
                logger.info(f"[{full_slug}] Branch created successfully")

        except Exception as e:
            logger.error(f"[{full_slug}] Failed to create branch: {e}")
            raise

    async def _sandbox_issue_certificate(self, full_slug: str, sandbox_id: str):
        """Issue SSL certificate for sandbox subdomain"""
        logger.info(f"[{full_slug}] Issuing SSL certificate for sandbox subdomain")

        try:
            cert_info = await certificate_service.issue_sandbox_certificate(full_slug)
            self._current_payload["cert_info"] = cert_info
            logger.info(f"[{full_slug}] SSL certificate issued: {cert_info.get('domain', 'unknown')}")
        except Exception as e:
            logger.warning(f"[{full_slug}] Certificate issuance failed (non-fatal): {e}")
            # Continue without certificate - Traefik may handle it

    async def _sandbox_clone_database(self, full_slug: str, sandbox_id: str):
        """Clone workspace database for sandbox"""
        workspace_slug = self._current_payload["workspace_slug"]
        database_name = full_slug.replace("-", "_")

        logger.info(f"[{full_slug}] Cloning database from workspace {workspace_slug}")

        # Source container is the workspace's postgres container
        source_container = f"{workspace_slug}-postgres"
        source_db = workspace_slug.replace("-", "_") + "_app"

        # Target container is the sandbox's postgres container
        target_container = f"{full_slug}-postgres"
        target_db = database_name

        try:
            # Clone the database
            await database_cloner.clone_database(
                source_container=source_container,
                source_db=source_db,
                target_container=target_container,
                target_db=target_db,
            )
            logger.info(f"[{full_slug}] Database cloned successfully: {target_db}")
        except Exception as e:
            logger.warning(f"[{full_slug}] Database cloning failed (may not exist yet): {e}")
            # This is expected for new workspaces without a database
            pass

    async def _sandbox_create_directory(self, full_slug: str, sandbox_id: str):
        """Create sandbox directory structure and clone/update repository."""
        # Sandbox data is stored at {HOST_PROJECT_PATH}/data/sandboxes/{full_slug}
        # This directory is mounted in docker-compose.yml, so we can use Python file operations
        sandbox_data_path = f"{HOST_PROJECT_PATH}/data/sandboxes/{full_slug}"

        # Create sandbox data directories
        os.makedirs(f"{sandbox_data_path}/uploads", exist_ok=True)
        os.makedirs(f"{sandbox_data_path}/redis", exist_ok=True)

        logger.info(f"[{full_slug}] Directory structure created at {sandbox_data_path}")

        # Setup repository with the sandbox branch
        workspace_slug = self._current_payload["workspace_slug"]
        github_org = self._current_payload.get("github_org", "hckmseduardo")
        github_repo = self._current_payload.get("github_repo_name", f"{workspace_slug}-app")
        git_branch = f"sandbox/{full_slug}"

        github_repo_url = f"https://github.com/{github_org}/{github_repo}.git"
        # Use workspace-specific PAT if available, otherwise fall back to default
        github_token = self._current_payload.get("github_pat") or os.environ.get("GITHUB_TOKEN")

        # Build authenticated clone URL
        clone_url = github_repo_url
        if github_token and "github.com" in github_repo_url:
            clone_url = github_repo_url.replace("https://github.com", f"https://{github_token}@github.com")

        repo_path = f"{sandbox_data_path}/repo"
        git_dir = f"{repo_path}/.git"

        # Check if repository already exists
        if os.path.exists(git_dir):
            logger.info(f"[{full_slug}] Repository already exists, updating to latest version")

            # Fetch all remote changes
            result = subprocess.run(
                ["git", "fetch", "--all"],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                logger.warning(f"[{full_slug}] Failed to fetch: {result.stderr}")

            # Checkout the correct branch
            logger.info(f"[{full_slug}] Checking out branch {git_branch}")
            result = subprocess.run(
                ["git", "checkout", git_branch],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                logger.warning(f"[{full_slug}] Failed to checkout {git_branch}: {result.stderr}")
                # Try to create the branch from origin if checkout failed
                result = subprocess.run(
                    ["git", "checkout", "-b", git_branch, f"origin/{git_branch}"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    raise RuntimeError(f"Failed to checkout branch {git_branch}: {result.stderr}")

            # Pull latest changes
            logger.info(f"[{full_slug}] Pulling latest changes for branch {git_branch}")
            result = subprocess.run(
                ["git", "pull", "origin", git_branch],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                logger.warning(f"[{full_slug}] Failed to pull (may be ok if no remote changes): {result.stderr}")

            logger.info(f"[{full_slug}] Repository updated successfully")
        else:
            # Clone fresh
            os.makedirs(repo_path, exist_ok=True)

            logger.info(f"[{full_slug}] Cloning repository with branch {git_branch}")
            result = subprocess.run(
                ["git", "clone", "--branch", git_branch, clone_url, "."],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to clone repository: {result.stderr}")

            logger.info(f"[{full_slug}] Repository cloned successfully to {repo_path}")

    async def _sandbox_configure_with_claude(self, full_slug: str, sandbox_id: str):
        """Configure sandbox repository using Claude CLI for non-template repos.

        Detects if the repository has the expected structure (backend/Dockerfile
        and frontend/Dockerfile) and if not, uses Claude CLI to generate
        appropriate Docker configuration.
        """
        sandbox_data_path = f"{HOST_PROJECT_PATH}/data/sandboxes/{full_slug}"
        repo_path = f"{sandbox_data_path}/repo"

        # Check if repository has expected structure
        backend_dockerfile = Path(repo_path) / "backend" / "Dockerfile"
        frontend_dockerfile = Path(repo_path) / "frontend" / "Dockerfile"

        if backend_dockerfile.exists() and frontend_dockerfile.exists():
            logger.info(f"[{full_slug}] Repository has expected structure, skipping Claude configuration")
            return

        # Check if there's already a docker-compose.yml in the repo
        existing_compose = Path(repo_path) / "docker-compose.yml"
        if existing_compose.exists():
            logger.info(f"[{full_slug}] Repository has docker-compose.yml, Claude will adapt it")

        # Calculate the domain
        base_domain = DOMAIN.replace("kanban.", "") if DOMAIN.startswith("kanban.") else DOMAIN
        sandbox_domain = f"{full_slug}.sandbox.{base_domain}"

        prompt = f"""Analyze this repository and configure it to run as a Docker application for the Kanban sandbox environment.

Requirements:
1. Create a docker-compose.yml in the root with THESE EXACT configurations:
   - PostgreSQL service: {full_slug}-postgres (postgres:15-alpine)
   - App service(s): {full_slug}-api and optionally {full_slug}-web
   - Redis service: {full_slug}-redis (redis:7-alpine)
   - All services must use container_name matching the service name
   - Network: {NETWORK_NAME} (external: true)
   - restart: unless-stopped on all services

2. The app MUST expose:
   - Backend API on port 8000 (internal)
   - Frontend (if exists) on port 5173 (internal)

3. Traefik labels for HTTPS routing:
   - Domain: {sandbox_domain}
   - API route: PathPrefix(/api) with strip middleware
   - Frontend route: Host rule for all other paths
   - Use certresolver: kanban-letsencrypt
   - Entrypoints: websecure (HTTPS), web (HTTP redirect)

4. Create/modify Dockerfile(s) as needed:
   - Multi-stage builds for smaller images
   - Production-ready configurations
   - Appropriate CMD/ENTRYPOINT

5. Environment variables the app expects:
   - DATABASE_URL=postgresql+asyncpg://postgres:${{POSTGRES_PASSWORD}}@{full_slug}-postgres:5432/{full_slug.replace('-', '_')}
   - SECRET_KEY (will be injected)
   - REDIS_URL=redis://{full_slug}-redis:6379

6. Volume mounts:
   - PostgreSQL: /var/lib/postgresql/data
   - Redis: /data
   - Uploads: /app/uploads (if applicable)

The sandbox will be accessible at: https://{sandbox_domain}

Important:
- Analyze the existing codebase structure carefully
- If a docker-compose.yml exists, adapt it to the sandbox requirements
- Keep any app-specific services that are needed
- Use kanban labels for orchestration: kanban.type, kanban.full-slug, etc.

Generate the docker-compose.yml file now."""

        logger.info(f"[{full_slug}] Configuring sandbox with Claude CLI...")

        try:
            result = await claude_runner.run(
                prompt=prompt,
                working_dir=repo_path,
                tool_profile="developer",
                timeout=600,  # 10 minutes
            )

            if not result.success:
                raise RuntimeError(f"Claude configuration failed: {result.error}")

            # Verify docker-compose.yml was created or modified
            compose_path = Path(repo_path) / "docker-compose.yml"
            if not compose_path.exists():
                logger.warning(f"[{full_slug}] Claude did not generate docker-compose.yml, will use template")
            else:
                logger.info(f"[{full_slug}] Sandbox configured successfully by Claude")
                # Mark that we have a Claude-generated config
                self._current_payload["claude_configured"] = True

        except Exception as e:
            logger.warning(f"[{full_slug}] Claude configuration failed, will try template: {e}")
            # Don't fail - let the template-based deployment try

    async def _sandbox_deploy_containers(self, full_slug: str, sandbox_id: str):
        """Deploy sandbox containers using the sandbox-compose template or Claude-generated config"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        workspace_slug = self._current_payload["workspace_slug"]
        sandbox_slug = self._current_payload["sandbox_slug"]
        git_branch = f"sandbox/{full_slug}"
        database_name = full_slug.replace("-", "_")

        logger.info(f"[{full_slug}] Deploying sandbox containers")

        # Paths
        workspace_data_path = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}"
        sandbox_data_path = f"{HOST_PROJECT_PATH}/data/sandboxes/{full_slug}"
        repo_path = f"{sandbox_data_path}/repo"
        app_source_path = f"{workspace_data_path}/app"

        # Check if Claude generated a docker-compose.yml
        claude_compose = Path(repo_path) / "docker-compose.yml"
        compose_file_host = f"{sandbox_data_path}/docker-compose.app.yml"
        sandbox_host_dir = sandbox_data_path

        # Ensure directory exists
        os.makedirs(sandbox_host_dir, exist_ok=True)

        use_claude_compose = False
        if claude_compose.exists() and self._current_payload.get("claude_configured"):
            # Use Claude-generated compose file from repo directory
            logger.info(f"[{full_slug}] Using Claude-generated docker-compose.yml")
            # Run compose from repo directory so relative paths work
            compose_file_host = str(claude_compose)
            use_claude_compose = True
        else:
            # Use template-based compose
            logger.info(f"[{full_slug}] Using template-based docker-compose")

            # Generate secrets
            postgres_password = secrets.token_hex(16)
            app_secret_key = secrets.token_hex(32)

            # Kanban API URL
            if PORT == "443":
                kanban_api_url = f"https://{workspace_slug}.{DOMAIN}/api"
            else:
                kanban_api_url = f"https://{workspace_slug}.{DOMAIN}:{PORT}/api"

            # Render sandbox compose template
            try:
                template = self.app_factory_jinja.get_template("sandbox-compose.yml.j2")
                compose_content = template.render(
                    full_slug=full_slug,
                    workspace_slug=workspace_slug,
                    sandbox_slug=sandbox_slug,
                    git_branch=git_branch,
                    database_name=database_name,
                    postgres_password=postgres_password,
                    app_secret_key=app_secret_key,
                    data_path=sandbox_data_path,
                    app_source_path=app_source_path,
                    kanban_api_url=kanban_api_url,
                    domain=DOMAIN,
                    port=PORT,
                    network_name=NETWORK_NAME,
                    # Entra External ID (CIAM) credentials (inherited from workspace)
                    entra_tenant_id=self._current_payload.get("entra_tenant_id", ""),
                    entra_authority=self._current_payload.get("entra_authority", ""),
                    entra_client_id=self._current_payload.get("entra_client_id", ""),
                    entra_client_secret=self._current_payload.get("entra_client_secret", ""),
                )
            except Exception as e:
                logger.error(f"[{full_slug}] Failed to render sandbox template: {e}")
                raise

            # Write compose file
            with open(compose_file_host, "w") as f:
                f.write(compose_content)

        logger.info(f"[{full_slug}] Using compose file: {compose_file_host}")

        project_name = f"{full_slug}-app"
        # Working directory for docker compose - use repo dir for Claude compose
        compose_cwd = repo_path if use_claude_compose else None

        try:
            # Stop and remove existing stack if it exists
            subprocess.run(
                ["docker", "compose", "-f", compose_file_host, "-p", project_name, "down", "--remove-orphans"],
                capture_output=True,
                text=True,
                check=False,
                cwd=compose_cwd
            )

            # Create sandbox data directories and clean up postgres data
            # The sandboxes directory is mounted, so we can use regular Python file operations
            postgres_host_path = f"{sandbox_data_path}/postgres"
            os.makedirs(f"{sandbox_data_path}/uploads", exist_ok=True)
            os.makedirs(f"{sandbox_data_path}/redis", exist_ok=True)
            if os.path.exists(postgres_host_path):
                shutil.rmtree(postgres_host_path, ignore_errors=True)
            logger.info(f"[{full_slug}] Created directories and cleaned postgres data")

            # Start the stack with retry logic for transient failures
            max_retries = 3
            retry_delay = 2  # seconds
            last_error = None

            for attempt in range(1, max_retries + 1):
                result = subprocess.run(
                    ["docker", "compose", "-f", compose_file_host, "-p", project_name, "up", "-d", "--build"],
                    capture_output=True,
                    text=True,
                    check=False,
                    cwd=compose_cwd
                )

                if result.returncode == 0:
                    logger.info(f"[{full_slug}] Sandbox containers deployed (attempt {attempt})")
                    break

                last_error = result.stderr or result.stdout or "Unknown error"
                logger.warning(f"[{full_slug}] Docker compose up failed (attempt {attempt}/{max_retries}): {last_error}")

                if attempt < max_retries:
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
            else:
                # All retries exhausted
                logger.error(f"[{full_slug}] Docker compose stderr: {result.stderr}")
                logger.error(f"[{full_slug}] Docker compose stdout: {result.stdout}")
                raise RuntimeError(f"Failed to start sandbox containers after {max_retries} attempts: {last_error}")

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"[{full_slug}] Sandbox deployment failed: {e}")
            raise

    async def _sandbox_health_check(self, full_slug: str, sandbox_id: str):
        """Health check for sandbox components"""
        if not self.docker_available:
            logger.warning("Docker not available, skipping health check")
            return

        logger.info(f"[{full_slug}] Running health check")

        # Check key containers
        containers_to_check = [
            f"{full_slug}-api",
            f"{full_slug}-web",
            f"{full_slug}-postgres",
        ]

        max_retries = 15
        for i in range(max_retries):
            all_running = True
            for container in containers_to_check:
                result = run_docker_cmd([
                    "inspect", "-f", "{{.State.Status}}", container
                ], check=False)

                if result.returncode != 0 or result.stdout.strip() != "running":
                    all_running = False
                    break

            if all_running:
                logger.info(f"[{full_slug}] All sandbox containers are running")
                return

            logger.info(f"[{full_slug}] Waiting for containers... (attempt {i+1}/{max_retries})")
            await asyncio.sleep(2)

        raise RuntimeError(f"Sandbox containers for {full_slug} failed to start")

    async def _sandbox_finalize(self, full_slug: str, sandbox_id: str):
        """Finalize sandbox setup"""
        await self.redis.publish("sandbox:status", json.dumps({
            "sandbox_id": sandbox_id,
            "full_slug": full_slug,
            "status": "active"
        }))
        await asyncio.sleep(0.5)

    async def delete_sandbox(self, task: dict):
        """Delete a sandbox environment"""
        task_id = task["task_id"]
        payload = task["payload"]
        sandbox_id = payload["sandbox_id"]
        full_slug = payload["full_slug"]

        # Store payload for access by step functions
        self._current_payload = payload

        logger.info(f"Deleting sandbox: {full_slug}")

        steps = [
            ("Stopping sandbox containers", self._sandbox_stop_containers),
            ("Removing sandbox containers", self._sandbox_remove_containers),
            ("Deleting git branch", self._sandbox_delete_branch),
            ("Removing Azure redirect URI", self._sandbox_remove_azure_redirect_uri),
            ("Archiving sandbox data", self._sandbox_archive_data),
        ]

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(full_slug, sandbox_id)
                logger.info(f"[{full_slug}] {step_name} - completed")

            await self.redis.publish("sandbox:status", json.dumps({
                "sandbox_id": sandbox_id,
                "full_slug": full_slug,
                "status": "deleted"
            }))

            await self.complete_task(task_id, {
                "action": "delete_sandbox",
                "sandbox_id": sandbox_id,
                "full_slug": full_slug,
                "deleted": True
            })

            logger.info(f"Sandbox {full_slug} deleted successfully")

        except Exception as e:
            logger.error(f"Sandbox deletion failed: {e}")
            await self.fail_task(task_id, str(e))
            raise

    async def restart_sandbox(self, task: dict):
        """Restart a sandbox environment by pulling latest code and rebuilding containers"""
        task_id = task["task_id"]
        payload = task["payload"]
        sandbox_id = payload["sandbox_id"]
        full_slug = payload["full_slug"]
        workspace_slug = payload.get("workspace_slug", full_slug.rsplit("-", 1)[0])

        # Store payload for access by step functions
        self._current_payload = payload

        logger.info(f"Restarting sandbox: {full_slug}")

        steps = [
            ("Pulling latest code", self._sandbox_restart_pull_code),
            ("Stopping containers", self._sandbox_stop_containers),
            ("Rebuilding containers", self._sandbox_restart_rebuild),
            ("Running health check", self._sandbox_restart_health_check),
        ]

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(full_slug, sandbox_id)
                logger.info(f"[{full_slug}] {step_name} - completed")

            await self.redis.publish("sandbox:status", json.dumps({
                "sandbox_id": sandbox_id,
                "full_slug": full_slug,
                "status": "restarted"
            }))

            await self.complete_task(task_id, {
                "action": "restart_sandbox",
                "sandbox_id": sandbox_id,
                "full_slug": full_slug,
                "restarted": True
            })

            logger.info(f"Sandbox {full_slug} restarted successfully")

        except Exception as e:
            logger.error(f"Sandbox restart failed: {e}")
            await self.fail_task(task_id, str(e))
            raise

    async def sandbox_pull_request(self, task: dict):
        """Create, approve, and merge a sandbox PR, then rebuild the workspace app."""
        task_id = task["task_id"]
        payload = task["payload"]
        workspace_id = payload["workspace_id"]
        workspace_slug = payload["workspace_slug"]
        sandbox_id = payload["sandbox_id"]
        sandbox_slug = payload["sandbox_slug"]
        full_slug = payload.get("full_slug", f"{workspace_slug}-{sandbox_slug}")
        git_branch = payload.get("git_branch") or f"sandbox/{full_slug}"

        # Store payload for step functions
        payload["full_slug"] = full_slug
        payload["git_branch"] = git_branch
        self._current_payload = payload

        logger.info(f"[{full_slug}] Starting sandbox pull request flow")

        steps = [
            ("Validating repository", self._sandbox_pr_validate),
            ("Creating pull request", self._sandbox_pr_create),
            ("Approving pull request", self._sandbox_pr_approve),
            ("Merging pull request", self._sandbox_pr_merge),
            ("Updating workspace code", self._workspace_update_repo_main),
            ("Rebuilding app containers", self._workspace_rebuild_app_after_merge),
        ]

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(full_slug, sandbox_id)
                logger.info(f"[{full_slug}] {step_name} - completed")

            pr_url = self._current_payload.get("pull_request_url")
            pr_number = self._current_payload.get("pull_request_number")
            merge_sha = self._current_payload.get("merge_sha")

            await self.complete_task(task_id, {
                "action": "sandbox.pull_request",
                "workspace_slug": workspace_slug,
                "sandbox_slug": sandbox_slug,
                "full_slug": full_slug,
                "pull_request_url": pr_url,
                "pull_request_number": pr_number,
                "merge_sha": merge_sha,
            })

            logger.info(f"[{full_slug}] Sandbox pull request flow completed")

        except Exception as e:
            logger.error(f"[{full_slug}] Sandbox pull request failed: {e}")
            await self.fail_task(task_id, str(e))
            raise

    async def _sandbox_pr_validate(self, full_slug: str, sandbox_id: str):
        """Validate GitHub repo and branch for PR creation."""
        payload = self._current_payload
        github_org = payload.get("github_org")
        github_repo = payload.get("github_repo_name")
        git_branch = payload.get("git_branch")
        if not github_org or not github_repo:
            raise RuntimeError("GitHub repository info not configured for this workspace")

        # Ensure token is configured early
        _ = github_service.token

        # Confirm repository exists
        repo = await github_service.get_repository(github_org, github_repo)
        if not repo:
            raise RuntimeError(f"GitHub repository not found: {github_org}/{github_repo}")

        branch = await github_service.get_branch(github_org, github_repo, git_branch)
        if not branch:
            raise RuntimeError(f"Sandbox branch not found: {github_org}/{github_repo}:{git_branch}")

        payload["github_org"] = github_org
        payload["github_repo_name"] = github_repo
        payload["git_branch"] = git_branch

    async def _sandbox_pr_create(self, full_slug: str, sandbox_id: str):
        """Create (or find) a PR from sandbox branch to main."""
        payload = self._current_payload
        github_org = payload["github_org"]
        github_repo = payload["github_repo_name"]
        git_branch = payload["git_branch"]

        title = f"Deploy sandbox {full_slug}"
        body = f"Automated PR to merge `{git_branch}` into `main`."

        pr = await github_service.create_pull_request(
            owner=github_org,
            repo=github_repo,
            head=git_branch,
            base="main",
            title=title,
            body=body,
        )

        payload["pull_request_number"] = pr.get("number")
        payload["pull_request_url"] = pr.get("html_url")
        payload["pull_request_state"] = pr.get("state")
        payload["pull_request_merged"] = pr.get("merged_at") is not None

    async def _sandbox_pr_approve(self, full_slug: str, sandbox_id: str):
        """Approve the PR if it is open (skipped for self-owned PRs)."""
        payload = self._current_payload
        if payload.get("pull_request_merged"):
            logger.info(f"[{full_slug}] PR already merged, skipping approval")
            return
        if payload.get("pull_request_state") != "open":
            raise RuntimeError("Pull request is not open; cannot approve")

        try:
            await github_service.approve_pull_request(
                owner=payload["github_org"],
                repo=payload["github_repo_name"],
                pull_number=payload["pull_request_number"],
                body="Auto-approve sandbox deploy",
            )
        except Exception as e:
            # GitHub doesn't allow approving your own PR - skip and proceed to merge
            logger.warning(f"[{full_slug}] Could not approve PR (may be self-owned): {e}")

    async def _sandbox_pr_merge(self, full_slug: str, sandbox_id: str):
        """Merge the PR into main."""
        payload = self._current_payload
        if payload.get("pull_request_merged"):
            logger.info(f"[{full_slug}] PR already merged, skipping merge")
            return
        if payload.get("pull_request_state") != "open":
            raise RuntimeError("Pull request is not open; cannot merge")

        merge_result = await github_service.merge_pull_request(
            owner=payload["github_org"],
            repo=payload["github_repo_name"],
            pull_number=payload["pull_request_number"],
            merge_method="merge",
        )

        payload["merge_sha"] = merge_result.get("sha")

    async def _workspace_update_repo_main(self, full_slug: str, sandbox_id: str):
        """Pull latest main into the workspace app repo."""
        payload = self._current_payload
        workspace_slug = payload["workspace_slug"]
        repo_path = WORKSPACES_DIR / workspace_slug / "app"

        if not repo_path.exists():
            raise RuntimeError(f"Workspace repo not found at {repo_path}")

        commands = [
            ["git", "fetch", "origin"],
            ["git", "checkout", "main"],
            ["git", "pull", "origin", "main"],
        ]

        for cmd in commands:
            result = subprocess.run(
                cmd,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Git command failed ({' '.join(cmd)}): {result.stderr}")

        logger.info(f"[{workspace_slug}] Workspace repo updated to latest main")

    async def _workspace_rebuild_app_after_merge(self, full_slug: str, sandbox_id: str):
        """Rebuild app containers after updating main."""
        payload = self._current_payload
        workspace_slug = payload["workspace_slug"]
        workspace_id = payload["workspace_id"]
        compose_file = Path(f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/docker-compose.app.yml")
        legacy_compose = Path(f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/app/docker-compose.yml")

        if compose_file.exists():
            await self._workspace_restart_rebuild_app(workspace_slug, workspace_id)
            return
        if legacy_compose.exists():
            await self._workspace_start_rebuild_app(workspace_slug, workspace_id)
            return

        raise RuntimeError(f"No app compose file found for workspace {workspace_slug}")

    async def _sandbox_restart_pull_code(self, full_slug: str, sandbox_id: str):
        """Pull latest code from the sandbox branch"""
        workspace_slug = self._current_payload.get("workspace_slug", full_slug.rsplit("-", 1)[0])
        repo_path = f"{HOST_PROJECT_PATH}/data/sandboxes/{full_slug}/repo"
        git_branch = f"sandbox/{full_slug}"

        logger.info(f"[{full_slug}] Pulling latest from {git_branch}")

        # Check if repo directory exists
        if not os.path.exists(repo_path):
            logger.warning(f"[{full_slug}] Repo directory not found: {repo_path}")
            return

        try:
            # Fetch and checkout the sandbox branch
            result = subprocess.run(
                ["git", "fetch", "origin"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                logger.warning(f"[{full_slug}] Git fetch failed: {result.stderr}")

            # Checkout the sandbox branch
            result = subprocess.run(
                ["git", "checkout", git_branch],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                logger.warning(f"[{full_slug}] Git checkout failed: {result.stderr}")

            # Pull latest
            result = subprocess.run(
                ["git", "pull", "origin", git_branch],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                logger.warning(f"[{full_slug}] Git pull failed: {result.stderr}")
            else:
                logger.info(f"[{full_slug}] Code updated: {result.stdout.strip()}")

        except Exception as e:
            logger.error(f"[{full_slug}] Failed to pull code: {e}")
            # Don't raise - continue with restart even if pull fails

    async def _sandbox_restart_rebuild(self, full_slug: str, sandbox_id: str):
        """Rebuild and start sandbox containers"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        compose_file = f"{HOST_PROJECT_PATH}/data/sandboxes/{full_slug}/docker-compose.app.yml"
        project_name = f"{full_slug}-app"

        if not os.path.exists(compose_file):
            raise RuntimeError(f"Compose file not found: {compose_file}")

        logger.info(f"[{full_slug}] Rebuilding containers")

        # Remove old containers and images
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "down", "--rmi", "local", "--remove-orphans"],
            capture_output=True,
            text=True,
            check=False
        )

        # Build and start
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "-p", project_name, "up", "-d", "--build"],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            logger.error(f"[{full_slug}] Docker compose up failed: {result.stderr}")
            raise RuntimeError(f"Failed to rebuild containers: {result.stderr}")

        logger.info(f"[{full_slug}] Containers rebuilt successfully")

    async def _sandbox_restart_health_check(self, full_slug: str, sandbox_id: str):
        """Health check after sandbox restart"""
        if not self.docker_available:
            logger.warning("Docker not available, skipping health check")
            return

        logger.info(f"[{full_slug}] Running health check")

        # Check key containers
        containers_to_check = [
            f"{full_slug}-api",
            f"{full_slug}-web",
        ]

        max_retries = 10
        for i in range(max_retries):
            all_running = True
            for container in containers_to_check:
                result = run_docker_cmd([
                    "inspect", "-f", "{{.State.Status}}", container
                ], check=False)

                if result.returncode != 0 or result.stdout.strip() != "running":
                    all_running = False
                    break

            if all_running:
                logger.info(f"[{full_slug}] All containers healthy")
                return

            await asyncio.sleep(2)

        logger.warning(f"[{full_slug}] Some containers may not be fully healthy")

    async def _sandbox_stop_containers(self, full_slug: str, sandbox_id: str):
        """Stop sandbox containers"""
        if not self.docker_available:
            logger.warning("Docker not available, skipping container stop")
            return

        logger.info(f"[{full_slug}] Stopping containers")
        project_name = f"{full_slug}-app"

        # Stop individual containers if compose file not available
        for suffix in ["api", "web", "postgres", "redis"]:
            container_name = f"{full_slug}-{suffix}"
            run_docker_cmd(["stop", container_name], check=False)

    async def _sandbox_remove_containers(self, full_slug: str, sandbox_id: str):
        """Remove sandbox containers"""
        if not self.docker_available:
            logger.warning("Docker not available, skipping container removal")
            return

        logger.info(f"[{full_slug}] Removing containers")

        # Remove individual containers
        for suffix in ["api", "web", "postgres", "redis"]:
            container_name = f"{full_slug}-{suffix}"
            run_docker_cmd(["rm", "-f", container_name], check=False)

        # Also try removing by compose project name
        project_name = f"{full_slug}-app"
        run_docker_cmd(["compose", "-p", project_name, "down", "--remove-orphans"], check=False)

    async def _sandbox_delete_branch(self, full_slug: str, sandbox_id: str):
        """Delete sandbox git branch"""
        workspace_slug = self._current_payload.get("workspace_slug")
        github_org = self._current_payload.get("github_org")
        github_repo = self._current_payload.get("github_repo_name")

        if not workspace_slug or not github_repo:
            logger.warning(
                f"[{full_slug}] Missing workspace_slug or github_repo_name in payload, "
                f"skipping branch deletion"
            )
            return

        branch_name = f"sandbox/{full_slug}"

        logger.info(f"[{full_slug}] Deleting branch: {github_org}/{github_repo}:{branch_name}")

        try:
            deleted = await github_service.delete_branch(
                owner=github_org,
                repo=github_repo,
                branch_name=branch_name,
            )

            if deleted:
                logger.info(f"[{full_slug}] Branch deleted successfully")
            else:
                logger.warning(f"[{full_slug}] Branch not found (may have been deleted already)")

        except Exception as e:
            logger.warning(f"[{full_slug}] Failed to delete branch (non-fatal): {e}")

    async def _sandbox_remove_azure_redirect_uri(self, full_slug: str, sandbox_id: str):
        """Remove sandbox redirect URI from Azure app registration"""
        azure_object_id = self._current_payload.get("azure_object_id")

        if not azure_object_id:
            logger.warning(f"[{full_slug}] No Azure object ID provided, skipping redirect URI removal")
            return

        # Build the sandbox redirect URI to remove
        base_domain = DOMAIN.replace("kanban.", "") if DOMAIN.startswith("kanban.") else DOMAIN
        sandbox_redirect_uri = f"https://{full_slug}.sandbox.{base_domain}"
        if PORT and PORT != "443":
            sandbox_redirect_uri += f":{PORT}"
        sandbox_redirect_uri += "/api/auth/callback"

        logger.info(f"[{full_slug}] Removing redirect URI from Azure app: {sandbox_redirect_uri}")

        try:
            # Get existing redirect URIs
            app = await azure_service.get_app_registration(azure_object_id)
            if not app:
                logger.warning(f"[{full_slug}] Azure app registration not found, skipping")
                return

            existing_uris = app.get("web", {}).get("redirectUris", [])

            # Check if URI is present
            if sandbox_redirect_uri not in existing_uris:
                logger.info(f"[{full_slug}] Redirect URI not present, skipping")
                return

            # Remove URI from list
            updated_uris = [uri for uri in existing_uris if uri != sandbox_redirect_uri]

            # Update app registration
            success = await azure_service.update_redirect_uris(azure_object_id, updated_uris)
            if success:
                logger.info(f"[{full_slug}] Redirect URI removed successfully")
            else:
                logger.warning(f"[{full_slug}] Failed to update Azure redirect URIs")

        except Exception as e:
            logger.warning(f"[{full_slug}] Failed to remove Azure redirect URI (non-fatal): {e}")

    async def _sandbox_archive_data(self, full_slug: str, sandbox_id: str):
        """Archive sandbox data directory before deletion.

        This includes postgres data, redis data, uploads, etc.
        Archiving prevents orphaned data from causing password mismatch issues if the sandbox is recreated.
        """
        # Sandbox data is stored at {HOST_PROJECT_PATH}/data/sandboxes/{full_slug}
        sandbox_dir = Path(f"{HOST_PROJECT_PATH}/data/sandboxes/{full_slug}")
        archive_dir = Path(f"{HOST_PROJECT_PATH}/data/sandboxes/.archived")

        if not sandbox_dir.exists():
            logger.info(f"[{full_slug}] Sandbox data directory not found, nothing to archive")
            return

        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            archived_name = f"{full_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            archived_path = archive_dir / archived_name

            shutil.move(str(sandbox_dir), str(archived_path))
            logger.info(f"[{full_slug}] Sandbox data archived to {archived_path}")
        except Exception as e:
            logger.error(f"[{full_slug}] Failed to archive sandbox data: {e}")
            # Try to delete instead if move fails
            try:
                shutil.rmtree(str(sandbox_dir))
                logger.info(f"[{full_slug}] Sandbox data deleted (archive failed)")
            except Exception as e2:
                logger.error(f"[{full_slug}] Failed to delete sandbox data: {e2}")
                # Don't raise - continue with deletion

    # =========================================================================
    # Agent Task Processing (On-demand AI)
    # =========================================================================

    async def process_agent_task(self, task: dict):
        """Process an AI agent task using an agent CLI subprocess.

        This method:
        1. Prepares the sandbox context (git branch, working directory)
        2. Builds the agent prompt from card data and agent config
        3. Spawns agent CLI subprocess with tool_profile and timeout
        4. Streams progress to card comments
        5. Updates card on completion
        """
        task_id = task["task_id"]
        payload = task["payload"]
        card_id = payload["card_id"]
        card_number = payload.get("card_number", "")
        card_title = payload["card_title"]
        card_description = payload["card_description"]
        column_name = payload["column_name"]
        agent_config = payload.get("agent_config", {})
        agent_name = agent_config.get("agent_name", "developer")
        llm_provider = self._resolve_llm_provider(agent_config)
        payload["llm_provider"] = llm_provider
        sandbox_id = payload["sandbox_id"]
        workspace_slug = payload["workspace_slug"]
        git_branch = payload["git_branch"]
        session_id = payload.get("claude_session_id")
        kanban_api_url = payload["kanban_api_url"]
        target_project_path = payload["target_project_path"]

        # Build log prefix with card_number for easier debugging
        log_prefix = f"[{card_number}]" if card_number else f"[{card_id[:8]}]"

        logger.info(
            f"{log_prefix} Processing agent task: agent={agent_name}, "
            f"sandbox={sandbox_id}"
        )

        # Create a context dict for this task (NOT instance variables to avoid race conditions with parallel tasks)
        ctx = {
            "payload": payload,
            "result": None,
            "log_prefix": log_prefix,  # Store for use in step functions
            "task_id": task_id,  # Store for use when clearing agent_status
        }

        steps = [
            ("Preparing sandbox context", self._agent_prepare_context),
            ("Checking sandbox health", self._agent_check_sandbox_health),
            ("Resolving agent session", self._agent_resolve_session),
            ("Preparing QA context", self._agent_prepare_qa_context),
            ("Running QA tests", self._agent_run_qa_tests),
            ("Running AI agent", self._agent_run_claude),
            ("Processing results", self._agent_process_results),
            ("Processing QA results", self._agent_process_qa_results),
            ("Updating card", self._agent_update_card),
        ]

        # Update card's agent_status to "processing"
        kanban_api_url = f"http://{workspace_slug}-kanban-api-1:8000"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.patch(
                    f"{kanban_api_url}/cards/{card_id}",
                    headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")},
                    json={
                        "agent_status": {
                            "status": "processing",
                            "agent_name": agent_name,
                            "task_id": task_id,
                            "started_at": datetime.utcnow().isoformat() + "Z"
                        }
                    }
                )
                logger.info(f"{log_prefix} Updated agent_status to 'processing'")
        except Exception as e:
            logger.warning(f"{log_prefix} Failed to update agent_status to processing: {e}")

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(card_id, sandbox_id, ctx)
                logger.info(f"{log_prefix} {step_name} - completed")

            result = ctx["result"]
            await self.complete_task(task_id, {
                "action": "process_card",
                "card_id": card_id,
                "agent_name": agent_name,
                "success": result.success if result else False,
                "files_modified": result.files_modified if result else [],
            })

            logger.info(f"{log_prefix} Agent task completed successfully")

        except Exception as e:
            logger.error(f"{log_prefix} Agent task failed: {e}")
            error_message = str(e)

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    # Update card's agent_status to "failed"
                    await client.patch(
                        f"{kanban_api_url}/cards/{card_id}",
                        headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")},
                        json={
                            "agent_status": {
                                "status": "failed",
                                "agent_name": agent_name,
                                "error": error_message[:500],
                                "completed_at": datetime.utcnow().isoformat() + "Z"
                            }
                        }
                    )
                    logger.info(f"{log_prefix} Updated agent_status to 'failed'")

                    # Add a comment explaining the error
                    agent_config = payload.get("agent_config", {})
                    display_name = agent_config.get("display_name", agent_name)
                    comment_text = (
                        f"## Agent: {display_name}\n\n"
                        f"**Status:** Failed\n"
                        f"**Error:** {error_message}\n\n"
                        f"Please review and fix the issue before retrying."
                    )
                    await client.post(
                        f"{kanban_api_url}/cards/{card_id}/comments",
                        headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")},
                        json={"text": comment_text, "author_name": display_name}
                    )
                    logger.info(f"[{card_id}] Added error comment to card")

                    # Move card to Development column (column_failure)
                    # But first check if user manually moved the card while agent was running
                    column_failure = agent_config.get("column_failure", "Development")
                    board_id = payload.get("board_id")
                    original_column_name = payload.get("column_name", "")
                    should_move_card = True

                    if board_id:
                        # Check if card is still in the original column
                        card_check_resp = await client.get(
                            f"{kanban_api_url}/cards/{card_id}",
                            headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")}
                        )
                        if card_check_resp.status_code == 200:
                            card_check_data = card_check_resp.json()
                            current_column = card_check_data.get("column", {})
                            current_column_name = current_column.get("name", "")
                            if current_column_name and current_column_name != original_column_name:
                                logger.info(
                                    f"[{card_id}] Card was moved by user from '{original_column_name}' to "
                                    f"'{current_column_name}' while agent was running - skipping automatic move"
                                )
                                should_move_card = False

                        if should_move_card:
                            board_resp = await client.get(
                                f"{kanban_api_url}/boards/{board_id}",
                                headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")}
                            )
                            if board_resp.status_code == 200:
                                board_data = board_resp.json()
                                for col in board_data.get("columns", []):
                                    if col.get("name") == column_failure:
                                        move_resp = await client.post(
                                            f"{kanban_api_url}/cards/{card_id}/move",
                                            headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")},
                                            params={"column_id": col["id"], "position": 0}
                                        )
                                        if move_resp.status_code == 200:
                                            logger.info(f"Moved card to column: {column_failure}")
                                        break

                    # Clear agent_status (pass task_id to prevent race condition)
                    await client.delete(
                        f"{kanban_api_url}/cards/{card_id}/agent-status",
                        headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")},
                        params={"task_id": task_id}
                    )
                    logger.info(f"[{card_id}] Cleared agent_status")

            except Exception as status_err:
                logger.warning(f"[{card_id}] Failed to update card after failure: {status_err}")
            await self.fail_task(task_id, error_message)
            raise

    async def _agent_prepare_context(self, card_id: str, sandbox_id: str, ctx: dict):
        """Prepare the sandbox context for agent execution."""
        payload = ctx["payload"]
        log_prefix = ctx.get("log_prefix", f"[{card_id[:8]}]")
        workspace_slug = payload["workspace_slug"]
        sandbox_slug = payload.get("sandbox_slug")

        if not sandbox_slug:
            raise RuntimeError(f"sandbox_slug is required - card must be linked to a sandbox")

        # Construct full_slug from workspace and sandbox slugs
        full_slug = f"{workspace_slug}-{sandbox_slug}"
        logger.info(f"{log_prefix} Using sandbox: {full_slug} (branch: sandbox/{full_slug})")

        base_domain = DOMAIN.replace("kanban.", "")
        port_suffix = "" if PORT == "443" else f":{PORT}"
        sandbox_url = f"https://{full_slug}.sandbox.{base_domain}{port_suffix}"
        payload["sandbox_url"] = sandbox_url
        payload["sandbox_api_url"] = f"{sandbox_url}/api"

        # Always compute git_branch from full_slug - don't trust payload
        # Sandbox branch format is: sandbox/{full_slug}
        git_branch = f"sandbox/{full_slug}"
        # Update payload so other steps use the correct branch
        payload["git_branch"] = git_branch

        # Repo path is in sandbox data folder (cloned during sandbox provisioning)
        # Format: /data/sandboxes/{full_slug}/repo/
        sandbox_data_path = Path(HOST_PROJECT_PATH) / "data" / "sandboxes" / full_slug
        repo_path = sandbox_data_path / "repo"

        # If repo doesn't exist, clone it now
        if not repo_path.exists() or not (repo_path / ".git").exists():
            logger.info(f"{log_prefix} Repository not found at {repo_path}, cloning now...")

            # Get GitHub info from payload or lookup workspace
            github_repo_url = payload.get("github_repo_url")
            if not github_repo_url:
                raise RuntimeError(f"Repository not found and github_repo_url not in payload")

            # Use workspace-specific PAT if available, otherwise fall back to default
            github_token = payload.get("github_pat") or os.environ.get("GITHUB_TOKEN")
            clone_url = github_repo_url
            if github_token and "github.com" in github_repo_url:
                clone_url = github_repo_url.replace("https://github.com", f"https://{github_token}@github.com")

            # Ensure directory exists
            os.makedirs(str(repo_path), exist_ok=True)

            # Clone with the sandbox branch
            logger.info(f"{log_prefix} Cloning {github_repo_url} branch {git_branch}")
            result = subprocess.run(
                ["git", "clone", "--branch", git_branch, clone_url, "."],
                cwd=str(repo_path),
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to clone repository: {result.stderr}")

            logger.info(f"{log_prefix} Repository cloned successfully")

        # Use the repo path
        payload["target_project_path"] = str(repo_path)

        # Fetch latest changes from remote
        logger.info(f"Fetching latest changes from remote for {sandbox_id}")
        result = subprocess.run(
            ["git", "fetch", "--all"],
            cwd=str(repo_path),
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            logger.warning(f"Failed to fetch: {result.stderr}")

        # Ensure we're on the correct branch and pull latest
        logger.info(f"Checking out branch {git_branch}")
        result = subprocess.run(
            ["git", "checkout", git_branch],
            cwd=str(repo_path),
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            logger.warning(f"Failed to checkout {git_branch}: {result.stderr}")

        # Pull latest changes for the branch
        logger.info(f"Pulling latest changes for branch {git_branch}")
        result = subprocess.run(
            ["git", "pull", "origin", git_branch],
            cwd=str(repo_path),
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            # Pull might fail if branch doesn't exist on remote yet, that's ok
            logger.debug(f"Pull result: {result.stderr}")
        else:
            logger.info(f"Pulled latest changes for {git_branch}")

        # Check if working tree is dirty and clean up if needed
        log_prefix = ctx.get("log_prefix", f"[{card_id[:8]}]")
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_path),
            capture_output=True,
            text=True
        )
        if status_result.returncode == 0 and status_result.stdout.strip():
            dirty_files = [line[3:] for line in status_result.stdout.strip().splitlines() if len(line) > 3]
            logger.warning(f"{log_prefix} Git working tree is dirty with {len(dirty_files)} file(s), cleaning up...")

            # Reset staged changes and checkout to clean working tree
            subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=str(repo_path), capture_output=True)
            subprocess.run(["git", "clean", "-fd"], cwd=str(repo_path), capture_output=True)

            # Verify it's clean now
            verify_result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(repo_path),
                capture_output=True,
                text=True
            )
            if verify_result.returncode == 0 and not verify_result.stdout.strip():
                logger.info(f"{log_prefix} Git working tree cleaned successfully")
            else:
                logger.warning(f"{log_prefix} Git working tree still dirty after cleanup: {verify_result.stdout.strip()[:100]}")

    async def _agent_check_sandbox_health(self, card_id: str, sandbox_id: str, ctx: dict):
        """Check if sandbox containers are running before executing agent.

        This prevents the release agent from completing successfully when
        the sandbox is actually down (returning 404).
        """
        payload = ctx["payload"]
        log_prefix = ctx.get("log_prefix", f"[{card_id[:8]}]")
        agent_config = payload.get("agent_config", {})
        agent_name = agent_config.get("agent_name", "")

        # Only require sandbox health check for release agent
        if agent_name != "release":
            logger.debug(f"{log_prefix} Skipping sandbox health check for agent: {agent_name}")
            return

        workspace_slug = payload["workspace_slug"]
        sandbox_slug = payload.get("sandbox_slug")
        if not sandbox_slug:
            raise RuntimeError("Cannot check sandbox health: sandbox_slug not set")

        full_slug = f"{workspace_slug}-{sandbox_slug}"
        sandbox_url = payload.get("sandbox_url")
        sandbox_api_url = payload.get("sandbox_api_url")

        logger.info(f"{log_prefix} Checking sandbox health for {full_slug}")

        # Check 1: Verify sandbox containers exist and are running
        if self.docker_available:
            api_container = f"{full_slug}-api"
            try:
                result = subprocess.run(
                    ["docker", "inspect", api_container, "--format", "{{.State.Status}}"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"Sandbox container '{api_container}' not found. "
                        f"The sandbox may need to be provisioned or restarted first."
                    )

                status = result.stdout.strip()
                if status != "running":
                    raise RuntimeError(
                        f"Sandbox container '{api_container}' is not running (status: {status}). "
                        f"Please restart the sandbox before deploying."
                    )

                # Check restart count for crash loops
                result = subprocess.run(
                    ["docker", "inspect", api_container, "--format", "{{.RestartCount}}"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    restart_count = int(result.stdout.strip() or "0")
                    if restart_count > 5:
                        raise RuntimeError(
                            f"Sandbox container '{api_container}' is in a crash loop "
                            f"({restart_count} restarts). Please check logs and fix issues."
                        )

                logger.info(f"{log_prefix} Container {api_container} is running")

            except subprocess.TimeoutExpired:
                logger.warning(f"{log_prefix} Docker inspect timed out")
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning(f"{log_prefix} Could not check container status: {e}")

        # Check 2: Verify sandbox API is responding (not 404)
        if sandbox_api_url:
            try:
                async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
                    # Try the health endpoint
                    health_url = f"{sandbox_api_url}/health"
                    logger.debug(f"{log_prefix} Checking {health_url}")

                    response = await client.get(health_url)

                    if response.status_code == 404:
                        raise RuntimeError(
                            f"Sandbox API returned 404 at {health_url}. "
                            f"The sandbox may not be properly deployed or Traefik routing is misconfigured."
                        )
                    elif response.status_code >= 500:
                        raise RuntimeError(
                            f"Sandbox API returned {response.status_code} at {health_url}. "
                            f"The sandbox is experiencing server errors."
                        )
                    elif response.status_code != 200:
                        logger.warning(
                            f"{log_prefix} Sandbox health check returned {response.status_code} "
                            f"(expected 200, but continuing)"
                        )
                    else:
                        logger.info(f"{log_prefix} Sandbox API health check passed")

            except httpx.ConnectError as e:
                raise RuntimeError(
                    f"Cannot connect to sandbox API at {sandbox_api_url}. "
                    f"The sandbox containers may not be running. Error: {e}"
                )
            except httpx.TimeoutException:
                raise RuntimeError(
                    f"Timeout connecting to sandbox API at {sandbox_api_url}. "
                    f"The sandbox may be overloaded or not responding."
                )
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning(f"{log_prefix} Sandbox API check failed (non-fatal): {e}")

        logger.info(f"{log_prefix} Sandbox health check passed for {full_slug}")

    def _resolve_llm_provider(self, agent_config: dict) -> str:
        """Resolve the LLM provider for an agent, defaulting to Claude CLI."""
        provider = (agent_config or {}).get("llm_provider") or os.getenv("LLM_PROVIDER", "")
        provider = provider.strip().lower()
        if not provider:
            return "claude-cli"
        if provider in {"claude", "claude-cli", "claude-cli-ssh"}:
            return "claude-cli"
        if provider in {"codex", "codex-cli", "codex-cli-ssh"}:
            return "codex-cli"
        logger.warning(f"Unsupported LLM provider '{provider}', falling back to Claude CLI")
        return "claude-cli"

    async def _agent_resolve_session(self, card_id: str, sandbox_id: str, ctx: dict):
        """Ensure a persistent session ID exists when supported by the agent CLI."""
        payload = ctx["payload"]
        log_prefix = ctx.get("log_prefix", f"[{card_id[:8]}]")
        llm_provider = payload.get("llm_provider") or self._resolve_llm_provider(
            payload.get("agent_config", {})
        )
        if llm_provider != "claude-cli":
            logger.info(f"{log_prefix} Skipping session resolution for provider {llm_provider}")
            return
        session_id = payload.get("claude_session_id")
        kanban_api_url = payload.get("kanban_api_url")

        if session_id and not self._is_valid_uuid(session_id):
            logger.warning(f"{log_prefix} Invalid Claude session ID provided: {session_id}")
            session_id = None

        if not session_id:
            session_id = str(uuid.uuid4())
            payload["claude_session_id"] = session_id

            if kanban_api_url:
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.patch(
                            f"{kanban_api_url}/cards/{card_id}",
                            headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")},
                            json={"claude_session_id": session_id},
                        )
                    if resp.status_code != 200:
                        logger.warning(
                            f"{log_prefix} Failed to persist session ID: {resp.status_code} {resp.text}"
                        )
                except Exception as e:
                    logger.warning(f"{log_prefix} Failed to persist session ID: {e}")
            else:
                logger.warning(f"{log_prefix} Missing kanban_api_url; cannot persist session ID")

        logger.info(f"{log_prefix} Claude session resolved: {session_id}")

    @staticmethod
    def _is_valid_uuid(value: str) -> bool:
        """Validate UUID string for Claude session IDs."""
        try:
            uuid.UUID(value)
            return True
        except (ValueError, TypeError):
            return False

    async def _agent_prepare_qa_context(self, card_id: str, sandbox_id: str, ctx: dict):
        """Prepare QA runtime context for sandbox validation.

        Fetches test credentials from Key Vault and passes them to the QA agent.
        The agent will authenticate via Playwright browser automation.
        """
        payload = ctx["payload"]
        log_prefix = ctx.get("log_prefix", f"[{card_id[:8]}]")
        agent_name = payload.get("agent_config", {}).get("agent_name", "")
        if agent_name != "qa":
            return

        sandbox_url = payload.get("sandbox_url")
        sandbox_api_url = payload.get("sandbox_api_url")

        if not sandbox_url or not sandbox_api_url:
            raise RuntimeError("Sandbox URL not available for QA testing")

        # Fetch test credentials from Key Vault
        test_user_email = keyvault_service.get_secret("test-user-email")
        test_user_password = keyvault_service.get_secret("test-user-password")

        if not test_user_email or not test_user_password:
            raise RuntimeError(
                "Missing test user credentials from Key Vault. "
                "Please ensure 'test-user-email' and 'test-user-password' secrets are configured."
            )

        logger.info(f"{log_prefix} QA credentials loaded for browser authentication")

        # Store credentials for inclusion in the prompt (QA agent authenticates via Playwright)
        payload["qa_test_email"] = test_user_email
        payload["qa_test_password"] = test_user_password

    async def _agent_run_qa_tests(self, card_id: str, sandbox_id: str, ctx: dict):
        """Placeholder step for QA tests - the QA agent now creates and runs tests itself.

        Previously this step ran Playwright tests via Docker before the QA agent.
        Now the QA agent is responsible for:
        1. Creating tests scoped to the card's functionality
        2. Executing tests using Playwright MCP tools or bash scripts
        3. Reporting results with screenshots and structured bug reports

        This step is kept for backwards compatibility but does nothing.
        """
        payload = ctx["payload"]
        log_prefix = ctx.get("log_prefix", f"[{card_id[:8]}]")
        agent_name = payload.get("agent_config", {}).get("agent_name", "")

        # Only applies to QA agent
        if agent_name != "qa":
            return

        # QA agent now runs its own tests - no pre-execution needed
        logger.info(f"{log_prefix} QA agent will create and execute tests itself (no pre-execution)")

    async def _agent_run_claude(self, card_id: str, sandbox_id: str, ctx: dict):
        """Run agent CLI subprocess for the agent task."""
        payload = ctx["payload"]
        card_title = payload["card_title"]
        card_description = payload["card_description"]
        column_name = payload["column_name"]
        agent_config = payload.get("agent_config", {})
        agent_name = agent_config.get("agent_name", "developer")
        llm_provider = payload.get("llm_provider") or self._resolve_llm_provider(agent_config)
        llm_model = agent_config.get("llm_model")
        target_project_path = payload["target_project_path"]
        sandbox_slug = payload.get("sandbox_slug", "")
        workspace_slug = payload["workspace_slug"]
        board_id = payload.get("board_id")
        sandbox_url = payload.get("sandbox_url", "")
        sandbox_api_url = payload.get("sandbox_api_url", "")

        # Get agent config values with defaults
        persona = agent_config.get("persona", "")
        tool_profile = agent_config.get("tool_profile", "developer")
        timeout = agent_config.get("timeout", 600)

        # For scrum_master agent, fetch the current board state so it can see all cards
        board_state = None
        if agent_name == "scrum_master" and board_id:
            board_state = await self._fetch_board_state_for_agent(workspace_slug, board_id)

        # Build the prompt for agent CLI using persona from agent config
        # Include sandbox info so agents can link created cards to the same sandbox
        # For QA agent, include test credentials from Key Vault
        qa_credentials = None
        if agent_name == "qa":
            qa_credentials = {
                "email": payload.get("qa_test_email", ""),
                "password": payload.get("qa_test_password", ""),
            }

        prompt = self._build_agent_prompt(
            card_title=card_title,
            card_description=card_description,
            column_name=column_name,
            persona=persona,
            sandbox_id=sandbox_id,
            sandbox_slug=sandbox_slug,
            sandbox_url=sandbox_url,
            sandbox_api_url=sandbox_api_url,
            board_state=board_state,
            qa_credentials=qa_credentials,
        )

        env = None
        if agent_name == "qa":
            # Pass sandbox URLs as env vars for QA agent
            # Credentials are passed in the prompt for browser authentication via Playwright
            env = {
                "QA_SANDBOX_URL": sandbox_url,
                "QA_API_URL": sandbox_api_url,
            }

        # Progress callback for streaming updates
        async def on_progress(message: str, percentage: int):
            # Could stream to card comments here
            logger.debug(f"Agent progress ({percentage}%): {message[:100]}")

        if llm_provider == "codex-cli":
            codex_env = dict(env or {})
            if OPENAI_API_KEY:
                codex_env.setdefault("OPENAI_API_KEY", OPENAI_API_KEY)
            ctx["result"] = await codex_runner.run(
                prompt=prompt,
                working_dir=target_project_path,
                agent_type=agent_name,
                tool_profile=tool_profile,
                timeout=timeout,
                model=llm_model,
                env=codex_env or None,
            )
        else:
            ctx["result"] = await claude_runner.run(
                prompt=prompt,
                working_dir=target_project_path,
                agent_type=agent_name,  # Still used for tool fallback
                tool_profile=tool_profile,
                timeout=timeout,
                session_id=payload.get("claude_session_id"),
                env=env,
            )

        if not ctx["result"].success:
            log_prefix = ctx.get("log_prefix", f"[{card_id[:8]}]")
            logger.error(f"{log_prefix} Agent CLI failed: {ctx['result'].error}")

    async def _agent_process_results(self, card_id: str, sandbox_id: str, ctx: dict):
        """Process results from Claude Code execution."""
        if not ctx["result"]:
            return

        result = ctx["result"]
        payload = ctx["payload"]
        log_prefix = ctx.get("log_prefix", f"[{card_id[:8]}]")
        target_project_path = payload["target_project_path"]
        git_branch = payload["git_branch"]

        # Always check for uncommitted changes on the host via SSH
        repo_path = shlex.quote(str(target_project_path))
        status_lines = []
        status_ok = True
        status_cmd = f"cd {repo_path} && git status --porcelain"
        status_code, status_out, status_err = await claude_runner.run_ssh_command(status_cmd, timeout=30)
        if status_code != 0:
            status_error = status_err.strip() or "git status failed"
            logger.warning(f"{log_prefix} Failed to check git status: {status_error}")
            result.git_dirty = True
            result.commit_error = status_error
            if result.error:
                result.error = f"{result.error}\nCommit error: {status_error}"
            else:
                result.error = f"Commit error: {status_error}"
            result.success = False
            status_ok = False
        else:
            status_lines = [line for line in status_out.splitlines() if line.strip()]

        commit_hash = None
        commit_error = result.commit_error
        push_error = None
        push_attempted = False
        push_success = False
        ahead_count = 0
        push_needed = False

        if status_lines:
            result.git_dirty = True
            changed_files = []
            for line in status_lines:
                path_part = line[3:] if len(line) > 3 else ""
                if " -> " in path_part:
                    path_part = path_part.split(" -> ")[-1]
                if path_part:
                    changed_files.append(path_part)

            if not result.files_modified:
                result.files_modified = changed_files
            else:
                for path in changed_files:
                    if path not in result.files_modified:
                        result.files_modified.append(path)

            commit_message = self._extract_commit_message(result.output)
            if commit_message:
                commit_message = " ".join(commit_message.split())
            else:
                commit_error = "Missing COMMIT_MESSAGE in agent output"

            if commit_message and not commit_error:
                add_cmd = f"cd {repo_path} && git add -A"
                add_code, add_out, add_err = await claude_runner.run_ssh_command(add_cmd, timeout=30)
                if add_code != 0:
                    commit_error = add_err.strip() or add_out.strip() or "git add failed"
                else:
                    commit_cmd = f"cd {repo_path} && git commit -m {shlex.quote(commit_message)}"
                    commit_code, commit_out, commit_err = await claude_runner.run_ssh_command(commit_cmd, timeout=30)
                    if commit_code != 0:
                        commit_error = commit_err.strip() or commit_out.strip() or "git commit failed"
                    else:
                        hash_cmd = f"cd {repo_path} && git rev-parse HEAD"
                        hash_code, hash_out, _ = await claude_runner.run_ssh_command(hash_cmd, timeout=15)
                        if hash_code == 0:
                            commit_hash = hash_out.strip()
                        logger.info(f"{log_prefix} Committed changes ({len(result.files_modified)} files)")

            # Verify working tree is clean after commit attempt
            final_cmd = f"cd {repo_path} && git status --porcelain"
            final_code, final_out, final_err = await claude_runner.run_ssh_command(final_cmd, timeout=30)
            if final_code == 0 and final_out.strip():
                result.git_dirty = True
                if not commit_error:
                    commit_error = "Working tree not clean after commit"
            elif final_code == 0:
                result.git_dirty = False
            else:
                logger.warning(f"{log_prefix} Failed to verify git status: {final_err.strip() or final_out.strip()}")
                if not commit_error:
                    commit_error = f"git status failed after commit: {final_err.strip() or final_out.strip()}"
        elif status_ok:
            result.git_dirty = False

        # Push if there are unpushed commits and no commit errors
        ahead_ref = f"origin/{git_branch}..{git_branch}"
        ahead_cmd = f"cd {repo_path} && git rev-list --count {shlex.quote(ahead_ref)}"
        ahead_code, ahead_out, _ = await claude_runner.run_ssh_command(ahead_cmd, timeout=30)
        if ahead_code == 0:
            ahead_count = int(ahead_out.strip() or "0")
            push_needed = ahead_count > 0
        elif commit_hash:
            push_needed = True

        if commit_hash:
            push_needed = True

        if not commit_error and push_needed:
            push_attempted = True
            push_cmd = f"cd {repo_path} && git push origin {shlex.quote(git_branch)}"
            push_code, push_out, push_err = await claude_runner.run_ssh_command(push_cmd, timeout=60)
            if push_code == 0:
                push_success = True
                logger.info(f"{log_prefix} Pushed changes to {git_branch}")
            else:
                push_error = f"git push failed: {push_err.strip() or push_out.strip()}"

        result.commit_hash = commit_hash
        result.push_attempted = push_attempted
        result.push_success = push_success
        result.commit_error = commit_error
        result.push_error = push_error
        result.push_needed = push_needed
        result.ahead_count = ahead_count

        if commit_error:
            logger.warning(f"{log_prefix} Commit issue: {commit_error}")
            result.commit_error = commit_error
            if result.error:
                result.error = f"{result.error}\nCommit error: {commit_error}"
            else:
                result.error = f"Commit error: {commit_error}"
            result.success = False
        elif push_error:
            logger.warning(f"{log_prefix} Push issue: {push_error}")
            if result.error:
                result.error = f"{result.error}\nPush error: {push_error}"
            else:
                result.error = f"Push error: {push_error}"
            result.success = False

    async def _agent_process_qa_results(self, card_id: str, sandbox_id: str, ctx: dict):
        """Process QA agent results - extract structured issues from output.

        The QA agent now creates and runs tests itself, including its results
        directly in the output. This step extracts any structured issues
        (marked with QA_ISSUES_START/END tags) for the card description.
        """
        payload = ctx["payload"]
        log_prefix = ctx.get("log_prefix", f"[{card_id[:8]}]")
        agent_name = payload.get("agent_config", {}).get("agent_name", "")

        # Only process for QA agent
        if agent_name != "qa":
            return

        result = ctx.get("result")
        if not result or not result.output:
            return

        # Extract structured issues from QA agent output (if present)
        import re
        issues_match = re.search(
            r'<!-- QA_ISSUES_START -->.*?<!-- QA_ISSUES_END -->',
            result.output,
            re.DOTALL
        )

        if issues_match:
            ctx["qa_issues_formatted"] = issues_match.group(0)
            logger.info(f"{log_prefix} Extracted structured QA issues from agent output")
        else:
            ctx["qa_issues_formatted"] = ""
            logger.info(f"{log_prefix} No structured QA issues found in agent output")

    async def _agent_update_card(self, card_id: str, sandbox_id: str, ctx: dict):
        """Update the kanban card with agent results."""
        if not ctx["result"]:
            return

        result = ctx["result"]
        payload = ctx["payload"]
        log_prefix = ctx.get("log_prefix", f"[{card_id[:8]}]")
        workspace_slug = payload["workspace_slug"]
        # Use internal Docker network URL for service-to-service calls
        kanban_api_url = f"http://{workspace_slug}-kanban-api-1:8000"
        git_branch = payload["git_branch"]
        session_id = payload.get("claude_session_id")

        # Build comment content
        agent_config = payload.get("agent_config", {})
        agent_name = agent_config.get("agent_name", "agent")
        display_name = agent_config.get("display_name", agent_name)
        column_success = agent_config.get("column_success")
        column_failure = agent_config.get("column_failure")

        if result.success:
            comment = f"## Agent: {display_name}\n\n"
            comment += f"**Status:** Completed\n"
            comment += f"**Duration:** {result.duration_seconds:.1f}s\n"
            comment += f"**Branch:** `{git_branch}`\n"
            if session_id:
                comment += f"**Session:** `{session_id}`\n"
            if result.commit_hash:
                comment += f"**Commit:** `{result.commit_hash}`\n"
            if result.push_attempted:
                if result.push_success:
                    comment += f"**Push:** Success\n"
                else:
                    push_error = result.push_error or "Unknown error"
                    comment += f"**Push:** Failed ({push_error})\n"
            elif result.push_needed:
                if result.ahead_count > 0:
                    comment += f"**Push:** Pending ({result.ahead_count} commits ahead, no token)\n"
                else:
                    comment += f"**Push:** Pending (no token)\n"
            elif result.commit_hash:
                comment += f"**Push:** Skipped (no token)\n"
            comment += f"**Git Status:** {'Dirty' if result.git_dirty else 'Clean'}\n"
            if result.files_modified:
                comment += f"\n**Files Modified:**\n"
                for f in result.files_modified[:10]:
                    comment += f"- `{f}`\n"
            else:
                comment += f"\n**Files Modified:** None detected\n"
            if result.output:
                # Include summary of what was done
                output_summary = result.output[:1000] if len(result.output) > 1000 else result.output
                comment += f"\n**Summary:**\n{output_summary}\n"
        else:
            comment = f"## Agent: {display_name}\n\n"
            comment += f"**Status:** Failed\n"
            comment += f"**Error:** {result.error}\n"
            if session_id:
                comment += f"\n**Session:** `{session_id}`\n"
            if result.commit_hash:
                comment += f"\n**Commit:** `{result.commit_hash}`\n"
            if result.push_attempted:
                if result.push_success:
                    comment += f"**Push:** Success\n"
                else:
                    push_error = result.push_error or "Unknown error"
                    comment += f"**Push:** Failed ({push_error})\n"
            elif result.push_needed:
                if result.ahead_count > 0:
                    comment += f"**Push:** Pending ({result.ahead_count} commits ahead, no token)\n"
                else:
                    comment += f"**Push:** Pending (no token)\n"
            elif result.commit_hash:
                comment += f"**Push:** Skipped (no token)\n"
            comment += f"**Git Status:** {'Dirty' if result.git_dirty else 'Clean'}\n"
            comment += f"\nPlease review and retry."

        logger.info(f"Card update for {card_id}: {comment[:200]}...")

        # Actually POST the comment to the kanban API
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Add comment to card (API expects 'text' field)
                response = await client.post(
                    f"{kanban_api_url}/cards/{card_id}/comments",
                    headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")},
                    json={"text": comment, "author_name": f"Agent: {display_name}"}
                )
                if response.status_code not in [200, 201]:
                    logger.warning(f"Failed to add comment: {response.status_code} - {response.text}")

                # Get current card to update description
                card_response = await client.get(
                    f"{kanban_api_url}/cards/{card_id}",
                    headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")}
                )

                # Update card description - for successful agents or QA agent (always update with issues)
                qa_issues_formatted = ctx.get("qa_issues_formatted", "")
                should_update_description = (
                    card_response.status_code == 200 and
                    (result.success and result.output) or
                    (agent_name == "qa" and qa_issues_formatted)
                )

                if should_update_description:
                    card_data = card_response.json()
                    current_description = card_data.get("description", "") or ""

                    # Build agent output section
                    agent_section = f"\n\n---\n\n## Agent: {display_name}\n\n"

                    # For QA agent, include structured issues for developer
                    if agent_name == "qa" and qa_issues_formatted:
                        agent_section += qa_issues_formatted + "\n\n"

                    # Truncate output if too long
                    if result.output:
                        output_text = result.output[:2000] if len(result.output) > 2000 else result.output
                        agent_section += output_text

                    # Check if this agent's section already exists and remove it
                    section_marker = f"## Agent: {display_name}"
                    if section_marker in current_description:
                        # Find this agent's section and remove just it (not other agent sections after)
                        import re
                        # Pattern matches from this agent's marker to the next agent marker or end
                        # The ---\n\n before the section is also part of the section to remove
                        pattern = r'(\n*---\n*)?## Agent: ' + re.escape(display_name) + r'.*?(?=\n---\n\n## Agent:|$)'
                        current_description = re.sub(pattern, '', current_description, flags=re.DOTALL)
                        current_description = current_description.rstrip()

                    # Also remove any existing QA_ISSUES section to avoid duplication
                    if "<!-- QA_ISSUES_START -->" in current_description:
                        import re
                        current_description = re.sub(
                            r'<!-- QA_ISSUES_START -->.*?<!-- QA_ISSUES_END -->',
                            '',
                            current_description,
                            flags=re.DOTALL
                        )
                        current_description = current_description.rstrip()

                    new_description = current_description + agent_section

                    # Update card with new description
                    desc_response = await client.patch(
                        f"{kanban_api_url}/cards/{card_id}",
                        headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")},
                        json={"description": new_description}
                    )
                    if desc_response.status_code == 200:
                        logger.info(f"Updated card description with agent output")
                    else:
                        logger.warning(f"Failed to update description: {desc_response.status_code}")

                # Special handling for project_manager agent: create epics and cards
                if agent_name == "project_manager" and result.success:
                    await self._handle_project_manager_output(card_id, sandbox_id, ctx)

                # Get board_id for card movements (needed by scrum_master and column moves)
                board_id = payload.get("board_id")

                # Special handling for scrum_master agent: move next card from project plan
                if agent_name == "scrum_master" and result.success and board_id:
                    await self._handle_scrum_master_output(card_id, kanban_api_url, board_id, ctx)

                # Check if we should move the card
                # Skip move if user manually moved the card to another column while agent was running
                original_column_name = payload.get("column_name", "")
                should_move_card = True

                if board_id and (column_success or column_failure):
                    # Fetch current card state to check its column
                    card_resp = await client.get(
                        f"{kanban_api_url}/cards/{card_id}",
                        headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")}
                    )
                    if card_resp.status_code == 200:
                        card_data = card_resp.json()
                        current_column = card_data.get("column", {})
                        current_column_name = current_column.get("name", "")

                        if current_column_name and current_column_name != original_column_name:
                            logger.info(
                                f"{log_prefix} Card was moved by user from '{original_column_name}' to "
                                f"'{current_column_name}' while agent was running - skipping automatic move"
                            )
                            should_move_card = False

                # If successful and column_success is set, move the card
                if result.success and column_success and should_move_card:
                    if board_id:
                        board_resp = await client.get(
                            f"{kanban_api_url}/boards/{board_id}",
                            headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")}
                        )
                        if board_resp.status_code == 200:
                            board_data = board_resp.json()
                            for col in board_data.get("columns", []):
                                if col.get("name") == column_success:
                                    move_resp = await client.post(
                                        f"{kanban_api_url}/cards/{card_id}/move",
                                        headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")},
                                        params={"column_id": col["id"], "position": 0}
                                    )
                                    if move_resp.status_code == 200:
                                        logger.info(f"Moved card to column: {column_success}")
                                    break

                # If failed and column_failure is set, move the card there
                elif not result.success and column_failure and should_move_card:
                    if board_id:
                        board_resp = await client.get(
                            f"{kanban_api_url}/boards/{board_id}",
                            headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")}
                        )
                        if board_resp.status_code == 200:
                            board_data = board_resp.json()
                            for col in board_data.get("columns", []):
                                if col.get("name") == column_failure:
                                    move_resp = await client.post(
                                        f"{kanban_api_url}/cards/{card_id}/move",
                                        headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")},
                                        params={"column_id": col["id"], "position": 0}
                                    )
                                    if move_resp.status_code == 200:
                                        logger.info(f"Moved card to column: {column_failure}")
                                    break

                # Clear the agent_status now that processing is complete
                # (we clear it rather than setting to completed/failed because
                # the card description and comment already show the result)
                # Pass task_id to prevent race condition where a new task has already started
                task_id = ctx.get("task_id")
                clear_resp = await client.delete(
                    f"{kanban_api_url}/cards/{card_id}/agent-status",
                    headers={"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")},
                    params={"task_id": task_id} if task_id else None
                )
                if clear_resp.status_code == 200:
                    clear_data = clear_resp.json()
                    if clear_data.get("cleared"):
                        logger.info(f"{log_prefix} Cleared agent_status")
                    else:
                        logger.info(f"{log_prefix} Skipped clearing agent_status (task_id mismatch - new task already started)")
                else:
                    logger.warning(f"{log_prefix} Failed to clear agent_status: {clear_resp.status_code}")

        except Exception as e:
            logger.error(f"Error updating card via API: {e}")

    async def _fetch_board_state_for_agent(self, workspace_slug: str, board_id: str) -> str:
        """Fetch current board state for agents like scrum_master that need to see all cards.

        Returns a formatted string showing all columns and their cards.
        """
        kanban_api_url = f"http://{workspace_slug}-kanban-api-1:8000"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")}
                board_resp = await client.get(
                    f"{kanban_api_url}/boards/{board_id}",
                    headers=headers
                )

                if board_resp.status_code != 200:
                    logger.warning(f"Failed to fetch board state: {board_resp.status_code}")
                    return None

                board_data = board_resp.json()
                columns = board_data.get("columns", [])

                # Build a readable summary of all cards and their columns
                lines = ["Below is the current state of all cards on the kanban board:\n"]

                for col in columns:
                    col_name = col.get("name", "Unknown")
                    cards = col.get("cards", [])
                    lines.append(f"### Column: {col_name}")

                    if not cards:
                        lines.append("  (empty)\n")
                    else:
                        for card in cards:
                            card_title = card.get("title", "Untitled")
                            card_id = card.get("id", "")[:8]
                            lines.append(f"  - [{card_id}] {card_title}")
                        lines.append("")

                lines.append("\nUse this information to identify which cards are already Done,")
                lines.append("which are in progress, and which are still waiting in Backlog.")

                return "\n".join(lines)

        except Exception as e:
            logger.error(f"Error fetching board state: {e}")
            return None

    def _build_agent_prompt(
        self,
        card_title: str,
        card_description: str,
        column_name: str,
        persona: str = "",
        sandbox_id: str = "",
        sandbox_slug: str = "",
        sandbox_url: str = "",
        sandbox_api_url: str = "",
        board_state: str = None,
        qa_credentials: dict = None,
    ) -> str:
        """Build the prompt for the agent CLI using persona from kanban-team.

        Args:
            card_title: The card title
            card_description: The card description/requirements
            column_name: Current column name
            persona: Agent persona/instructions from kanban-team config
            sandbox_id: The sandbox ID this card is linked to
            sandbox_slug: The sandbox slug for reference
            sandbox_url: Public sandbox URL for runtime validation
            sandbox_api_url: Public sandbox API base URL
            board_state: Current kanban board state (for scrum_master)
            qa_credentials: Test credentials for QA agent (email, password)
        """
        # Use persona from config, or a generic fallback
        if not persona:
            persona = "Process this card according to your role."

        # Build context section with sandbox info
        context_section = ""
        if sandbox_id or sandbox_slug or sandbox_url:
            context_section = f"""
## Card Context:
- Sandbox ID: {sandbox_id}
- Sandbox Slug: {sandbox_slug}
{f"- Sandbox URL: {sandbox_url}" if sandbox_url else ""}
{f"- Sandbox API: {sandbox_api_url}" if sandbox_api_url else ""}
IMPORTANT: When creating project plans or cards, use this sandbox_id to link them to the same sandbox.
"""

        # Add board state for scrum_master (so it can see all cards and their columns)
        board_state_section = ""
        if board_state:
            board_state_section = f"""
## Current Kanban Board State:
{board_state}
"""

        # Add QA test credentials section for QA agent
        qa_credentials_section = ""
        if qa_credentials:
            qa_credentials_section = f"""
## Test Credentials:
Use these credentials to test the sandbox application:
- Email: {qa_credentials.get("email", "")}
- Password: {qa_credentials.get("password", "")}
"""

        prompt = f"""# Task: {card_title}

## Column: {column_name}

## Description:
{card_description}
{context_section}{board_state_section}{qa_credentials_section}
## Agent Instructions:
{persona}

## Commit Instructions:
- Do NOT run git commit/push commands.
- If you modified files, include a single line at the end of your response:
  `COMMIT_MESSAGE: <type>: <short description>`

## Progress Tracking:
You MUST track your progress in `docs/Backlog.json`:
1. Read `docs/Backlog.json` at the start to understand current project state
2. Update task status as you progress (todo → in_progress → done)
3. Add new tasks discovered during work to the backlog
4. Save changes to `docs/Backlog.json` after completing tasks

Please complete this task. Update files as needed and explain what you did."""

        return prompt

    # =========================================================================
    # Enhance Description Task (On-demand AI)
    # =========================================================================

    async def enhance_description_task(self, task: dict):
        """Enhance a card's description using Claude Code subprocess.

        This method:
        1. Calls Claude Code to analyze the card
        2. Generates enhanced description, acceptance criteria, etc.
        3. Returns results to kanban-team via API call
        """
        task_id = task["task_id"]
        payload = task["payload"]
        card_id = payload["card_id"]
        card_title = payload["card_title"]
        card_description = payload["card_description"]
        workspace_slug = payload["workspace_slug"]
        kanban_api_url = payload["kanban_api_url"]
        options = payload.get("options", {})
        mode = payload.get("mode", "append")
        apply_labels = payload.get("apply_labels", True)
        add_checklist = payload.get("add_checklist", True)

        logger.info(f"Enhancing description: card={card_id}, workspace={workspace_slug}")

        steps = [
            ("Analyzing card content", self._enhance_analyze),
            ("Generating enhancements", self._enhance_generate),
            ("Updating card", self._enhance_update_card),
        ]

        # Store payload for step functions
        self._current_payload = payload
        self._enhance_result = None

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(card_id)
                logger.info(f"[{card_id}] {step_name} - completed")

            await self.complete_task(task_id, {
                "action": "enhance_description",
                "card_id": card_id,
                "success": True,
                "result": self._enhance_result,
            })

            logger.info(f"Enhance description completed: card={card_id}")

        except Exception as e:
            logger.error(f"Enhance description failed: {e}")
            await self.fail_task(task_id, str(e))
            raise

    async def _enhance_analyze(self, card_id: str):
        """Analyze the card content."""
        # This step is mainly for progress indication
        pass

    async def _enhance_generate(self, card_id: str):
        """Generate enhanced content using Claude Code CLI."""
        payload = self._current_payload
        card_title = payload["card_title"]
        card_description = payload["card_description"]
        workspace_slug = payload["workspace_slug"]
        options = payload.get("options", {})

        # Determine the working directory for codebase context
        # Try sandbox path first, fall back to workspace repo
        sandbox_slug = payload.get("sandbox_slug")
        if sandbox_slug:
            working_dir = f"/data/repos/{workspace_slug}/sandboxes/{sandbox_slug}"
        else:
            working_dir = f"/data/repos/{workspace_slug}"

        # Verify the path exists, fallback to cwd if not
        if not Path(working_dir).exists():
            logger.warning(f"Working dir {working_dir} doesn't exist, using cwd")
            working_dir = str(Path.cwd())

        logger.info(f"Enhance description using working_dir: {working_dir}")

        # Build the enhancement prompt
        prompt = self._build_enhance_prompt(card_title, card_description, options)

        # Run Claude Code CLI with readonly tools (can read codebase for context)
        result = await claude_runner.run(
            prompt=prompt,
            working_dir=working_dir,
            agent_type="product_owner",
            tool_profile="readonly",
            timeout=180,  # 3 minutes to allow for codebase analysis
        )

        if not result.success:
            raise RuntimeError(f"Claude Code failed: {result.error}")

        # Parse the JSON output from Claude's response
        self._enhance_result = self._parse_enhance_output(result.output)

    async def _enhance_update_card(self, card_id: str):
        """Update the card via kanban-team API."""
        if not self._enhance_result:
            logger.warning("No enhancement result to apply")
            return

        payload = self._current_payload
        workspace_slug = payload["workspace_slug"]
        mode = payload.get("mode", "append")
        apply_labels = payload.get("apply_labels", True)
        add_checklist = payload.get("add_checklist", True)

        result = self._enhance_result
        logger.info(f"Enhancement result: {result}")

        # Build the update payload
        update_data = {
            "enhanced_description": result.get("enhanced_description", ""),
            "acceptance_criteria": result.get("acceptance_criteria", []) if add_checklist else [],
            "complexity": result.get("complexity", ""),
            "complexity_reason": result.get("complexity_reason", ""),
            "suggested_labels": result.get("suggested_labels", []) if apply_labels else [],
        }

        logger.info(f"Sending update_data with description length: {len(update_data.get('enhanced_description', ''))}, mode={mode}")

        # Use internal Docker network URL to bypass external auth
        internal_api_url = f"http://{workspace_slug}-kanban-api-1:8000"

        # Call kanban-team API to apply changes
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{internal_api_url}/cards/{card_id}/apply-enhancement",
                    headers={"X-Service-Secret": CROSS_DOMAIN_SECRET},
                    json={
                        "mode": mode,
                        "apply_labels": apply_labels,
                        "add_checklist": add_checklist,
                        **update_data,
                    }
                )
                logger.info(f"Apply enhancement response: {response.status_code}")
                logger.info(f"Response body: {response.text}")
                if response.status_code != 200:
                    logger.warning(f"Failed to apply enhancement: {response.text}")
        except Exception as e:
            logger.error(f"Error calling kanban-team API: {e}")

    def _build_enhance_prompt(
        self,
        card_title: str,
        card_description: str,
        options: dict,
    ) -> str:
        """Build the prompt for enhancing card description."""
        features = []
        if options.get("refine_description", True):
            features.append("- Refine and improve the description for clarity")
        if options.get("acceptance_criteria", True):
            features.append("- Generate acceptance criteria as a list of testable requirements")
        if options.get("complexity_estimate", True):
            features.append("- Estimate complexity (low, medium, high) with a brief reason")
        if options.get("suggest_labels", True):
            features.append("- Suggest appropriate labels (e.g., bug, feature, enhancement, documentation)")

        features_text = "\n".join(features)

        prompt = f"""Analyze this kanban card and enhance it.

## FIRST STEP - ANALYZE THE CODEBASE (MANDATORY)
Before enhancing the card, you MUST explore the codebase to understand the project context:
1. Read the project structure to understand the application architecture
2. Look for existing features, components, and patterns related to this card
3. Check for similar implementations that can inform your analysis
4. Identify the tech stack, conventions, and coding patterns

Use this codebase knowledge to:
- Write more accurate and specific acceptance criteria that reference actual components/pages
- Provide realistic complexity estimates based on the actual codebase
- Suggest labels that match the project's conventions
- Reference actual file paths or components when relevant

## Card Title
{card_title}

## Current Description
{card_description or "(No description provided)"}

## Tasks
{features_text}

## Output Format
After analyzing the codebase, respond with ONLY a JSON object in this exact format (no markdown, no code blocks):
{{
  "enhanced_description": "The improved description text (reference actual components/pages from codebase when relevant)",
  "acceptance_criteria": ["Specific criterion referencing actual codebase elements", "Another testable requirement", "..."],
  "complexity": "low|medium|high",
  "complexity_reason": "Brief explanation based on actual codebase analysis",
  "suggested_labels": ["label1", "label2"]
}}

Be concise but thorough. Base your analysis on what you found in the codebase."""

        return prompt

    def _parse_project_plan_output(self, output: str) -> Optional[dict]:
        """Parse Claude output to extract project plan JSON from project_manager agent."""
        import re

        logger.info(f"Parsing project plan output ({len(output)} chars)")
        logger.info(f"Raw output preview: {output[:1000]}...")

        if not output or not output.strip():
            logger.warning("Empty output from project_manager agent")
            return None

        # Try to find JSON block in the output - look for outermost braces
        first_brace = output.find('{')
        last_brace = output.rfind('}')

        if first_brace != -1 and last_brace > first_brace:
            json_str = output[first_brace:last_brace + 1]
            logger.info(f"Found JSON block from pos {first_brace} to {last_brace}")
            try:
                result = json.loads(json_str)
                logger.info(f"Parsed JSON keys: {list(result.keys())}")
                if "epics" in result:
                    logger.info(f"Successfully parsed project plan with {len(result.get('epics', []))} epics")
                    return result
                else:
                    logger.warning(f"JSON parsed but no 'epics' key found. Keys: {list(result.keys())}")
                    # Return anyway if it has project_summary - might be a valid plan
                    if "project_summary" in result:
                        logger.info("Found project_summary, returning result anyway")
                        return result
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON block: {e}")
                logger.warning(f"JSON string that failed: {json_str[:500]}...")

        # Try parsing the whole output as JSON
        try:
            result = json.loads(output.strip())
            logger.info(f"Parsed whole output as JSON. Keys: {list(result.keys())}")
            if "epics" in result:
                return result
        except json.JSONDecodeError:
            pass

        # Try to find JSON in code blocks
        code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', output, re.DOTALL)
        if code_block_match:
            try:
                result = json.loads(code_block_match.group(1))
                logger.info(f"Parsed JSON from code block. Keys: {list(result.keys())}")
                if "epics" in result:
                    return result
            except json.JSONDecodeError:
                pass

        logger.warning("Could not parse project plan JSON from Claude output")
        logger.warning(f"Full output was: {output[:2000]}")
        return None

    async def _handle_project_manager_output(self, card_id: str, sandbox_id: str, ctx: dict):
        """Handle project_manager agent output: create epics and cards on Feature Request board."""
        logger.info(f"[{card_id}] _handle_project_manager_output called")

        if not ctx["result"]:
            logger.warning(f"[{card_id}] No agent result available")
            return

        payload = ctx["payload"]
        workspace_slug = payload["workspace_slug"]
        board_id = payload.get("board_id")
        kanban_api_url = f"http://{workspace_slug}-kanban-api-1:8000"
        target_project_path = payload.get("target_project_path", "")

        # Try to parse from agent output first
        result = ctx["result"]
        project_plan = None
        if result.output:
            logger.info(f"[{card_id}] Agent output length: {len(result.output)} chars")
            project_plan = self._parse_project_plan_output(result.output)

        # If parsing failed, check for PROJECT_PLAN.json file in repo
        if not project_plan and target_project_path:
            plan_file_paths = [
                Path(target_project_path) / "docs" / "PROJECT_PLAN.json",
                Path(target_project_path) / "PROJECT_PLAN.json",
            ]
            for plan_file in plan_file_paths:
                if plan_file.exists():
                    logger.info(f"[{card_id}] Found project plan file: {plan_file}")
                    try:
                        with open(plan_file, 'r') as f:
                            project_plan = json.load(f)
                        logger.info(f"[{card_id}] Loaded project plan from file with {len(project_plan.get('epics', []))} epics")
                        break
                    except Exception as e:
                        logger.warning(f"[{card_id}] Failed to read plan file: {e}")
        if not project_plan or not project_plan.get("epics"):
            logger.warning(f"[{card_id}] No valid project plan in output")
            return

        logger.info(f"[{card_id}] Processing project plan with {len(project_plan['epics'])} epics")

        # ALWAYS use the sandbox_id from the original task (passed as parameter)
        # Don't trust project plan's sandbox_id - agent might write wrong value (e.g., full_slug instead of UUID)
        # The task's sandbox_id is guaranteed to be correct (comes from the source card via webhook)
        original_sandbox_id = sandbox_id
        plan_sandbox_id = project_plan.get("sandbox_id")
        if plan_sandbox_id:
            logger.info(f"[{card_id}] Project plan has sandbox_id: {plan_sandbox_id} (ignoring, using task's sandbox_id)")

        # Validate sandbox_id looks like a UUID (contains dashes, ~36 chars)
        if not sandbox_id or '-' not in sandbox_id or len(sandbox_id) < 30:
            logger.error(f"[{card_id}] Invalid sandbox_id format: {sandbox_id} - expected UUID format")
            return

        logger.info(f"[{card_id}] Creating cards with sandbox_id: {sandbox_id} (original task sandbox_id)")
        logger.info(f"[{card_id}] First card to move: {project_plan.get('first_card', 'NOT SPECIFIED')}")

        created_epics = {}  # epic_name -> epic_id
        total_cards_created = 0

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")}

                # 1. Find Feature Request board
                boards_resp = await client.get(f"{kanban_api_url}/boards", headers=headers)
                feature_board = None
                if boards_resp.status_code == 200:
                    for board in boards_resp.json():
                        if "Feature Request" in board.get("name", ""):
                            board_resp = await client.get(
                                f"{kanban_api_url}/boards/{board['id']}", headers=headers
                            )
                            if board_resp.status_code == 200:
                                feature_board = board_resp.json()
                                logger.info(f"[{card_id}] Found Feature Request board: {feature_board['id']}")
                                break

                if not feature_board:
                    logger.error(f"[{card_id}] Feature Request board not found in workspace")
                    return

                # Find first column (Feature Request column)
                columns = sorted(feature_board.get("columns", []), key=lambda c: c.get("position", 0))
                first_column_id = columns[0]["id"] if columns else None

                if not first_column_id:
                    logger.error(f"[{card_id}] No columns in Feature Request board")
                    return

                # 2. Create epics on Ideas Pipeline board (where the idea card is)
                for epic_data in project_plan["epics"]:
                    epic_resp = await client.post(
                        f"{kanban_api_url}/epics",
                        headers=headers,
                        json={
                            "board_id": board_id,
                            "name": epic_data["name"],
                            "description": epic_data.get("description", ""),
                            "color": epic_data.get("color", "#6366f1"),
                            "status": "open",
                        }
                    )
                    if epic_resp.status_code in [200, 201]:
                        epic = epic_resp.json()
                        created_epics[epic_data["name"]] = epic["id"]
                        logger.info(f"[{card_id}] Created epic: {epic['name']} ({epic['id']})")
                    else:
                        logger.warning(f"[{card_id}] Failed to create epic: {epic_resp.status_code}")

                # 3. Create cards on Feature Request board
                created_cards = {}  # title -> card_id mapping
                for epic_data in project_plan["epics"]:
                    epic_id = created_epics.get(epic_data["name"])

                    for i, card_data in enumerate(epic_data.get("cards", [])):
                        # Build card description with metadata
                        description = card_data.get("description", "")
                        description += f"\n\n---\n**Priority:** {card_data.get('priority', 'P2')}"
                        description += f"\n**Complexity:** {card_data.get('complexity', 'M')}"
                        if card_data.get("depends_on"):
                            description += f"\n**Depends on:** {', '.join(card_data['depends_on'])}"
                        description += f"\n**Epic:** {epic_data['name']}"

                        card_resp = await client.post(
                            f"{kanban_api_url}/cards",
                            headers=headers,
                            json={
                                "column_id": first_column_id,
                                "title": card_data["title"],
                                "description": description,
                                "position": i,
                                "labels": card_data.get("labels", []),
                                "priority": card_data.get("priority"),
                                "sandbox_id": sandbox_id,
                                "epic_id": epic_id,
                            }
                        )
                        if card_resp.status_code in [200, 201]:
                            total_cards_created += 1
                            created_card = card_resp.json()
                            created_cards[card_data["title"]] = created_card["id"]
                            logger.info(f"[{card_id}] Created card: {card_data['title']} ({created_card['id']})")
                        else:
                            logger.warning(f"[{card_id}] Failed to create card: {card_resp.status_code}")

                # 4. Update original idea card with project plan summary
                summary = f"\n\n---\n\n## Project Plan Created\n\n"
                summary += f"**Summary:** {project_plan.get('project_summary', '')}\n\n"
                summary += f"### Epics ({len(created_epics)})\n"
                for epic_name in created_epics:
                    epic_data = next((e for e in project_plan["epics"] if e["name"] == epic_name), {})
                    summary += f"- **{epic_name}** ({len(epic_data.get('cards', []))} cards)\n"

                if project_plan.get("execution_notes"):
                    summary += f"\n### Execution Notes\n{project_plan['execution_notes']}\n"

                if project_plan.get("risks"):
                    summary += f"\n### Risks\n"
                    for risk in project_plan["risks"]:
                        summary += f"- {risk}\n"

                summary += f"\n**Total Cards Created:** {total_cards_created} on Feature Request board\n"

                card_resp = await client.get(f"{kanban_api_url}/cards/{card_id}", headers=headers)
                if card_resp.status_code == 200:
                    current = card_resp.json().get("description", "") or ""
                    await client.patch(
                        f"{kanban_api_url}/cards/{card_id}",
                        headers=headers,
                        json={"description": current + summary}
                    )

                # 5. Add completion comment
                await client.post(
                    f"{kanban_api_url}/cards/{card_id}/comments",
                    headers=headers,
                    json={
                        "text": f"Project plan created: {len(created_epics)} epics with {total_cards_created} cards on Feature Request board.",
                        "author_name": "Agent: Project Manager"
                    }
                )

                logger.info(f"[{card_id}] Project plan processing complete: {len(created_epics)} epics, {total_cards_created} cards")

                # 6. Move first card to UI/UX Design column
                first_card_title = project_plan.get("first_card")
                if first_card_title and first_card_title in created_cards:
                    first_card_id = created_cards[first_card_title]

                    # Find UI/UX Design column
                    ux_column_id = None
                    for col in columns:
                        if col.get("name") == "UI/UX Design":
                            ux_column_id = col["id"]
                            break

                    if ux_column_id:
                        move_resp = await client.post(
                            f"{kanban_api_url}/cards/{first_card_id}/move",
                            headers=headers,
                            params={"column_id": ux_column_id, "position": 0}
                        )
                        if move_resp.status_code == 200:
                            logger.info(f"[{card_id}] Moved first card '{first_card_title}' to UI/UX Design")

                            # Add comment to the moved card
                            await client.post(
                                f"{kanban_api_url}/cards/{first_card_id}/comments",
                                headers=headers,
                                json={
                                    "text": "Automatically moved to UI/UX Design as the first card to start development.",
                                    "author_name": "Agent: Project Manager"
                                }
                            )
                        else:
                            logger.warning(f"[{card_id}] Failed to move first card: {move_resp.status_code}")
                    else:
                        logger.warning(f"[{card_id}] UI/UX Design column not found")
                elif first_card_title:
                    logger.warning(f"[{card_id}] First card '{first_card_title}' not found in created cards")

        except Exception as e:
            logger.error(f"[{card_id}] Error handling project manager output: {e}")

    async def _handle_scrum_master_output(self, card_id: str, kanban_api_url: str, board_id: str, ctx: dict):
        """Handle scrum_master agent output: move next card to UI/UX Design column.

        The scrum_master agent outputs a JSON block specifying which card to move:
        {
            "action": "MOVE_CARD",
            "card_title": "Card title to find and move",
            "target_column": "UI/UX Design",
            "reason": "Explanation"
        }
        """
        logger.info(f"[{card_id}] _handle_scrum_master_output called")

        if not ctx["result"]:
            logger.warning(f"[{card_id}] No agent result available for scrum_master")
            return

        # Parse JSON from agent output
        output = ctx["result"].output
        action_data = self._parse_scrum_master_action(output)

        if not action_data:
            logger.warning(f"[{card_id}] Could not parse action from scrum_master output")
            return

        action = action_data.get("action")
        logger.info(f"[{card_id}] Scrum master action: {action}")

        if action == "PROJECT_COMPLETE":
            logger.info(f"[{card_id}] Project complete: {action_data.get('message')}")
            return

        if action == "NO_PROJECT_PLAN":
            logger.info(f"[{card_id}] No project plan found: {action_data.get('message')}")
            return

        if action == "CARDS_IN_PROGRESS":
            in_progress = action_data.get("in_progress_cards", [])
            logger.info(f"[{card_id}] Cards in progress, waiting for completion: {in_progress}")
            return

        if action != "MOVE_CARD":
            logger.warning(f"[{card_id}] Unknown scrum_master action: {action}")
            return

        card_title = action_data.get("card_title")
        target_column = action_data.get("target_column", "UI/UX Design")
        reason = action_data.get("reason", "")

        if not card_title:
            logger.warning(f"[{card_id}] No card_title in MOVE_CARD action")
            return

        logger.info(f"[{card_id}] Moving card '{card_title}' to '{target_column}': {reason}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"X-Service-Secret": os.environ.get("CROSS_DOMAIN_SECRET", "")}

                # Get board data to find columns and cards
                board_resp = await client.get(
                    f"{kanban_api_url}/boards/{board_id}",
                    headers=headers
                )

                if board_resp.status_code != 200:
                    logger.error(f"[{card_id}] Failed to get board: {board_resp.status_code}")
                    return

                board_data = board_resp.json()
                columns = board_data.get("columns", [])

                # Find the target column ID
                target_column_id = None
                for col in columns:
                    if col.get("name") == target_column:
                        target_column_id = col["id"]
                        break

                if not target_column_id:
                    logger.error(f"[{card_id}] Target column '{target_column}' not found in board")
                    return

                # Search for the card by title across all columns
                target_card_id = None
                for col in columns:
                    for c in col.get("cards", []):
                        if c.get("title") == card_title:
                            target_card_id = c["id"]
                            logger.info(f"[{card_id}] Found card '{card_title}' with ID {target_card_id}")
                            break
                    if target_card_id:
                        break

                if not target_card_id:
                    # Try searching via API
                    logger.info(f"[{card_id}] Card not found in board data, trying API search...")
                    search_resp = await client.get(
                        f"{kanban_api_url}/cards",
                        params={"board_id": board_id, "search": card_title},
                        headers=headers
                    )
                    if search_resp.status_code == 200:
                        cards = search_resp.json()
                        for c in cards:
                            if c.get("title") == card_title:
                                target_card_id = c["id"]
                                break

                if not target_card_id:
                    logger.warning(f"[{card_id}] Card '{card_title}' not found")
                    return

                # Move the card to the target column
                move_resp = await client.post(
                    f"{kanban_api_url}/cards/{target_card_id}/move",
                    headers=headers,
                    params={"column_id": target_column_id, "position": 0}
                )

                if move_resp.status_code == 200:
                    logger.info(f"[{card_id}] Successfully moved card '{card_title}' to '{target_column}'")

                    # Add a comment to the moved card explaining why
                    await client.post(
                        f"{kanban_api_url}/cards/{target_card_id}/comments",
                        headers=headers,
                        json={
                            "text": f"Moved to {target_column} by Scrum Master.\n\nReason: {reason}",
                            "author_name": "Agent: Scrum Master"
                        }
                    )
                else:
                    logger.error(f"[{card_id}] Failed to move card: {move_resp.status_code}")

        except Exception as e:
            logger.error(f"[{card_id}] Error in scrum_master handler: {e}")

    def _parse_scrum_master_action(self, output: str) -> Optional[dict]:
        """Parse the scrum_master agent output to extract the action JSON."""
        import re

        if not output:
            return None

        # Try to find JSON block in code block first
        code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', output, re.DOTALL)
        if code_block_match:
            try:
                result = json.loads(code_block_match.group(1))
                if "action" in result:
                    return result
            except json.JSONDecodeError:
                pass

        # Try to find JSON with action key anywhere in output
        # Note: CARDS_IN_PROGRESS has nested array, so it uses the fallback JSON parser below
        action_patterns = [
            r'\{\s*"action"\s*:\s*"MOVE_CARD"[^}]+\}',
            r'\{\s*"action"\s*:\s*"PROJECT_COMPLETE"[^}]+\}',
            r'\{\s*"action"\s*:\s*"NO_PROJECT_PLAN"[^}]+\}',
            r'\{\s*"action"\s*:\s*"CARDS_IN_PROGRESS"[^}]+\}',
        ]

        for pattern in action_patterns:
            match = re.search(pattern, output, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group(0))
                    return result
                except json.JSONDecodeError:
                    continue

        # Try to find any JSON object with "action" key
        first_brace = output.find('{')
        while first_brace != -1:
            # Find matching closing brace
            depth = 0
            for i in range(first_brace, len(output)):
                if output[i] == '{':
                    depth += 1
                elif output[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            candidate = output[first_brace:i+1]
                            result = json.loads(candidate)
                            if "action" in result:
                                return result
                        except json.JSONDecodeError:
                            pass
                        break
            first_brace = output.find('{', first_brace + 1)

        return None

    def _extract_commit_message(self, output: str) -> Optional[str]:
        """Extract COMMIT_MESSAGE from agent output."""
        import re

        if not output:
            return None

        line_match = re.search(r'^\s*COMMIT_MESSAGE\s*:\s*(.+)$', output, re.MULTILINE)
        if line_match:
            return line_match.group(1).strip().strip('"')

        code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', output, re.DOTALL)
        if code_block_match:
            try:
                result = json.loads(code_block_match.group(1))
                if isinstance(result, dict) and result.get("commit_message"):
                    return str(result["commit_message"]).strip()
            except json.JSONDecodeError:
                pass

        try:
            result = json.loads(output.strip())
            if isinstance(result, dict) and result.get("commit_message"):
                return str(result["commit_message"]).strip()
        except json.JSONDecodeError:
            pass

        return None

    def _parse_enhance_output(self, output: str) -> dict:
        """Parse the Claude Code output to extract enhancement data."""
        import re

        logger.info(f"Parsing Claude output ({len(output)} chars): {output[:500]}...")

        # Try to find JSON block in the output - look for outermost braces
        # Find the first { and last } to extract JSON
        first_brace = output.find('{')
        last_brace = output.rfind('}')

        if first_brace != -1 and last_brace > first_brace:
            json_str = output[first_brace:last_brace + 1]
            try:
                result = json.loads(json_str)
                logger.info(f"Successfully parsed JSON: {list(result.keys())}")
                return result
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON block: {e}")

        # Try parsing the whole output as JSON
        try:
            result = json.loads(output.strip())
            logger.info(f"Successfully parsed whole output as JSON")
            return result
        except json.JSONDecodeError:
            pass

        # Try to find JSON in code blocks
        code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', output, re.DOTALL)
        if code_block_match:
            try:
                result = json.loads(code_block_match.group(1))
                logger.info(f"Successfully parsed JSON from code block")
                return result
            except json.JSONDecodeError:
                pass

        # Fallback: return the raw output as enhanced description
        logger.warning("Could not parse JSON from Claude output, using raw text")
        return {
            "enhanced_description": output[:2000] if output else "",
            "acceptance_criteria": [],
            "complexity": "medium",
            "complexity_reason": "Could not determine",
            "suggested_labels": [],
        }


async def main():
    orchestrator = Orchestrator()
    await orchestrator.start()


if __name__ == "__main__":
    asyncio.run(main())
