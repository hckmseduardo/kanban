"""Orchestrator main entry point - listens for provisioning tasks"""

import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
import shlex
import time
from datetime import datetime
from pathlib import Path

import redis.asyncio as redis
from jinja2 import Environment, FileSystemLoader

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
HOST_IP = os.getenv("HOST_IP", "127.0.0.1")
HOST_PROJECT_PATH = os.getenv("HOST_PROJECT_PATH", "/Volumes/dados/projects/kanban")

TEAMS_DIR = Path("/app/data/teams")
TEMPLATE_DIR = Path("/app/kanban-team")
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

        # Check if Docker CLI is available
        if docker_available():
            self.docker_available = True
            logger.info("Docker CLI available")
        else:
            logger.warning("Docker CLI not available. Container operations disabled.")

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


async def main():
    orchestrator = Orchestrator()
    await orchestrator.start()


if __name__ == "__main__":
    asyncio.run(main())
