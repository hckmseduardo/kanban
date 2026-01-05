"""Sandbox management routes"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.auth.unified import AuthContext, require_scope
from app.config import settings
from app.models.sandbox import (
    SandboxCreateRequest,
    SandboxUpdateRequest,
    SandboxResponse,
    SandboxListResponse,
    SandboxStatusResponse,
    SandboxAgentRestartResponse,
)
from app.services.database_service import db_service
from app.services.task_service import task_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_base_domain() -> str:
    """Get the base domain without kanban. prefix if present"""
    domain = settings.domain
    # If domain already starts with 'kanban.', extract base domain
    if domain.startswith("kanban."):
        return domain[7:]  # Remove 'kanban.' prefix
    return domain


def get_sandbox_subdomain(full_slug: str) -> str:
    """Generate sandbox subdomain URL"""
    base_domain = _get_base_domain()
    if settings.port == 443:
        return f"https://{full_slug}.sandbox.{base_domain}"
    return f"https://{full_slug}.sandbox.{base_domain}:{settings.port}"


def get_agent_webhook_url(full_slug: str) -> str:
    """Generate agent webhook URL"""
    return f"{get_sandbox_subdomain(full_slug)}/agent/webhook"


def _sandbox_to_response(sandbox: dict, include_secret: bool = False) -> SandboxResponse:
    """Convert database sandbox to response model"""
    return SandboxResponse(
        id=sandbox["id"],
        workspace_id=sandbox["workspace_id"],
        slug=sandbox["slug"],
        full_slug=sandbox["full_slug"],
        name=sandbox["name"],
        description=sandbox.get("description"),
        owner_id=sandbox["owner_id"],
        git_branch=sandbox["git_branch"],
        source_branch=sandbox.get("source_branch", "main"),
        subdomain=get_sandbox_subdomain(sandbox["full_slug"]),
        database_name=sandbox["database_name"],
        agent_container_name=sandbox["agent_container_name"],
        agent_webhook_url=get_agent_webhook_url(sandbox["full_slug"]),
        agent_webhook_secret=sandbox.get("agent_webhook_secret") if include_secret else None,
        status=sandbox["status"],
        created_at=sandbox["created_at"],
        provisioned_at=sandbox.get("provisioned_at"),
    )


@router.get("", response_model=SandboxListResponse)
async def list_sandboxes(
    workspace_slug: str,
    auth: AuthContext = Depends(require_scope("sandboxes:read"))
):
    """
    List sandboxes for a workspace.

    Authentication: JWT or Portal API token
    Required scope: sandboxes:read
    """
    # Get and validate workspace
    workspace = db_service.get_workspace_by_slug(workspace_slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check access
    if workspace["owner_id"] != auth.user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Check if workspace has an app (sandboxes only for app workspaces)
    if not workspace.get("app_template_id"):
        raise HTTPException(
            status_code=400,
            detail="Sandboxes are only available for workspaces with an app"
        )

    sandboxes = db_service.get_sandboxes_by_workspace(workspace["id"])

    return SandboxListResponse(
        sandboxes=[_sandbox_to_response(s) for s in sandboxes],
        total=len(sandboxes)
    )


@router.get("/{sandbox_slug}", response_model=SandboxResponse)
async def get_sandbox(
    workspace_slug: str,
    sandbox_slug: str,
    auth: AuthContext = Depends(require_scope("sandboxes:read"))
):
    """
    Get sandbox details.

    Authentication: JWT or Portal API token
    Required scope: sandboxes:read
    """
    # Get and validate workspace
    workspace = db_service.get_workspace_by_slug(workspace_slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check access
    if workspace["owner_id"] != auth.user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get sandbox
    sandbox = db_service.get_sandbox_by_workspace_and_slug(workspace["id"], sandbox_slug)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    return _sandbox_to_response(sandbox)


@router.post("", response_model=dict)
async def create_sandbox(
    workspace_slug: str,
    request: SandboxCreateRequest,
    auth: AuthContext = Depends(require_scope("sandboxes:write"))
):
    """
    Create a new sandbox for a workspace.

    This starts an async provisioning process that will:
    1. Create a git branch from source_branch
    2. Clone the workspace database
    3. Deploy sandbox containers
    4. Provision a dedicated agent

    Authentication: JWT or Portal API token
    Required scope: sandboxes:write
    """
    # Get and validate workspace
    workspace = db_service.get_workspace_by_slug(workspace_slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check access
    if workspace["owner_id"] != auth.user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Check if workspace has an app
    if not workspace.get("app_template_id"):
        raise HTTPException(
            status_code=400,
            detail="Sandboxes are only available for workspaces with an app"
        )

    # Check if workspace is active
    if workspace["status"] != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot create sandbox: workspace is {workspace['status']}"
        )

    # Check if slug is available
    full_slug = f"{workspace['slug']}-{request.slug}"
    existing = db_service.get_sandbox_by_full_slug(full_slug)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Sandbox with slug '{request.slug}' already exists in this workspace"
        )

    # Create sandbox record
    sandbox_data = {
        "workspace_id": workspace["id"],
        "slug": request.slug,
        "full_slug": full_slug,
        "name": request.name,
        "description": request.description,
        "owner_id": auth.user["id"],
        "git_branch": f"sandbox/{full_slug}",
        "source_branch": request.source_branch,
        "database_name": full_slug.replace("-", "_"),
        "agent_container_name": f"kanban-agent-{full_slug}",
    }

    sandbox = db_service.create_sandbox(sandbox_data)

    # Create provisioning task
    task_id = await task_service.create_sandbox_provision_task(
        sandbox_id=sandbox["id"],
        workspace_id=workspace["id"],
        workspace_slug=workspace["slug"],
        sandbox_slug=sandbox["slug"],
        full_slug=sandbox["full_slug"],
        source_branch=request.source_branch,
        owner_id=auth.user["id"],
        github_org=workspace.get("github_org"),
        github_repo_name=workspace.get("github_repo_name"),
        azure_tenant_id=workspace.get("azure_tenant_id"),
        azure_app_id=workspace.get("azure_app_id"),
        azure_client_secret=workspace.get("azure_client_secret"),
        azure_object_id=workspace.get("azure_object_id"),
    )

    logger.info(
        f"Sandbox creation started: {full_slug} "
        f"(from branch: {request.source_branch}) "
        f"by {auth.user["id"]}"
    )

    return {
        "message": "Sandbox creation started",
        "sandbox": _sandbox_to_response(sandbox, include_secret=True),
        "task_id": task_id
    }


@router.get("/{sandbox_slug}/status", response_model=SandboxStatusResponse)
async def get_sandbox_status(
    workspace_slug: str,
    sandbox_slug: str,
    auth: AuthContext = Depends(require_scope("sandboxes:read"))
):
    """
    Get sandbox provisioning status.

    Authentication: JWT or Portal API token
    Required scope: sandboxes:read
    """
    # Get and validate workspace
    workspace = db_service.get_workspace_by_slug(workspace_slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check access
    if workspace["owner_id"] != auth.user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get sandbox
    sandbox = db_service.get_sandbox_by_workspace_and_slug(workspace["id"], sandbox_slug)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    # Get latest task for this sandbox
    tasks = await task_service.get_user_tasks(auth.user["id"], limit=50)
    sandbox_task = None
    for task in tasks:
        payload = task.get("payload", {})
        if payload.get("sandbox_id") == sandbox["id"]:
            sandbox_task = task
            break

    return SandboxStatusResponse(
        sandbox_id=sandbox["id"],
        status=sandbox["status"],
        progress=sandbox_task.get("progress") if sandbox_task else None,
        current_step=sandbox_task.get("current_step") if sandbox_task else None,
        error=sandbox_task.get("error") if sandbox_task else None,
    )


@router.put("/{sandbox_slug}", response_model=SandboxResponse)
async def update_sandbox(
    workspace_slug: str,
    sandbox_slug: str,
    request: SandboxUpdateRequest,
    auth: AuthContext = Depends(require_scope("sandboxes:write"))
):
    """
    Update sandbox details.

    Authentication: JWT or Portal API token
    Required scope: sandboxes:write
    """
    # Get and validate workspace
    workspace = db_service.get_workspace_by_slug(workspace_slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check access
    if workspace["owner_id"] != auth.user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get sandbox
    sandbox = db_service.get_sandbox_by_workspace_and_slug(workspace["id"], sandbox_slug)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    updates = {}
    if request.name is not None:
        updates["name"] = request.name
    if request.description is not None:
        updates["description"] = request.description

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    updated = db_service.update_sandbox(sandbox["id"], updates)
    logger.info(f"Sandbox updated: {sandbox['full_slug']} by {auth.user["id"]}")

    return _sandbox_to_response(updated)


@router.delete("/{sandbox_slug}")
async def delete_sandbox(
    workspace_slug: str,
    sandbox_slug: str,
    auth: AuthContext = Depends(require_scope("sandboxes:write"))
):
    """
    Delete a sandbox.

    This starts an async deletion process that will:
    1. Stop and remove containers
    2. Delete git branch
    3. Delete database
    4. Clean up agent

    Authentication: JWT or Portal API token
    Required scope: sandboxes:write
    """
    # Get and validate workspace
    workspace = db_service.get_workspace_by_slug(workspace_slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check access
    if workspace["owner_id"] != auth.user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get sandbox
    sandbox = db_service.get_sandbox_by_workspace_and_slug(workspace["id"], sandbox_slug)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    # Create deletion task
    task_id = await task_service.create_sandbox_delete_task(
        sandbox_id=sandbox["id"],
        workspace_id=workspace["id"],
        full_slug=sandbox["full_slug"],
        user_id=auth.user["id"],
        workspace_slug=workspace["slug"],
        github_org=workspace.get("github_org"),
        github_repo_name=workspace.get("github_repo_name"),
        azure_object_id=workspace.get("azure_object_id"),
    )

    # Update status to deleting
    db_service.update_sandbox(sandbox["id"], {"status": "deleting"})

    logger.info(f"Sandbox deletion started: {sandbox['full_slug']} by {auth.user["id"]}")

    return {
        "message": "Sandbox deletion started",
        "task_id": task_id
    }


@router.post("/{sandbox_slug}/agent/restart", response_model=SandboxAgentRestartResponse)
async def restart_sandbox_agent(
    workspace_slug: str,
    sandbox_slug: str,
    regenerate_secret: bool = False,
    auth: AuthContext = Depends(require_scope("sandboxes:write"))
):
    """
    Restart the sandbox agent.

    Optionally regenerate the webhook secret.

    Authentication: JWT or Portal API token
    Required scope: sandboxes:write
    """
    # Get and validate workspace
    workspace = db_service.get_workspace_by_slug(workspace_slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check access
    if workspace["owner_id"] != auth.user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get sandbox
    sandbox = db_service.get_sandbox_by_workspace_and_slug(workspace["id"], sandbox_slug)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    # Regenerate secret if requested
    new_secret = None
    if regenerate_secret:
        new_secret = db_service.regenerate_sandbox_webhook_secret(sandbox["id"])

    # Create restart task
    await task_service.create_sandbox_agent_restart_task(
        sandbox_id=sandbox["id"],
        full_slug=sandbox["full_slug"],
        user_id=auth.user["id"],
        regenerate_secret=regenerate_secret,
    )

    logger.info(
        f"Sandbox agent restart requested: {sandbox['full_slug']} "
        f"(regenerate_secret={regenerate_secret}) by {auth.user["id"]}"
    )

    return SandboxAgentRestartResponse(
        sandbox_id=sandbox["id"],
        agent_container_name=sandbox["agent_container_name"],
        new_webhook_secret=new_secret,
        message="Agent restart initiated" + (" with new webhook secret" if new_secret else "")
    )
