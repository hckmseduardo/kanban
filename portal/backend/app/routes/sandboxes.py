"""Sandbox management routes

Sandbox permissions are based on workspace team membership:
- List/View sandboxes: Any workspace member (viewer+)
- Create sandbox: Admin or owner
- Update sandbox: Admin or owner
- Delete sandbox: Sandbox owner, workspace admin, or workspace owner
- Pull request: Sandbox owner, workspace admin, or workspace owner
- Restart agent: Admin or owner
"""

import logging
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Header

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
from app.routes.workspaces import check_workspace_access

logger = logging.getLogger(__name__)


def get_workspace_with_role(
    workspace_slug: str,
    user_id: str,
    require_role: Optional[str] = None
) -> Tuple[dict, dict]:
    """
    Get workspace and verify user access with optional role requirement.

    Args:
        workspace_slug: Workspace slug
        user_id: User ID
        require_role: Optional minimum role required (owner, admin, member, viewer)

    Returns:
        Tuple of (workspace, membership)

    Raises:
        HTTPException if not found or insufficient access
    """
    workspace = db_service.get_workspace_by_slug(workspace_slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    has_access, membership = check_workspace_access(workspace, user_id, require_role)
    if not has_access:
        if membership and require_role:
            raise HTTPException(
                status_code=403,
                detail=f"Requires {require_role} role or higher"
            )
        raise HTTPException(status_code=403, detail="Access denied")

    return workspace, membership

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

    Access: Any workspace member (viewer+)

    Authentication: JWT or Portal API token
    Required scope: sandboxes:read
    """
    # Get workspace and verify access (any member can view)
    workspace, _ = get_workspace_with_role(workspace_slug, auth.user["id"])

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

    Access: Any workspace member (viewer+)

    Authentication: JWT or Portal API token
    Required scope: sandboxes:read
    """
    # Get workspace and verify access (any member can view)
    workspace, _ = get_workspace_with_role(workspace_slug, auth.user["id"])

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

    Access: Admin or owner only (or internal service)

    Authentication: JWT, Portal API token, or X-Service-Secret
    Required scope: sandboxes:write
    """
    # For internal service auth, skip role check but get workspace
    if auth.auth_type == "service":
        workspace = db_service.get_workspace_by_slug(workspace_slug)
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")
    else:
        # Get workspace and verify access (admin+ required to create)
        workspace, _ = get_workspace_with_role(
            workspace_slug, auth.user["id"], require_role="admin"
        )

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

    Access: Any workspace member (viewer+)

    Authentication: JWT or Portal API token
    Required scope: sandboxes:read
    """
    # Get workspace and verify access (any member can view status)
    workspace, _ = get_workspace_with_role(workspace_slug, auth.user["id"])

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

    Access: Admin or owner only

    Authentication: JWT or Portal API token
    Required scope: sandboxes:write
    """
    # Get workspace and verify access (admin+ required to update)
    workspace, _ = get_workspace_with_role(
        workspace_slug, auth.user["id"], require_role="admin"
    )

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

    Access: Sandbox owner, workspace admin, or workspace owner

    Authentication: JWT or Portal API token
    Required scope: sandboxes:write
    """
    # Get workspace and verify basic access first
    workspace, membership = get_workspace_with_role(workspace_slug, auth.user["id"])

    # Get sandbox
    sandbox = db_service.get_sandbox_by_workspace_and_slug(workspace["id"], sandbox_slug)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    # Check delete permission:
    # - Workspace owner can delete any sandbox
    # - Workspace admin can delete any sandbox
    # - Sandbox owner can delete their own sandbox
    user_role = membership["role"] if membership else None
    is_sandbox_owner = sandbox["owner_id"] == auth.user["id"]
    can_delete = (
        user_role in ("owner", "admin") or
        is_sandbox_owner
    )

    if not can_delete:
        raise HTTPException(
            status_code=403,
            detail="Only sandbox owner, workspace admin, or workspace owner can delete sandboxes"
        )

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


@router.post("/{sandbox_slug}/pull-request")
async def create_sandbox_pull_request(
    workspace_slug: str,
    sandbox_slug: str,
    auth: AuthContext = Depends(require_scope("sandboxes:write"))
):
    """
    Create and merge a pull request from a sandbox branch to main.

    This starts an async process that will:
    1. Create a PR from the sandbox branch to main
    2. Approve the PR
    3. Merge the PR
    4. Update workspace app code and rebuild containers

    Access: Sandbox owner, workspace admin, or workspace owner

    Authentication: JWT or Portal API token
    Required scope: sandboxes:write
    """
    # Get workspace and verify basic access
    workspace, membership = get_workspace_with_role(workspace_slug, auth.user["id"])

    # Ensure workspace has an app + repo
    if not workspace.get("app_template_id"):
        raise HTTPException(status_code=400, detail="Workspace does not have an app")

    github_org = workspace.get("github_org")
    github_repo_name = workspace.get("github_repo_name")
    if not github_org or not github_repo_name:
        raise HTTPException(status_code=400, detail="Workspace GitHub repository not configured")

    # Get sandbox
    sandbox = db_service.get_sandbox_by_workspace_and_slug(workspace["id"], sandbox_slug)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    # Permission check: sandbox owner OR workspace admin/owner
    is_sandbox_owner = sandbox["owner_id"] == auth.user["id"]
    is_workspace_admin = membership and membership.get("role") in ["owner", "admin"]
    if not (is_sandbox_owner or is_workspace_admin):
        raise HTTPException(
            status_code=403,
            detail="Only sandbox owner, workspace admin, or workspace owner can open a pull request"
        )

    # Check sandbox is in a deployable state
    if sandbox["status"] != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot create pull request for sandbox with status '{sandbox['status']}'"
        )

    task_id = await task_service.create_sandbox_pull_request_task(
        sandbox_id=sandbox["id"],
        workspace_id=workspace["id"],
        workspace_slug=workspace["slug"],
        sandbox_slug=sandbox["slug"],
        full_slug=sandbox["full_slug"],
        git_branch=sandbox["git_branch"],
        user_id=auth.user["id"],
        github_org=github_org,
        github_repo_name=github_repo_name,
    )

    logger.info(f"Sandbox PR started: {sandbox['full_slug']} by {auth.user['id']}")

    return {
        "message": "Sandbox pull request started",
        "task_id": task_id
    }


@router.post("/{sandbox_slug}/restart")
async def restart_sandbox(
    workspace_slug: str,
    sandbox_slug: str,
    auth: AuthContext = Depends(require_scope("sandboxes:write"))
):
    """
    Restart sandbox containers.

    This starts an async process that will:
    1. Pull latest code from the sandbox branch
    2. Stop existing containers
    3. Rebuild and start containers with the new code
    4. Run health check

    Use this when:
    - Sandbox containers are stopped/crashed
    - You need to apply code changes to the sandbox
    - The sandbox is returning 404 errors

    Access: Admin or owner only

    Authentication: JWT or Portal API token
    Required scope: sandboxes:write
    """
    # Get workspace and verify access (admin+ required)
    workspace, _ = get_workspace_with_role(
        workspace_slug, auth.user["id"], require_role="admin"
    )

    # Get sandbox
    sandbox = db_service.get_sandbox_by_workspace_and_slug(workspace["id"], sandbox_slug)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    # Check sandbox is in a restartable state
    if sandbox["status"] in ["provisioning", "deleting"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot restart sandbox with status '{sandbox['status']}'"
        )

    # Create restart task
    task_id = await task_service.create_sandbox_restart_task(
        sandbox_id=sandbox["id"],
        full_slug=sandbox["full_slug"],
        workspace_slug=workspace["slug"],
        user_id=auth.user["id"],
    )

    logger.info(f"Sandbox restart started: {sandbox['full_slug']} by {auth.user['id']}")

    return {
        "message": "Sandbox restart started",
        "task_id": task_id
    }


@router.post("/{sandbox_slug}/agent/regenerate-secret", response_model=SandboxAgentRestartResponse)
async def regenerate_agent_secret(
    workspace_slug: str,
    sandbox_slug: str,
    auth: AuthContext = Depends(require_scope("sandboxes:write"))
):
    """
    Regenerate the sandbox agent webhook secret.

    With on-demand agents, there's no container to restart. This endpoint
    only regenerates the webhook secret used to authenticate card events.

    Access: Admin or owner only

    Authentication: JWT or Portal API token
    Required scope: sandboxes:write
    """
    # Get workspace and verify access (admin+ required)
    workspace, _ = get_workspace_with_role(
        workspace_slug, auth.user["id"], require_role="admin"
    )

    # Get sandbox
    sandbox = db_service.get_sandbox_by_workspace_and_slug(workspace["id"], sandbox_slug)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    # Regenerate webhook secret
    new_secret = db_service.regenerate_sandbox_webhook_secret(sandbox["id"])

    logger.info(
        f"Sandbox agent secret regenerated: {sandbox['full_slug']} "
        f"by {auth.user['id']}"
    )

    return SandboxAgentRestartResponse(
        sandbox_id=sandbox["id"],
        agent_container_name=None,  # No container with on-demand agents
        new_webhook_secret=new_secret,
        message="Webhook secret regenerated"
    )


# ============================================================================
# Internal endpoints for service-to-service communication
# ============================================================================

@router.get("/internal/list", response_model=SandboxListResponse)
async def list_sandboxes_internal(
    workspace_slug: str,
    x_service_secret: str = Header(None, alias="X-Service-Secret")
):
    """
    Internal endpoint for service-to-service sandbox list access.

    This endpoint is called by team backends to get workspace sandboxes
    without user authentication, using service-to-service secret.

    Authentication: X-Service-Secret header with cross-domain secret
    """
    # Verify service secret
    if x_service_secret != settings.cross_domain_secret:
        raise HTTPException(status_code=403, detail="Invalid service secret")

    # Get workspace by slug
    workspace = db_service.get_workspace_by_slug(workspace_slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check if workspace has an app (sandboxes only for app workspaces)
    if not workspace.get("app_template_id"):
        # Return empty list for workspaces without apps
        return SandboxListResponse(sandboxes=[], total=0)

    sandboxes = db_service.get_sandboxes_by_workspace(workspace["id"])

    return SandboxListResponse(
        sandboxes=[_sandbox_to_response(s) for s in sandboxes],
        total=len(sandboxes)
    )


@router.post("/internal/create", response_model=dict)
async def create_sandbox_internal(
    workspace_slug: str,
    request: SandboxCreateRequest,
    x_service_secret: str = Header(None, alias="X-Service-Secret"),
    x_user_id: str = Header(None, alias="X-User-Id")
):
    """
    Internal endpoint for service-to-service sandbox creation.

    This endpoint is called by team backends to create sandboxes
    on behalf of a user, using service-to-service secret.

    Authentication: X-Service-Secret header with cross-domain secret
    X-User-Id header identifies the user creating the sandbox
    """
    # Verify service secret
    if x_service_secret != settings.cross_domain_secret:
        raise HTTPException(status_code=403, detail="Invalid service secret")

    if not x_user_id:
        raise HTTPException(status_code=400, detail="X-User-Id header required")

    # Get workspace by slug
    workspace = db_service.get_workspace_by_slug(workspace_slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

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
        "owner_id": x_user_id,
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
        owner_id=x_user_id,
        github_org=workspace.get("github_org"),
        github_repo_name=workspace.get("github_repo_name"),
        azure_tenant_id=workspace.get("azure_tenant_id"),
        azure_app_id=workspace.get("azure_app_id"),
        azure_client_secret=workspace.get("azure_client_secret"),
        azure_object_id=workspace.get("azure_object_id"),
    )

    logger.info(
        f"Sandbox creation started (internal): {full_slug} "
        f"(from branch: {request.source_branch}) "
        f"by user {x_user_id}"
    )

    return {
        "message": "Sandbox creation started",
        "sandbox": _sandbox_to_response(sandbox, include_secret=True),
        "task_id": task_id
    }
