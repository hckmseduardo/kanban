"""Orchestrator main entry point - listens for provisioning tasks"""

import asyncio
import json
import logging
import os
import secrets
import shutil
import signal
import subprocess
import shlex
import time
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

TEAMS_DIR = Path("/app/data/teams")
# Use HOST_PROJECT_PATH for workspaces so docker compose build contexts resolve correctly
WORKSPACES_DIR = Path(f"{HOST_PROJECT_PATH}/data/workspaces")
TEMPLATE_DIR = Path("/app/kanban-team")
APP_FACTORY_TEMPLATE_DIR = Path(__file__).parent / "templates"
TRAEFIK_DIR = Path("/app/traefik-dynamic")
DNS_DIR = Path("/app/dns-zones")
NETWORK_NAME = "kanban-global"

# Auto-scaling configuration
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

    def __init__(self):
        self.running = False
        self.redis: redis.Redis = None
        self.docker_available = False
        self.jinja = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
        self.app_factory_jinja = Environment(loader=FileSystemLoader(str(APP_FACTORY_TEMPLATE_DIR)))

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

        # Start idle team checker background task
        asyncio.create_task(self.check_idle_teams())
        logger.info(f"Idle team checker started (interval: {IDLE_CHECK_INTERVAL}s, threshold: {IDLE_THRESHOLD}s)")

        # Start health check processor background task
        asyncio.create_task(self.process_health_checks())
        logger.info("Health check processor started")

        logger.info(f"Orchestrator listening on queues: {self.QUEUES}")

        while self.running:
            try:
                result = await self.redis.brpop(self.QUEUES, timeout=5)

                if result:
                    queue_name, task_id = result
                    logger.info(f"Processing task {task_id} from {queue_name}")
                    await self.process_task(task_id)

            except Exception as e:
                logger.error(f"Orchestrator error: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info("Orchestrator stopped")

    async def stop(self):
        """Stop the orchestrator"""
        logger.info("Stopping orchestrator...")
        self.running = False

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
            # App Factory - Sandbox tasks
            elif task_type == "sandbox.provision":
                await self.provision_sandbox(task)
            elif task_type == "sandbox.delete":
                await self.delete_sandbox(task)
            elif task_type == "sandbox.restart":
                await self.restart_sandbox(task)
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

        # Default board templates to create
        default_boards = [
            ("ideas-pipeline", "Ideas Pipeline"),
            ("feature-request", "Feature Request"),
            ("bug-tracking", "Bug Tracking"),
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
            for template_id, board_name in default_boards:
                try:
                    response = await client.post(
                        f"{kanban_api_url}/templates/{template_id}/apply",
                        params={"board_name": board_name},
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

        # Use workspaces directory for app code
        workspace_dir = WORKSPACES_DIR / workspace_slug / "app"
        workspace_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[{workspace_slug}] Cloning repository to {workspace_dir}")

        try:
            # Get authenticated clone URL
            clone_url = await github_service.clone_repository_url(
                owner=github_org,
                repo=github_repo,
                use_ssh=False,  # Use HTTPS with token
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
        """Deploy app containers using the workspace-app-compose template"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        payload = self._current_payload
        database_name = workspace_slug.replace("-", "_") + "_app"

        logger.info(f"[{workspace_slug}] Deploying app containers")

        # Generate secrets
        postgres_password = secrets.token_hex(16)
        app_secret_key = secrets.token_hex(32)

        # Store secrets in payload
        self._current_payload["postgres_password"] = postgres_password
        self._current_payload["app_secret_key"] = app_secret_key

        # Paths
        workspace_data_path = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}"
        app_source_path = f"{workspace_data_path}/app"

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

    async def delete_workspace(self, task: dict):
        """Delete a workspace and all its resources"""
        task_id = task["task_id"]
        payload = task["payload"]
        workspace_id = payload["workspace_id"]
        workspace_slug = payload["workspace_slug"]

        logger.info(f"Deleting workspace: {workspace_slug}")

        # Store payload for step functions
        self._current_payload = payload

        steps = [
            ("Deleting sandboxes", self._workspace_delete_sandboxes),
            ("Stopping app containers", self._workspace_stop_app),
            ("Deleting GitHub repository", self._workspace_delete_github_repo),
            ("Deleting Azure app registration", self._workspace_delete_azure_app),
            ("Archiving workspace data", self._workspace_archive_data),
            ("Stopping kanban team", self._delete_stop_containers),
            ("Removing containers", self._delete_remove_containers),
            ("Archiving data", self._delete_archive_data),
            ("Cleaning up", self._delete_cleanup),
        ]

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
        branch_name = f"sandbox/{full_slug}"

        logger.info(f"[{full_slug}] Creating branch: {branch_name} from {source_branch}")

        try:
            result = await github_service.create_branch(
                owner=github_org,
                repo=github_repo,
                branch_name=branch_name,
                source_branch=source_branch,
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
        github_token = os.environ.get("GITHUB_TOKEN")

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

    async def _sandbox_deploy_containers(self, full_slug: str, sandbox_id: str):
        """Deploy sandbox containers using the sandbox-compose template"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        workspace_slug = self._current_payload["workspace_slug"]
        sandbox_slug = self._current_payload["sandbox_slug"]
        git_branch = f"sandbox/{full_slug}"
        database_name = full_slug.replace("-", "_")

        logger.info(f"[{full_slug}] Deploying sandbox containers")

        # Generate secrets
        postgres_password = secrets.token_hex(16)
        app_secret_key = secrets.token_hex(32)

        # Paths
        workspace_data_path = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}"
        sandbox_data_path = f"{HOST_PROJECT_PATH}/data/sandboxes/{full_slug}"
        app_source_path = f"{workspace_data_path}/app"

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

        # Write compose file to persistent location in sandbox directory
        # The sandboxes directory is mounted at HOST_PROJECT_PATH/data/sandboxes in docker-compose.yml
        compose_file_host = f"{HOST_PROJECT_PATH}/data/sandboxes/{full_slug}/docker-compose.app.yml"
        sandbox_host_dir = f"{HOST_PROJECT_PATH}/data/sandboxes/{full_slug}"

        # Ensure directory exists
        os.makedirs(sandbox_host_dir, exist_ok=True)

        # Write compose file
        with open(compose_file_host, "w") as f:
            f.write(compose_content)

        logger.info(f"[{full_slug}] Saved compose file to {compose_file_host}")

        project_name = f"{full_slug}-app"

        try:
            # Stop and remove existing stack if it exists
            subprocess.run(
                ["docker", "compose", "-f", compose_file_host, "-p", project_name, "down", "--remove-orphans"],
                capture_output=True,
                text=True,
                check=False
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
                    ["docker", "compose", "-f", compose_file_host, "-p", project_name, "up", "-d"],
                    capture_output=True,
                    text=True,
                    check=False
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
        """Process an AI agent task using Claude Code subprocess.

        This method:
        1. Prepares the sandbox context (git branch, working directory)
        2. Builds the agent prompt from card data and agent config
        3. Spawns Claude Code subprocess with tool_profile and timeout
        4. Streams progress to card comments
        5. Updates card on completion
        """
        task_id = task["task_id"]
        payload = task["payload"]
        card_id = payload["card_id"]
        card_title = payload["card_title"]
        card_description = payload["card_description"]
        column_name = payload["column_name"]
        agent_config = payload.get("agent_config", {})
        agent_name = agent_config.get("agent_name", "developer")
        sandbox_id = payload["sandbox_id"]
        workspace_slug = payload["workspace_slug"]
        git_branch = payload["git_branch"]
        kanban_api_url = payload["kanban_api_url"]
        target_project_path = payload["target_project_path"]

        logger.info(
            f"Processing agent task: card={card_id}, agent={agent_name}, "
            f"sandbox={sandbox_id}"
        )

        steps = [
            ("Preparing sandbox context", self._agent_prepare_context),
            ("Running AI agent", self._agent_run_claude),
            ("Processing results", self._agent_process_results),
            ("Updating card", self._agent_update_card),
        ]

        # Store payload for step functions
        self._current_payload = payload
        self._agent_result = None

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(card_id, sandbox_id)
                logger.info(f"[{card_id}] {step_name} - completed")

            await self.complete_task(task_id, {
                "action": "process_card",
                "card_id": card_id,
                "agent_name": agent_name,
                "success": self._agent_result.success if self._agent_result else False,
                "files_modified": self._agent_result.files_modified if self._agent_result else [],
            })

            logger.info(f"Agent task completed: card={card_id}")

        except Exception as e:
            logger.error(f"Agent task failed: {e}")
            await self.fail_task(task_id, str(e))
            raise

    async def _agent_prepare_context(self, card_id: str, sandbox_id: str):
        """Prepare the sandbox context for agent execution."""
        payload = self._current_payload
        workspace_slug = payload["workspace_slug"]
        sandbox_slug = payload.get("sandbox_slug")

        if not sandbox_slug:
            raise RuntimeError(f"sandbox_slug is required - card must be linked to a sandbox")

        # Construct full_slug from workspace and sandbox slugs
        full_slug = f"{workspace_slug}-{sandbox_slug}"
        logger.info(f"[{card_id}] Using sandbox: {full_slug} (branch: sandbox/{full_slug})")

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
            logger.info(f"[{card_id}] Repository not found at {repo_path}, cloning now...")

            # Get GitHub info from payload or lookup workspace
            github_repo_url = payload.get("github_repo_url")
            if not github_repo_url:
                raise RuntimeError(f"Repository not found and github_repo_url not in payload")

            github_token = os.environ.get("GITHUB_TOKEN")
            clone_url = github_repo_url
            if github_token and "github.com" in github_repo_url:
                clone_url = github_repo_url.replace("https://github.com", f"https://{github_token}@github.com")

            # Ensure directory exists
            os.makedirs(str(repo_path), exist_ok=True)

            # Clone with the sandbox branch
            logger.info(f"[{card_id}] Cloning {github_repo_url} branch {git_branch}")
            result = subprocess.run(
                ["git", "clone", "--branch", git_branch, clone_url, "."],
                cwd=str(repo_path),
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to clone repository: {result.stderr}")

            logger.info(f"[{card_id}] Repository cloned successfully")

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

    async def _agent_run_claude(self, card_id: str, sandbox_id: str):
        """Run Claude Code subprocess for the agent task."""
        payload = self._current_payload
        card_title = payload["card_title"]
        card_description = payload["card_description"]
        column_name = payload["column_name"]
        agent_config = payload.get("agent_config", {})
        agent_name = agent_config.get("agent_name", "developer")
        target_project_path = payload["target_project_path"]
        sandbox_slug = payload.get("sandbox_slug", "")
        workspace_slug = payload["workspace_slug"]
        board_id = payload.get("board_id")

        # Get agent config values with defaults
        persona = agent_config.get("persona", "")
        tool_profile = agent_config.get("tool_profile", "developer")
        timeout = agent_config.get("timeout", 600)

        # For scrum_master agent, fetch the current board state so it can see all cards
        board_state = None
        if agent_name == "scrum_master" and board_id:
            board_state = await self._fetch_board_state_for_agent(workspace_slug, board_id)

        # Build the prompt for Claude Code using persona from agent config
        # Include sandbox info so agents can link created cards to the same sandbox
        prompt = self._build_agent_prompt(
            card_title=card_title,
            card_description=card_description,
            column_name=column_name,
            persona=persona,
            sandbox_id=sandbox_id,
            sandbox_slug=sandbox_slug,
            board_state=board_state,
        )

        # Progress callback for streaming updates
        async def on_progress(message: str, percentage: int):
            # Could stream to card comments here
            logger.debug(f"Agent progress ({percentage}%): {message[:100]}")

        # Run Claude Code with config from kanban-team
        self._agent_result = await claude_runner.run(
            prompt=prompt,
            working_dir=target_project_path,
            agent_type=agent_name,  # Still used for tool fallback
            tool_profile=tool_profile,
            timeout=timeout,
        )

        if not self._agent_result.success:
            logger.error(f"Claude Code failed: {self._agent_result.error}")

    async def _agent_process_results(self, card_id: str, sandbox_id: str):
        """Process results from Claude Code execution."""
        if not self._agent_result:
            return

        result = self._agent_result
        payload = self._current_payload
        target_project_path = payload["target_project_path"]
        git_branch = payload["git_branch"]

        # Always check for uncommitted changes (agents may not report files_modified)
        target_path = Path(target_project_path)
        status_lines = []
        status_ok = True
        try:
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(target_path),
                capture_output=True,
                text=True
            )
            if status_result.returncode != 0:
                raise RuntimeError(status_result.stderr.strip() or "git status failed")
            status_lines = [line for line in status_result.stdout.splitlines() if line.strip()]
        except Exception as e:
            status_error = f"git status failed: {e}"
            logger.warning(f"[{card_id}] Failed to check git status: {e}")
            result.git_dirty = True
            result.commit_error = status_error
            if result.error:
                result.error = f"{result.error}\nCommit error: {status_error}"
            else:
                result.error = f"Commit error: {status_error}"
            result.success = False
            status_ok = False

        commit_hash = None
        commit_error = result.commit_error
        push_error = None
        push_attempted = False
        push_success = False

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

            agent_name = payload.get("agent_config", {}).get("agent_name", "agent")
            commit_msg = f"Agent: {agent_name} processed card {card_id[:8]}"

            try:
                add_result = subprocess.run(
                    ["git", "add", "-A"],
                    cwd=str(target_path),
                    capture_output=True,
                    text=True
                )
                if add_result.returncode != 0:
                    raise RuntimeError(add_result.stderr.strip() or "git add failed")

                commit_result = subprocess.run(
                    ["git", "commit", "-m", commit_msg],
                    cwd=str(target_path),
                    capture_output=True,
                    text=True
                )
                if commit_result.returncode != 0:
                    error_text = commit_result.stderr.strip() or commit_result.stdout.strip()
                    raise RuntimeError(error_text or "git commit failed")

                hash_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(target_path),
                    capture_output=True,
                    text=True
                )
                if hash_result.returncode == 0:
                    commit_hash = hash_result.stdout.strip()

                logger.info(f"[{card_id}] Committed changes ({len(result.files_modified)} files)")

            except Exception as e:
                commit_error = str(e)

            # Verify working tree is clean after commit
            try:
                final_status = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=str(target_path),
                    capture_output=True,
                    text=True
                )
                if final_status.returncode == 0 and final_status.stdout.strip():
                    result.git_dirty = True
                    if not commit_error:
                        commit_error = "Working tree not clean after commit"
                else:
                    result.git_dirty = False
            except Exception as e:
                logger.warning(f"[{card_id}] Failed to verify git status: {e}")
                if not commit_error:
                    commit_error = f"git status failed after commit: {e}"
        elif status_ok:
            result.git_dirty = False

        # Push if there are unpushed commits and no commit errors
        ahead_count = 0
        push_needed = False
        try:
            ahead_result = subprocess.run(
                ["git", "rev-list", "--count", f"origin/{git_branch}..{git_branch}"],
                cwd=str(target_path),
                capture_output=True,
                text=True
            )
            if ahead_result.returncode == 0:
                ahead_count = int(ahead_result.stdout.strip() or "0")
                push_needed = ahead_count > 0
            else:
                push_needed = True
        except Exception:
            push_needed = commit_hash is not None

        if commit_hash:
            push_needed = True

        github_token = os.environ.get("GITHUB_TOKEN")
        if github_token and not commit_error and push_needed:
            push_attempted = True
            try:
                push_result = subprocess.run(
                    ["git", "push", "origin", git_branch],
                    cwd=str(target_path),
                    capture_output=True,
                    text=True,
                    env={**os.environ, "GIT_ASKPASS": "echo", "GIT_TERMINAL_PROMPT": "0"}
                )
                if push_result.returncode == 0:
                    push_success = True
                    logger.info(f"[{card_id}] Pushed changes to {git_branch}")
                else:
                    error_text = push_result.stderr.strip() or push_result.stdout.strip()
                    push_error = f"git push failed: {error_text}"
            except Exception as e:
                push_error = f"git push failed: {e}"

        result.commit_hash = commit_hash
        result.push_attempted = push_attempted
        result.push_success = push_success
        result.commit_error = commit_error
        result.push_error = push_error
        result.push_needed = push_needed
        result.ahead_count = ahead_count

        if commit_error:
            logger.warning(f"[{card_id}] Commit issue: {commit_error}")
            result.commit_error = commit_error
            if result.error:
                result.error = f"{result.error}\nCommit error: {commit_error}"
            else:
                result.error = f"Commit error: {commit_error}"
            result.success = False
        elif push_error:
            logger.warning(f"[{card_id}] Push issue: {push_error}")

    async def _agent_update_card(self, card_id: str, sandbox_id: str):
        """Update the kanban card with agent results."""
        if not self._agent_result:
            return

        result = self._agent_result
        payload = self._current_payload
        workspace_slug = payload["workspace_slug"]
        # Use internal Docker network URL for service-to-service calls
        kanban_api_url = f"http://{workspace_slug}-kanban-api-1:8000"
        git_branch = payload["git_branch"]

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

                if card_response.status_code == 200 and result.success and result.output:
                    card_data = card_response.json()
                    current_description = card_data.get("description", "") or ""

                    # Build agent output section
                    agent_section = f"\n\n---\n\n## Agent: {display_name}\n\n"
                    # Truncate output if too long
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
                    await self._handle_project_manager_output(card_id, sandbox_id)

                # Get board_id for card movements (needed by scrum_master and column moves)
                board_id = payload.get("board_id")

                # Special handling for scrum_master agent: move next card from project plan
                if agent_name == "scrum_master" and result.success and board_id:
                    await self._handle_scrum_master_output(card_id, kanban_api_url, board_id)

                # If successful and column_success is set, move the card
                if result.success and column_success:
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
                elif not result.success and column_failure:
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
        board_state: str = None,
    ) -> str:
        """Build the prompt for Claude Code using persona from kanban-team.

        Args:
            card_title: The card title
            card_description: The card description/requirements
            column_name: Current column name
            persona: Agent persona/instructions from kanban-team config
            sandbox_id: The sandbox ID this card is linked to
            sandbox_slug: The sandbox slug for reference
            board_state: Current kanban board state (for scrum_master)
        """
        # Use persona from config, or a generic fallback
        if not persona:
            persona = "Process this card according to your role."

        # Build context section with sandbox info
        context_section = ""
        if sandbox_id or sandbox_slug:
            context_section = f"""
## Card Context:
- Sandbox ID: {sandbox_id}
- Sandbox Slug: {sandbox_slug}
IMPORTANT: When creating project plans or cards, use this sandbox_id to link them to the same sandbox.
"""

        # Add board state for scrum_master (so it can see all cards and their columns)
        board_state_section = ""
        if board_state:
            board_state_section = f"""
## Current Kanban Board State:
{board_state}
"""

        prompt = f"""# Task: {card_title}

## Column: {column_name}

## Description:
{card_description}
{context_section}{board_state_section}
## Agent Instructions:
{persona}

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
        options = payload.get("options", {})

        # Build the enhancement prompt
        prompt = self._build_enhance_prompt(card_title, card_description, options)

        # Run Claude Code CLI with readonly tools (no file modifications needed)
        result = await claude_runner.run(
            prompt=prompt,
            working_dir=str(Path.cwd()),  # Doesn't matter for this task
            agent_type="product_owner",
            tool_profile="readonly",
            timeout=120,  # 2 minutes should be enough
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

## Card Title
{card_title}

## Current Description
{card_description or "(No description provided)"}

## Tasks
{features_text}

## Output Format
Respond with ONLY a JSON object in this exact format (no markdown, no code blocks):
{{
  "enhanced_description": "The improved description text",
  "acceptance_criteria": ["Criterion 1", "Criterion 2", "..."],
  "complexity": "low|medium|high",
  "complexity_reason": "Brief explanation of complexity rating",
  "suggested_labels": ["label1", "label2"]
}}

Be concise but thorough. Focus on actionable improvements."""

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

    async def _handle_project_manager_output(self, card_id: str, sandbox_id: str):
        """Handle project_manager agent output: create epics and cards on Feature Request board."""
        logger.info(f"[{card_id}] _handle_project_manager_output called")

        if not self._agent_result:
            logger.warning(f"[{card_id}] No agent result available")
            return

        payload = self._current_payload
        workspace_slug = payload["workspace_slug"]
        board_id = payload.get("board_id")
        kanban_api_url = f"http://{workspace_slug}-kanban-api-1:8000"
        target_project_path = payload.get("target_project_path", "")

        # Try to parse from agent output first
        project_plan = None
        if self._agent_result.output:
            logger.info(f"[{card_id}] Agent output length: {len(self._agent_result.output)} chars")
            project_plan = self._parse_project_plan_output(self._agent_result.output)

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

    async def _handle_scrum_master_output(self, card_id: str, kanban_api_url: str, board_id: str):
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

        if not self._agent_result:
            logger.warning(f"[{card_id}] No agent result available for scrum_master")
            return

        # Parse JSON from agent output
        output = self._agent_result.output
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
