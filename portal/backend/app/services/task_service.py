"""Task service for async task management"""

import logging
from typing import Optional, List

from app.services.redis_service import redis_service

logger = logging.getLogger(__name__)


class TaskService:
    """Service for managing async tasks"""

    # Queue names
    QUEUE_PROVISIONING = "provisioning"
    QUEUE_CERTIFICATES = "certificates"
    QUEUE_DNS = "dns"
    QUEUE_NOTIFICATIONS = "notifications"

    async def create_team_provision_task(
        self,
        team_id: str,
        team_slug: str,
        owner_id: str,
        owner_email: str = None,
        owner_name: str = None
    ) -> str:
        """Create task to provision a new team"""
        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_PROVISIONING,
            task_type="team.provision",
            payload={
                "team_id": team_id,
                "team_slug": team_slug,
                "owner_id": owner_id,
                "owner_email": owner_email,
                "owner_name": owner_name
            },
            user_id=owner_id,
            priority="high"
        )

    async def create_team_delete_task(
        self,
        team_id: str,
        team_slug: str,
        user_id: str
    ) -> str:
        """Create task to delete a team"""
        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_PROVISIONING,
            task_type="team.delete",
            payload={
                "team_id": team_id,
                "team_slug": team_slug
            },
            user_id=user_id,
            priority="high"
        )

    async def create_cert_issue_task(
        self,
        team_slug: str,
        domain: str,
        user_id: str
    ) -> str:
        """Create task to issue SSL certificate"""
        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_CERTIFICATES,
            task_type="cert.issue",
            payload={
                "team_slug": team_slug,
                "domain": domain
            },
            user_id=user_id,
            priority="high"
        )

    async def get_task(self, task_id: str) -> Optional[dict]:
        """Get task by ID"""
        return await redis_service.get_task(task_id)

    async def get_user_tasks(
        self,
        user_id: str,
        status: str = None,
        limit: int = 20
    ) -> List[dict]:
        """Get tasks for a user"""
        return await redis_service.get_user_tasks(user_id, status, limit)

    async def retry_task(self, task_id: str) -> bool:
        """Retry a failed task"""
        task = await redis_service.get_task(task_id)
        if not task or task.get("status") != "failed":
            return False

        # Re-enqueue the task
        await redis_service.enqueue_task(
            queue_name=self._get_queue_for_type(task["type"]),
            task_type=task["type"],
            payload=task["payload"],
            user_id=task["user_id"],
            priority=task.get("priority", "normal")
        )
        return True

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending task"""
        task = await redis_service.get_task(task_id)
        if not task or task.get("status") != "pending":
            return False

        # Mark as cancelled
        task["status"] = "cancelled"
        await redis_service.client.hset(f"task:{task_id}", mapping={
            "data": __import__("json").dumps(task)
        })
        return True

    def _get_queue_for_type(self, task_type: str) -> str:
        """Get queue name for task type"""
        if task_type.startswith("team."):
            return self.QUEUE_PROVISIONING
        elif task_type.startswith("cert."):
            return self.QUEUE_CERTIFICATES
        elif task_type.startswith("dns."):
            return self.QUEUE_DNS
        else:
            return self.QUEUE_NOTIFICATIONS


# Singleton instance
task_service = TaskService()
