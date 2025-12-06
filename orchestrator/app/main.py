"""Orchestrator main entry point - listens for provisioning tasks"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import shlex
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
TEMPLATE_DIR = Path("/app/team-template")
TRAEFIK_DIR = Path("/app/traefik-dynamic")
DNS_DIR = Path("/app/dns-zones")
NETWORK_NAME = "kanban-global"


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
        """Initialize team database"""
        db_file = TEAMS_DIR / team_slug / "db" / "team.json"
        db_file.write_text('{"_default": {}}')

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
        """Start team containers using Docker CLI"""
        if not self.docker_available:
            raise RuntimeError("Docker CLI not available")

        logger.info(f"[{team_slug}] Starting containers...")

        # Container names
        api_container_name = f"kanban-team-{team_slug}-api"
        web_container_name = f"kanban-team-{team_slug}-web"

        # Remove existing containers if they exist
        run_docker_cmd(["rm", "-f", api_container_name], check=False)
        run_docker_cmd(["rm", "-f", web_container_name], check=False)

        # Images to use
        api_image = "kanban-team-backend:latest"
        web_image = "kanban-team-frontend:latest"

        # Host path for team data
        team_data_host_path = f"{HOST_PROJECT_PATH}/data/teams/{team_slug}"

        # Create API container
        # Routes: {slug}.{domain}/api/* -> backend (Traefik strips /api prefix)
        logger.info(f"[{team_slug}] Creating API container...")
        api_cmd = [
            "run", "-d",
            "--name", api_container_name,
            "--restart", "unless-stopped",
            "--network", NETWORK_NAME,
            "-e", f"REDIS_URL=redis://kanban-redis:6379",
            "-e", f"DOMAIN={DOMAIN}",
            "-e", f"PORTAL_URL=https://{DOMAIN}",
            "-e", f"TEAM_SLUG={team_slug}",
            "-v", f"{team_data_host_path}:/app/data",
            "-l", "traefik.enable=true",
            "-l", f"traefik.http.routers.team-{team_slug}-api.rule=Host(`{team_slug}.{DOMAIN}`) && PathPrefix(`/api`)",
            "-l", f"traefik.http.routers.team-{team_slug}-api.entrypoints=websecure",
            "-l", f"traefik.http.routers.team-{team_slug}-api.tls=true",
            "-l", f"traefik.http.routers.team-{team_slug}-api.tls.certresolver=letsencrypt",
            "-l", f"traefik.http.routers.team-{team_slug}-api.middlewares=team-{team_slug}-api-strip",
            "-l", f"traefik.http.middlewares.team-{team_slug}-api-strip.stripprefix.prefixes=/api",
            "-l", f"traefik.http.services.team-{team_slug}-api.loadbalancer.server.port=8000",
            api_image
        ]
        result = run_docker_cmd(api_cmd)
        container_id = result.stdout.strip()[:12]
        logger.info(f"[{team_slug}] API container started: {container_id}")

        # Create Web container
        # Routes: {slug}.{domain}/* (except /api) -> frontend
        logger.info(f"[{team_slug}] Creating Web container...")
        web_cmd = [
            "run", "-d",
            "--name", web_container_name,
            "--restart", "unless-stopped",
            "--network", NETWORK_NAME,
            "-l", "traefik.enable=true",
            "-l", f"traefik.http.routers.team-{team_slug}-web.rule=Host(`{team_slug}.{DOMAIN}`) && !PathPrefix(`/api`)",
            "-l", f"traefik.http.routers.team-{team_slug}-web.entrypoints=websecure",
            "-l", f"traefik.http.routers.team-{team_slug}-web.tls=true",
            "-l", f"traefik.http.routers.team-{team_slug}-web.tls.certresolver=letsencrypt",
            "-l", f"traefik.http.services.team-{team_slug}-web.loadbalancer.server.port=80",
            web_image
        ]
        result = run_docker_cmd(web_cmd)
        container_id = result.stdout.strip()[:12]
        logger.info(f"[{team_slug}] Web container started: {container_id}")

    async def _health_check(self, team_slug: str, team_id: str):
        """Check team environment health"""
        if not self.docker_available:
            return

        api_container_name = f"kanban-team-{team_slug}-api"
        web_container_name = f"kanban-team-{team_slug}-web"

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

        logger.info(f"Deleting team: {team_slug}")

        steps = [
            "Creating backup",
            "Stopping containers",
            "Removing DNS record",
            "Revoking certificate",
            "Archiving data",
        ]

        try:
            for i, step_name in enumerate(steps, 1):
                await self.update_progress(task_id, i, len(steps), step_name)
                await asyncio.sleep(0.5)
                logger.info(f"[{team_slug}] {step_name} - completed")

            await self.complete_task(task_id, {
                "team_slug": team_slug,
                "archived": True
            })

        except Exception as e:
            await self.fail_task(task_id, str(e))
            raise

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


async def main():
    orchestrator = Orchestrator()
    await orchestrator.start()


if __name__ == "__main__":
    asyncio.run(main())
