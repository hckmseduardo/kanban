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
    QUEUE_AGENTS = "agents"  # On-demand AI agent tasks

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
                "action": "create_workspace",
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
            "action": "delete_workspace",
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

    async def create_workspace_restart_task(
        self,
        workspace_id: str,
        workspace_slug: str,
        user_id: str,
        rebuild: bool = False,
        restart_app: bool = True,
    ) -> str:
        """Create task to restart/rebuild workspace containers.

        This will:
        1. Stop kanban containers
        2. If rebuild=True, rebuild kanban images
        3. Start kanban containers
        4. If restart_app=True and app exists:
           - If rebuild=True, rebuild app containers
           - Otherwise just restart app containers
        5. Run health check
        """
        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_PROVISIONING,
            task_type="workspace.restart",
            payload={
                "workspace_id": workspace_id,
                "workspace_slug": workspace_slug,
                "rebuild": rebuild,
                "restart_app": restart_app,
            },
            user_id=user_id,
            priority="high"
        )

    async def create_workspace_start_task(
        self,
        workspace_id: str,
        workspace_slug: str,
        user_id: str,
        kanban_only: bool = False,
    ) -> str:
        """Create task to start/rebuild workspace components.

        This will:
        1. Validate workspace
        2. Rebuild and start kanban containers
        3. If kanban_only=False (default):
           - Rebuild and start app containers (if exists)
           - Rebuild and start sandbox containers (if any)
        4. Run health check

        Args:
            kanban_only: If True, only start kanban containers (faster for
                        when user just wants to open the kanban board)
        """
        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_PROVISIONING,
            task_type="workspace.start",
            payload={
                "workspace_id": workspace_id,
                "workspace_slug": workspace_slug,
                "kanban_only": kanban_only,
            },
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

    # =========================================================================
    # Agent Tasks (On-demand AI processing)
    # =========================================================================

    async def create_agent_task(
        self,
        card_id: str,
        card_title: str,
        card_description: str,
        column_name: str,
        agent_config: dict,
        sandbox_id: str,
        workspace_slug: str,
        git_branch: str,
        kanban_api_url: str,
        target_project_path: str,
        user_id: str,
        board_id: str = None,
        labels: list = None,
        priority: str = "normal",
        github_repo_url: str = None,
    ) -> str:
        """Create task for on-demand AI agent to process a card.

        This spawns a Claude Code subprocess to process the card
        using the agent configuration from kanban-team.

        Args:
            card_id: The card to process
            card_title: Card title for context
            card_description: Card description with requirements
            column_name: Current column name
            agent_config: Full agent configuration from kanban-team including:
                - agent_name: Agent type (developer, architect, etc.)
                - persona: System prompt for the agent
                - tool_profile: Claude Code tools to allow (readonly, developer, full-access)
                - timeout: Maximum execution time in seconds
                - column_success: Column to move card on success
                - column_failure: Column to move card on failure
            sandbox_id: Sandbox identifier for isolation
            workspace_slug: Workspace this card belongs to
            git_branch: Git branch to work on
            kanban_api_url: API URL for card updates
            target_project_path: Path to project directory
            user_id: User who triggered the agent
            board_id: Optional board ID
            labels: Optional card labels
            priority: Task priority (high/normal)
        """
        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_AGENTS,
            task_type="agent.process_card",
            payload={
                "card_id": card_id,
                "card_title": card_title,
                "card_description": card_description,
                "column_name": column_name,
                "agent_config": agent_config,
                "sandbox_id": sandbox_id,
                "workspace_slug": workspace_slug,
                "git_branch": git_branch,
                "kanban_api_url": kanban_api_url,
                "target_project_path": target_project_path,
                "board_id": board_id,
                "labels": labels or [],
                "github_repo_url": github_repo_url,
            },
            user_id=user_id,
            priority=priority
        )

    async def create_enhance_description_task(
        self,
        card_id: str,
        card_title: str,
        card_description: str,
        workspace_slug: str,
        kanban_api_url: str,
        user_id: str,
        options: dict = None,
        mode: str = "append",
        apply_labels: bool = True,
        add_checklist: bool = True,
        priority: str = "high",
    ) -> str:
        """Create task for AI to enhance a card's description.

        This spawns a Claude Code subprocess to analyze the card and generate:
        - Refined description
        - Acceptance criteria (as checklist items)
        - Complexity estimate
        - Suggested labels

        Args:
            card_id: The card to enhance
            card_title: Card title for context
            card_description: Current card description
            workspace_slug: Workspace this card belongs to
            kanban_api_url: API URL for card updates
            user_id: User who triggered the enhancement
            options: Enhancement options (acceptance_criteria, complexity_estimate, etc.)
            mode: "append" or "replace" for description update
            apply_labels: Whether to apply suggested labels
            add_checklist: Whether to add criteria to checklist
            priority: Task priority (high/normal)
        """
        return await redis_service.enqueue_task(
            queue_name=self.QUEUE_AGENTS,
            task_type="agent.enhance_description",
            payload={
                "card_id": card_id,
                "card_title": card_title,
                "card_description": card_description,
                "workspace_slug": workspace_slug,
                "kanban_api_url": kanban_api_url,
                "options": options or {
                    "acceptance_criteria": True,
                    "complexity_estimate": True,
                    "suggest_labels": True,
                    "refine_description": True,
                },
                "mode": mode,
                "apply_labels": apply_labels,
                "add_checklist": add_checklist,
            },
            user_id=user_id,
            priority=priority
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
        elif task_type.startswith("agent."):
            return self.QUEUE_AGENTS
        else:
            return self.QUEUE_NOTIFICATIONS


# Singleton instance
task_service = TaskService()
