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

import redis.asyncio as redis
from jinja2 import Environment, FileSystemLoader

from app.services.database_cloner import database_cloner
from app.services.agent_factory import agent_factory, generate_webhook_secret
from app.services.github_service import github_service
from app.services.certificate_service import certificate_service
from app.services.azure_service import azure_service

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

        # Start idle team checker background task
        asyncio.create_task(self.check_idle_teams())
        logger.info(f"Idle team checker started (interval: {IDLE_CHECK_INTERVAL}s, threshold: {IDLE_THRESHOLD}s)")

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
            # App Factory - Sandbox tasks
            elif task_type == "sandbox.provision":
                await self.provision_sandbox(task)
            elif task_type == "sandbox.delete":
                await self.delete_sandbox(task)
            elif task_type == "sandbox.agent.restart":
                await self.restart_sandbox_agent(task)
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
        project_name = f"kanban-team-{team_slug}"

        # Host path for team data
        team_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{team_slug}"

        # Docker compose file path (mounted in orchestrator container)
        compose_file = str(TEMPLATE_DIR / "docker-compose.yml")

        # Environment variables for docker compose
        # These inherit from orchestrator's environment (which gets them from root .env via docker-compose.yml)
        env = os.environ.copy()
        env.update({
            "TEAM_SLUG": team_slug,
            "DOMAIN": DOMAIN,
            "DATA_PATH": team_data_host_path,
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
        api_container_name = f"kanban-team-{team_slug}-api-1"
        web_container_name = f"kanban-team-{team_slug}-web-1"

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

        project_name = f"kanban-team-{team_slug}"
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
            for container in [f"kanban-team-{team_slug}-api", f"kanban-team-{team_slug}-web"]:
                run_docker_cmd(["stop", container], check=False)
            logger.info(f"[{team_slug}] Containers stopped (fallback)")

    async def _delete_remove_containers(self, team_slug: str, team_id: str):
        """Remove team containers using docker compose"""
        if not self.docker_available:
            logger.warning("Docker not available, skipping container removal")
            return

        project_name = f"kanban-team-{team_slug}"
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
            for container in [f"kanban-team-{team_slug}-api", f"kanban-team-{team_slug}-web",
                              f"kanban-team-{team_slug}-api-1", f"kanban-team-{team_slug}-web-1"]:
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

        project_name = f"kanban-team-{team_slug}"
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

        project_name = f"kanban-team-{team_slug}"
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

        project_name = f"kanban-team-{team_slug}"
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

        project_name = f"kanban-team-{team_slug}"
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

        # Publish progress
        await self.redis.publish(f"tasks:{task['user_id']}", json.dumps({
            "type": "task.progress",
            "task_id": task_id,
            "step": current_step,
            "total_steps": total_steps,
            "step_name": step_name,
            "percentage": percentage
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

    async def _get_running_teams(self) -> list[str]:
        """Get list of team slugs with running containers."""
        if not self.docker_available:
            return []

        try:
            result = run_docker_cmd([
                "ps", "--filter", "name=kanban-team-",
                "--format", "{{.Names}}"
            ], check=False)

            if result.returncode != 0:
                return []

            teams = set()
            for line in result.stdout.strip().split('\n'):
                if line and line.startswith('kanban-team-'):
                    # Extract team slug from container name
                    # Format: kanban-team-{slug}-api-1 or kanban-team-{slug}-web-1
                    # Remove prefix "kanban-team-" and suffix "-api-1" or "-web-1"
                    name = line[len('kanban-team-'):]  # Remove prefix
                    # Remove the service suffix (-api-1, -web-1)
                    if name.endswith('-api-1'):
                        slug = name[:-6]
                    elif name.endswith('-web-1'):
                        slug = name[:-6]
                    else:
                        # Unknown format, try to extract slug
                        parts = name.rsplit('-', 2)
                        slug = '-'.join(parts[:-2]) if len(parts) >= 3 else parts[0]

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

        project_name = f"kanban-team-{team_slug}"
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
        ]

        if app_template_id:
            steps.extend([
                ("Creating GitHub repository", self._workspace_create_github_repo),
                ("Creating Azure app registration", self._workspace_create_azure_app),
                ("Cloning repository", self._workspace_clone_repo),
                ("Issuing SSL certificate", self._workspace_issue_certificate),
                ("Creating app database", self._workspace_create_database),
                ("Deploying app containers", self._workspace_deploy_app),
                ("Provisioning workspace agent", self._workspace_provision_agent),
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

    async def _workspace_create_github_repo(self, workspace_slug: str, workspace_id: str):
        """Create GitHub repository from app template"""
        payload = self._current_payload
        github_org = payload.get("github_org", "hckmseduardo")
        template_owner = payload.get("template_owner", "hckmseduardo")
        template_repo = payload.get("template_repo", "basic-app")
        new_repo_name = f"{workspace_slug}-app"

        logger.info(f"[{workspace_slug}] Creating GitHub repo: {github_org}/{new_repo_name} from {template_owner}/{template_repo}")

        try:
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

        # Write compose file
        compose_file = Path(f"/tmp/workspace-app-{workspace_slug}-compose.yml")
        compose_file.write_text(compose_content)

        project_name = f"kanban-app-{workspace_slug}"

        try:
            # Create workspace data directory
            Path(workspace_data_path).mkdir(parents=True, exist_ok=True)

            # Stop and remove existing stack if it exists
            subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "-p", project_name, "down", "--remove-orphans"],
                capture_output=True,
                text=True,
                check=False
            )

            # Build and start the stack
            logger.info(f"[{workspace_slug}] Building and starting app containers...")
            result = subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "-p", project_name, "up", "-d", "--build"],
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode != 0:
                logger.error(f"[{workspace_slug}] Docker compose stderr: {result.stderr}")
                logger.error(f"[{workspace_slug}] Docker compose stdout: {result.stdout}")
                raise RuntimeError(f"Failed to build/start app containers: {result.stderr}")

            logger.info(f"[{workspace_slug}] App containers deployed")

        finally:
            # Clean up compose file
            if compose_file.exists():
                compose_file.unlink()

    async def _workspace_provision_agent(self, workspace_slug: str, workspace_id: str):
        """Provision dedicated agent for the workspace"""
        payload = self._current_payload
        git_branch = "main"

        logger.info(f"[{workspace_slug}] Provisioning workspace agent")

        # Kanban API URL for the workspace
        if PORT == "443":
            kanban_api_url = f"https://{workspace_slug}.{DOMAIN}/api"
        else:
            kanban_api_url = f"https://{workspace_slug}.{DOMAIN}:{PORT}/api"

        # Target project path on host
        target_project_path = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/app"

        # Generate webhook secret
        webhook_secret = generate_webhook_secret()
        self._current_payload["workspace_agent_webhook_secret"] = webhook_secret

        try:
            agent_info = await agent_factory.provision_agent(
                agent_id=f"{workspace_slug}-main",
                kanban_api_url=kanban_api_url,
                target_project_path=target_project_path,
                sandbox_branch=git_branch,
                webhook_secret=webhook_secret,
            )

            self._current_payload["workspace_agent_info"] = agent_info
            logger.info(f"[{workspace_slug}] Workspace agent provisioned: {agent_info['container_name']}")

        except Exception as e:
            logger.error(f"[{workspace_slug}] Failed to provision workspace agent: {e}")
            raise

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
            ("Stopping workspace agent", self._workspace_delete_agent),
            ("Deleting Azure app registration", self._workspace_delete_azure_app),
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
                await self._sandbox_stop_agent(full_slug, sandbox_id)
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

        project_name = f"kanban-app-{workspace_slug}"
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

    async def _workspace_delete_agent(self, workspace_slug: str, workspace_id: str):
        """Delete workspace agent container"""
        agent_id = f"{workspace_slug}-main"
        logger.info(f"[{workspace_slug}] Stopping workspace agent: {agent_id}")

        try:
            await agent_factory.destroy_agent(agent_id)
            logger.info(f"[{workspace_slug}] Workspace agent stopped")
        except Exception as e:
            logger.warning(f"[{workspace_slug}] Error stopping agent (may not exist): {e}")

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
            ("Creating git branch", self._sandbox_create_branch),
            ("Issuing SSL certificate", self._sandbox_issue_certificate),
            ("Cloning workspace database", self._sandbox_clone_database),
            ("Creating sandbox directory", self._sandbox_create_directory),
            ("Deploying sandbox containers", self._sandbox_deploy_containers),
            ("Provisioning sandbox agent", self._sandbox_provision_agent),
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
            await self.fail_task(task_id, str(e))
            raise

    async def _sandbox_validate(self, full_slug: str, sandbox_id: str):
        """Validate sandbox configuration"""
        if not full_slug or len(full_slug) < 5:
            raise ValueError("Invalid sandbox full_slug")

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
        """Create sandbox directory structure"""
        sandbox_dir = TEAMS_DIR / full_slug
        (sandbox_dir / "db").mkdir(parents=True, exist_ok=True)
        (sandbox_dir / "app").mkdir(parents=True, exist_ok=True)
        (sandbox_dir / "logs").mkdir(parents=True, exist_ok=True)
        logger.info(f"[{full_slug}] Directory structure created")

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
        agent_webhook_secret = self._current_payload.get("agent_webhook_secret") or generate_webhook_secret()

        # Store webhook secret in payload for agent provisioning
        self._current_payload["agent_webhook_secret"] = agent_webhook_secret

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
                agent_webhook_secret=agent_webhook_secret,
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
        compose_file = Path(f"/tmp/sandbox-{full_slug}-compose.yml")
        compose_file.write_text(compose_content)

        project_name = f"kanban-sandbox-{full_slug}"

        try:
            # Create sandbox data directory
            Path(sandbox_data_path).mkdir(parents=True, exist_ok=True)

            # Stop and remove existing stack if it exists
            subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "-p", project_name, "down", "--remove-orphans"],
                capture_output=True,
                text=True,
                check=False
            )

            # Start the stack
            result = subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "-p", project_name, "up", "-d"],
                capture_output=True,
                text=True,
                check=True
            )

            if result.returncode != 0:
                raise RuntimeError(f"Failed to start sandbox containers: {result.stderr}")

            logger.info(f"[{full_slug}] Sandbox containers deployed")

        finally:
            # Clean up compose file
            if compose_file.exists():
                compose_file.unlink()

    async def _sandbox_provision_agent(self, full_slug: str, sandbox_id: str):
        """Provision dedicated agent for sandbox"""
        workspace_slug = self._current_payload["workspace_slug"]
        sandbox_slug = self._current_payload["sandbox_slug"]
        git_branch = f"sandbox/{full_slug}"

        logger.info(f"[{full_slug}] Provisioning sandbox agent: kanban-agent-{full_slug}")

        # Kanban API URL for the workspace
        if PORT == "443":
            kanban_api_url = f"https://{workspace_slug}.{DOMAIN}/api"
        else:
            kanban_api_url = f"https://{workspace_slug}.{DOMAIN}:{PORT}/api"

        # Target project path on host
        target_project_path = f"{HOST_PROJECT_PATH}/data/workspaces/{workspace_slug}/app"

        # Generate webhook secret
        webhook_secret = self._current_payload.get("agent_webhook_secret") or generate_webhook_secret()

        try:
            agent_info = await agent_factory.provision_agent(
                agent_id=full_slug,
                kanban_api_url=kanban_api_url,
                target_project_path=target_project_path,
                sandbox_branch=git_branch,
                webhook_secret=webhook_secret,
            )

            # Store agent info in payload for later steps
            self._current_payload["agent_info"] = agent_info
            logger.info(f"[{full_slug}] Agent provisioned: {agent_info['container_name']}")

        except Exception as e:
            logger.error(f"[{full_slug}] Failed to provision agent: {e}")
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
            ("Stopping sandbox agent", self._sandbox_stop_agent),
            ("Stopping sandbox containers", self._sandbox_stop_containers),
            ("Removing sandbox containers", self._sandbox_remove_containers),
            ("Deleting git branch", self._sandbox_delete_branch),
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

    async def _sandbox_stop_agent(self, full_slug: str, sandbox_id: str):
        """Stop sandbox agent container"""
        logger.info(f"[{full_slug}] Stopping agent")
        try:
            await agent_factory.destroy_agent(full_slug)
        except Exception as e:
            logger.warning(f"[{full_slug}] Error stopping agent (may not exist): {e}")

    async def _sandbox_stop_containers(self, full_slug: str, sandbox_id: str):
        """Stop sandbox containers"""
        if not self.docker_available:
            logger.warning("Docker not available, skipping container stop")
            return

        logger.info(f"[{full_slug}] Stopping containers")
        project_name = f"kanban-sandbox-{full_slug}"

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
        project_name = f"kanban-sandbox-{full_slug}"
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

    async def _sandbox_archive_data(self, full_slug: str, sandbox_id: str):
        """Archive sandbox data"""
        sandbox_dir = TEAMS_DIR / full_slug
        archive_dir = TEAMS_DIR / ".archived" / "sandboxes"

        if sandbox_dir.exists():
            archive_dir.mkdir(parents=True, exist_ok=True)
            archived_name = f"{full_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            archived_path = archive_dir / archived_name
            shutil.move(str(sandbox_dir), str(archived_path))
            logger.info(f"[{full_slug}] Data archived to {archived_path}")

    async def restart_sandbox_agent(self, task: dict):
        """Restart a sandbox agent"""
        task_id = task["task_id"]
        payload = task["payload"]
        sandbox_id = payload["sandbox_id"]
        full_slug = payload["full_slug"]
        regenerate_secret = payload.get("regenerate_secret", False)

        logger.info(f"Restarting sandbox agent: {full_slug} (regenerate_secret={regenerate_secret})")

        steps = [
            ("Stopping agent", self._sandbox_stop_agent),
            ("Starting agent", self._sandbox_provision_agent),
        ]

        try:
            for i, (step_name, step_func) in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await step_func(full_slug, sandbox_id)
                logger.info(f"[{full_slug}] {step_name} - completed")

            await self.complete_task(task_id, {
                "action": "restart_sandbox_agent",
                "sandbox_id": sandbox_id,
                "full_slug": full_slug,
            })

            logger.info(f"Sandbox agent {full_slug} restarted successfully")

        except Exception as e:
            logger.error(f"Sandbox agent restart failed: {e}")
            await self.fail_task(task_id, str(e))
            raise


async def main():
    orchestrator = Orchestrator()
    await orchestrator.start()


if __name__ == "__main__":
    asyncio.run(main())
