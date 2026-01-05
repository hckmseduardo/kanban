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

    async def create_team_restart_task(
        self,
        team_id: str,
        team_slug: str,
        user_id: str,
        rebuild: bool = False
    ) -> str:
        """Create task to restart/rebuild a team's containers"""
        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_PROVISIONING,
            task_type="team.restart",
            payload={
                "team_id": team_id,
                "team_slug": team_slug,
                "rebuild": rebuild
            },
            user_id=user_id,
            priority="high"
        )

    async def create_team_start_task(
        self,
        team_id: str,
        team_slug: str,
        user_id: str
    ) -> str:
        """Create task to start a suspended team's containers.

        This is used when a user tries to access a team that was
        automatically suspended due to inactivity.
        """
        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_PROVISIONING,
            task_type="team.start",
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

    # =========================================================================
    # Workspace Tasks
    # =========================================================================

    async def create_workspace_provision_task(
        self,
        workspace_id: str,
        workspace_slug: str,
        owner_id: str,
        owner_email: str = None,
        owner_name: str = None,
        app_template_id: str = None,
        template_owner: str = None,
        template_repo: str = None,
        github_org: str = "amazing-ai-tools",
    ) -> str:
        """Create task to provision a new workspace.

        This will:
        1. Create a kanban team for the workspace
        2. If app_template_id is provided:
           - Create a GitHub repo from the template
           - Deploy app containers
           - Provision a dedicated agent
        """
        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_PROVISIONING,
            task_type="workspace.provision",
            payload={
                "workspace_id": workspace_id,
                "workspace_slug": workspace_slug,
                "owner_id": owner_id,
                "owner_email": owner_email,
                "owner_name": owner_name,
                "app_template_id": app_template_id,
                "template_owner": template_owner,
                "template_repo": template_repo,
                "github_org": github_org,
            },
            user_id=owner_id,
            priority="high"
        )

    async def create_workspace_delete_task(
        self,
        workspace_id: str,
        workspace_slug: str,
        user_id: str,
        azure_object_id: str = None,
        sandboxes: list = None,
        github_org: str = None,
        github_repo_name: str = None,
    ) -> str:
        """Create task to delete a workspace.

        This will:
        1. Delete all sandboxes
        2. Delete the app (if present)
        3. Delete the Azure app registration (if present)
        4. Delete the kanban team
        5. Clean up all resources
        """
        payload = {
            "workspace_id": workspace_id,
            "workspace_slug": workspace_slug,
            "sandboxes": sandboxes or [],
            "github_org": github_org,
            "github_repo_name": github_repo_name,
        }
        if azure_object_id:
            payload["azure_object_id"] = azure_object_id

        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_PROVISIONING,
            task_type="workspace.delete",
            payload=payload,
            user_id=user_id,
            priority="high"
        )

    # =========================================================================
    # Sandbox Tasks
    # =========================================================================

    async def create_sandbox_provision_task(
        self,
        sandbox_id: str,
        workspace_id: str,
        workspace_slug: str,
        sandbox_slug: str,
        full_slug: str,
        source_branch: str,
        owner_id: str,
        github_org: str = None,
        github_repo_name: str = None,
        azure_tenant_id: str = None,
        azure_app_id: str = None,
        azure_client_secret: str = None,
        azure_object_id: str = None,
    ) -> str:
        """Create task to provision a new sandbox.

        This will:
        1. Create git branch from source_branch
        2. Clone database from workspace
        3. Deploy sandbox containers
        4. Provision dedicated agent
        5. Add redirect URI to Azure app registration
        """
        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_PROVISIONING,
            task_type="sandbox.provision",
            payload={
                "sandbox_id": sandbox_id,
                "workspace_id": workspace_id,
                "workspace_slug": workspace_slug,
                "sandbox_slug": sandbox_slug,
                "full_slug": full_slug,
                "source_branch": source_branch,
                "github_org": github_org,
                "github_repo_name": github_repo_name,
                "azure_tenant_id": azure_tenant_id,
                "azure_app_id": azure_app_id,
                "azure_client_secret": azure_client_secret,
                "azure_object_id": azure_object_id,
            },
            user_id=owner_id,
            priority="high"
        )

    async def create_sandbox_delete_task(
        self,
        sandbox_id: str,
        workspace_id: str,
        full_slug: str,
        user_id: str,
        workspace_slug: str = None,
        github_org: str = None,
        github_repo_name: str = None,
        azure_object_id: str = None,
    ) -> str:
        """Create task to delete a sandbox.

        This will:
        1. Stop and remove containers
        2. Delete git branch
        3. Delete database
        4. Clean up agent
        5. Remove redirect URI from Azure app registration
        """
        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_PROVISIONING,
            task_type="sandbox.delete",
            payload={
                "sandbox_id": sandbox_id,
                "workspace_id": workspace_id,
                "full_slug": full_slug,
                "workspace_slug": workspace_slug,
                "github_org": github_org,
                "github_repo_name": github_repo_name,
                "azure_object_id": azure_object_id,
            },
            user_id=user_id,
            priority="high"
        )

    async def create_sandbox_agent_restart_task(
        self,
        sandbox_id: str,
        full_slug: str,
        user_id: str,
        regenerate_secret: bool = False,
    ) -> str:
        """Create task to restart a sandbox agent."""
        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_PROVISIONING,
            task_type="sandbox.agent.restart",
            payload={
                "sandbox_id": sandbox_id,
                "full_slug": full_slug,
                "regenerate_secret": regenerate_secret,
            },
            user_id=user_id,
            priority="normal"
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
        elif task_type.startswith("workspace."):
            return self.QUEUE_PROVISIONING
        elif task_type.startswith("sandbox."):
            return self.QUEUE_PROVISIONING
        elif task_type.startswith("cert."):
            return self.QUEUE_CERTIFICATES
        elif task_type.startswith("dns."):
            return self.QUEUE_DNS
        else:
            return self.QUEUE_NOTIFICATIONS


# Singleton instance
task_service = TaskService()
