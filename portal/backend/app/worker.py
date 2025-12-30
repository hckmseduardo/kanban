"""Background worker for processing async tasks"""

import asyncio
import json
import logging
import signal
import sys

import redis.asyncio as redis

from app.config import settings
from app.services.redis_service import redis_service
from app.services.database_service import db_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class TaskWorker:
    """Worker that processes tasks from Redis queues

    Note: Provisioning tasks are handled by the orchestrator service,
    not this worker.
    """

    QUEUES = [
        # Provisioning is handled by orchestrator
        # "queue:provisioning:high",
        # "queue:provisioning:normal",
        "queue:certificates:high",
        "queue:certificates:normal",
        "queue:dns:high",
        "queue:dns:normal",
        "queue:notifications:normal",
    ]

    def __init__(self):
        self.running = False
        self.client: redis.Redis = None

    async def start(self):
        """Start the worker"""
        logger.info("Starting task worker...")
        self.running = True

        # Connect to Redis
        self.client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True
        )

        # Set up signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_event_loop().add_signal_handler(
                sig, lambda: asyncio.create_task(self.stop())
            )

        # Start pubsub listener for team status updates
        asyncio.create_task(self.listen_team_status())

        logger.info(f"Worker listening on queues: {self.QUEUES}")

        while self.running:
            try:
                # Block waiting for task from any queue
                result = await self.client.brpop(self.QUEUES, timeout=5)

                if result:
                    queue_name, task_id = result
                    logger.info(f"Processing task {task_id} from {queue_name}")
                    await self.process_task(task_id)

            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info("Worker stopped")

    async def stop(self):
        """Stop the worker gracefully"""
        logger.info("Stopping worker...")
        self.running = False

    async def listen_team_status(self):
        """Listen for team status updates from orchestrator"""
        logger.info("Starting team status listener on channel: team:status")

        pubsub_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
        pubsub = pubsub_client.pubsub()
        await pubsub.subscribe("team:status")

        try:
            while self.running:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        team_id = data.get("team_id")
                        team_slug = data.get("team_slug")
                        status = data.get("status")

                        # If we don't have team_id but have team_slug, look it up
                        if not team_id and team_slug:
                            team = db_service.get_team_by_slug(team_slug)
                            if team:
                                team_id = team["id"]
                            else:
                                logger.warning(f"Team {team_slug} not found in database")
                                continue

                        if team_id and status:
                            logger.info(f"Updating team {team_slug} status to: {status}")
                            if status == "deleted":
                                # Remove team from database
                                db_service.delete_team(team_id)
                                logger.info(f"Team {team_slug} removed from database")
                            elif status == "suspended":
                                # Team was suspended due to inactivity
                                db_service.update_team(team_id, {"status": "suspended"})
                                logger.info(f"Team {team_slug} suspended (idle timeout)")
                            else:
                                db_service.update_team(team_id, {"status": status})
                                logger.info(f"Team {team_slug} status updated to {status}")

                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON in team:status message: {e}")
                    except Exception as e:
                        logger.error(f"Error updating team status: {e}")

        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe("team:status")
            await pubsub_client.close()
            logger.info("Team status listener stopped")

    async def process_task(self, task_id: str):
        """Process a single task"""
        try:
            # Get task data
            task_data = await self.client.hget(f"task:{task_id}", "data")
            if not task_data:
                logger.error(f"Task {task_id} not found")
                return

            task = json.loads(task_data)
            task_type = task.get("type")

            logger.info(f"Executing task: {task_type}")

            # Route to handler
            if task_type == "team.provision":
                await self.handle_team_provision(task)
            elif task_type == "team.delete":
                await self.handle_team_delete(task)
            elif task_type == "cert.issue":
                await self.handle_cert_issue(task)
            else:
                logger.warning(f"Unknown task type: {task_type}")
                await redis_service.fail_task(task_id, f"Unknown task type: {task_type}")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)
            await redis_service.fail_task(task_id, str(e))

    async def handle_team_provision(self, task: dict):
        """Handle team provisioning"""
        task_id = task["task_id"]
        payload = task["payload"]
        team_slug = payload["team_slug"]

        steps = [
            "Validating team configuration",
            "Creating team directory",
            "Initializing database",
            "Generating configuration",
            "Adding DNS record",
            "Waiting for DNS propagation",
            "Issuing SSL certificate",
            "Updating Traefik config",
            "Starting containers",
            "Running health check",
            "Finalizing setup"
        ]

        try:
            await redis_service.connect()

            for i, step in enumerate(steps, 1):
                await redis_service.update_task_progress(
                    task_id=task_id,
                    current_step=i,
                    total_steps=len(steps),
                    step_name=step,
                    message=f"Step {i}/{len(steps)}: {step}"
                )

                # Simulate work (replace with actual implementation)
                await asyncio.sleep(1)

                logger.info(f"[{team_slug}] {step} - completed")

            # Mark as completed
            await redis_service.complete_task(task_id, {
                "team_slug": team_slug,
                "url": f"https://{team_slug}.{settings.domain}"
            })

            logger.info(f"Team {team_slug} provisioned successfully")

        except Exception as e:
            logger.error(f"Team provisioning failed: {e}")
            await redis_service.fail_task(task_id, str(e))
            raise

    async def handle_team_delete(self, task: dict):
        """Handle team deletion"""
        task_id = task["task_id"]
        payload = task["payload"]
        team_slug = payload["team_slug"]

        steps = [
            "Creating backup",
            "Stopping containers",
            "Removing DNS record",
            "Revoking certificate",
            "Archiving data"
        ]

        try:
            await redis_service.connect()

            for i, step in enumerate(steps, 1):
                await redis_service.update_task_progress(
                    task_id=task_id,
                    current_step=i,
                    total_steps=len(steps),
                    step_name=step,
                    message=f"Step {i}/{len(steps)}: {step}"
                )

                # Simulate work
                await asyncio.sleep(0.5)

            await redis_service.complete_task(task_id, {
                "team_slug": team_slug,
                "archived": True
            })

            logger.info(f"Team {team_slug} deleted successfully")

        except Exception as e:
            await redis_service.fail_task(task_id, str(e))
            raise

    async def handle_cert_issue(self, task: dict):
        """Handle certificate issuance"""
        task_id = task["task_id"]
        payload = task["payload"]
        domain = payload["domain"]

        steps = [
            "Checking DNS",
            "Requesting certificate",
            "Validating domain",
            "Installing certificate"
        ]

        try:
            await redis_service.connect()

            for i, step in enumerate(steps, 1):
                await redis_service.update_task_progress(
                    task_id=task_id,
                    current_step=i,
                    total_steps=len(steps),
                    step_name=step,
                    message=f"Step {i}/{len(steps)}: {step}"
                )

                await asyncio.sleep(0.5)

            await redis_service.complete_task(task_id, {
                "domain": domain,
                "issued": True
            })

            logger.info(f"Certificate for {domain} issued successfully")

        except Exception as e:
            await redis_service.fail_task(task_id, str(e))
            raise


async def main():
    """Main entry point"""
    worker = TaskWorker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
