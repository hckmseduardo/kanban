"""Workspace management routes

Workspace members are inherited from the workspace's kanban team.
This means:
- Workspace owner = Team owner
- Workspace members = Team members
- Access to workspace requires team membership
"""

import json
import logging
import uuid
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, EmailStr

from app.auth.unified import AuthContext, require_scope
from app.config import settings
from app.models.workspace import (
    WorkspaceCreateRequest,
    WorkspaceUpdateRequest,
    WorkspaceResponse,
    WorkspaceListResponse,
    WorkspaceStatusResponse,
    LinkAppFromTemplateRequest,
    LinkAppFromRepoRequest,
    UnlinkAppRequest,
    DeleteWorkspaceRequest,
)
from app.services.database_service import db_service
from app.services.task_service import task_service
from app.services.email_service import send_workspace_invitation_email
import httpx

logger = logging.getLogger(__name__)

router = APIRouter()


async def _add_member_to_kanban_team(
    workspace_slug: str,
    user_id: str,
    user_email: str,
    user_name: str,
    role: str
) -> bool:
    """
    Add a member to the kanban-team's members database.
    This is called when a user accepts a workspace invitation.

    The kanban-team uses its own database for members, separate from the portal.
    We need to add the member there so they can access the kanban board.
    """
    # Build kanban API URL
    if settings.port == 443 or settings.port == "443":
        kanban_api_url = f"https://{workspace_slug}.{settings.domain}/api"
    else:
        kanban_api_url = f"https://{workspace_slug}.{settings.domain}:{settings.port}/api"

    # Use the cross-domain secret for service-to-service authentication
    headers = {
        "X-Service-Secret": settings.cross_domain_secret
    }

    member_data = {
        "id": user_id,
        "email": user_email,
        "name": user_name or user_email.split("@")[0],
        "role": role
    }

    try:
        async with httpx.AsyncClient(timeout=30.0, verify=False, headers=headers) as client:
            response = await client.post(
                f"{kanban_api_url}/team/members",
                json=member_data
            )

            if response.status_code < 400:
                logger.info(
                    f"Added member {user_email} to kanban-team {workspace_slug} "
                    f"with role {role}"
                )
                return True
            elif response.status_code == 400:
                # Member might already exist - that's fine
                logger.info(
                    f"Member {user_email} may already exist in kanban-team {workspace_slug}: "
                    f"{response.text}"
                )
                return True
            else:
                logger.error(
                    f"Failed to add member to kanban-team {workspace_slug}: "
                    f"{response.status_code} - {response.text}"
                )
                return False

    except Exception as e:
        logger.error(f"Error adding member to kanban-team {workspace_slug}: {e}")
        # Don't fail the whole invitation acceptance - portal membership is already set
        return False


# Member request/response models
class WorkspaceMemberResponse(BaseModel):
    user_id: str
    email: str
    name: Optional[str] = None
    role: str  # owner, admin, member, viewer
    joined_at: Optional[str] = None


class WorkspaceMembersListResponse(BaseModel):
    members: list[WorkspaceMemberResponse]
    total: int


class AddMemberRequest(BaseModel):
    email: EmailStr
    role: str = "member"  # owner, admin, member, viewer


class UpdateMemberRequest(BaseModel):
    role: str  # owner, admin, member, viewer


def check_workspace_access(
    workspace: dict,
    user_id: str,
    require_role: Optional[str] = None
) -> Tuple[bool, Optional[dict]]:
    """
    Check if user has access to workspace via team membership.

    Args:
        workspace: The workspace dict
        user_id: The user ID to check
        require_role: Optional minimum role required (owner, admin, member, viewer)

    Returns:
        Tuple of (has_access, membership_dict)
    """
    # Check team membership
    team_id = workspace.get("kanban_team_id")
    if not team_id:
        return False, None

    membership = db_service.get_membership(team_id, user_id)
    if not membership:
        return False, None

    # If specific role required, check hierarchy
    if require_role:
        role_hierarchy = {"owner": 4, "admin": 3, "member": 2, "viewer": 1}
        user_level = role_hierarchy.get(membership["role"], 0)
        required_level = role_hierarchy.get(require_role, 0)
        if user_level < required_level:
            return False, membership

    return True, membership


def get_workspace_with_access(
    slug: str,
    user_id: str,
    require_role: Optional[str] = None
) -> Tuple[dict, dict]:
    """
    Get workspace and verify user access.

    Args:
        slug: Workspace slug
        user_id: User ID
        require_role: Optional minimum role required

    Returns:
        Tuple of (workspace, membership)

    Raises:
        HTTPException if not found or no access
    """
    workspace = db_service.get_workspace_by_slug(slug)
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


def _get_base_domain() -> str:
    """Get the base domain without kanban. prefix if present"""
    domain = settings.domain
    # If domain already starts with 'kanban.', extract base domain
    if domain.startswith("kanban."):
        return domain[7:]  # Remove 'kanban.' prefix
    return domain


def get_kanban_subdomain(slug: str) -> str:
    """Generate kanban team subdomain URL"""
    base_domain = _get_base_domain()
    if settings.port == 443:
        return f"https://{slug}.kanban.{base_domain}"
    return f"https://{slug}.kanban.{base_domain}:{settings.port}"


def get_app_subdomain(slug: str) -> str:
    """Generate app subdomain URL"""
    base_domain = _get_base_domain()
    if settings.port == 443:
        return f"https://{slug}.app.{base_domain}"
    return f"https://{slug}.app.{base_domain}:{settings.port}"


def _workspace_to_response(workspace: dict, user_id: str = None) -> WorkspaceResponse:
    """Convert database workspace to response model"""
    # Get template slug if workspace has an app
    app_template_slug = None
    if workspace.get("app_template_id"):
        template = db_service.get_app_template_by_id(workspace["app_template_id"])
        if template:
            app_template_slug = template["slug"]

    # Get user's role in this workspace from team membership
    user_role = None
    if user_id and workspace.get("kanban_team_id"):
        membership = db_service.get_membership(workspace["kanban_team_id"], user_id)
        if membership:
            user_role = membership.get("role")

    return WorkspaceResponse(
        id=workspace["id"],
        slug=workspace["slug"],
        name=workspace["name"],
        description=workspace.get("description"),
        user_role=user_role,
        kanban_team_id=workspace.get("kanban_team_id"),
        kanban_subdomain=get_kanban_subdomain(workspace["slug"]),
        app_template_id=workspace.get("app_template_id"),
        app_template_slug=app_template_slug,
        github_repo_url=workspace.get("github_repo_url"),
        github_repo_name=workspace.get("github_repo_name"),
        app_subdomain=get_app_subdomain(workspace["slug"]) if (workspace.get("app_template_id") or workspace.get("github_repo_url")) else None,
        app_database_name=workspace.get("app_database_name"),
        azure_app_id=workspace.get("azure_app_id"),
        azure_object_id=workspace.get("azure_object_id"),
        status=workspace["status"],
        created_at=workspace["created_at"],
        provisioned_at=workspace.get("provisioned_at"),
    )


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    auth: AuthContext = Depends(require_scope("workspaces:read"))
):
    """
    List workspaces for the current user.

    Returns workspaces where user is:
    - Owner of the workspace
    - Member of the workspace's kanban team

    Authentication: JWT or Portal API token
    Required scope: workspaces:read
    """
    user_id = auth.user["id"]

    # Get workspaces user owns
    owned_workspaces = db_service.get_user_workspaces(user_id)
    owned_ids = {w["id"] for w in owned_workspaces}

    # Get workspaces where user is a team member
    member_workspaces = db_service.get_workspaces_by_team_member(user_id)

    # Combine and deduplicate
    all_workspaces = list(owned_workspaces)
    for ws in member_workspaces:
        if ws["id"] not in owned_ids:
            all_workspaces.append(ws)

    return WorkspaceListResponse(
        workspaces=[_workspace_to_response(w, user_id) for w in all_workspaces],
        total=len(all_workspaces)
    )


@router.get("/{slug}", response_model=WorkspaceResponse)
async def get_workspace(
    slug: str,
    auth: AuthContext = Depends(require_scope("workspaces:read"))
):
    """
    Get workspace details by slug.

    Access: Owner or team member (any role)

    Authentication: JWT or Portal API token
    Required scope: workspaces:read
    """
    workspace, _ = get_workspace_with_access(slug, auth.user["id"])
    return _workspace_to_response(workspace, auth.user["id"])


@router.post("", response_model=dict)
async def create_workspace(
    request: WorkspaceCreateRequest,
    auth: AuthContext = Depends(require_scope("workspaces:write"))
):
    """
    Create a new workspace.

    This starts an async provisioning process that will:
    1. Create a kanban team for the workspace
    2. If app_template_slug is provided:
       - Create a GitHub repo from the template
       - Deploy the app containers
       - Provision a dedicated agent

    Authentication: JWT or Portal API token
    Required scope: workspaces:write
    """
    # Check if slug is available
    existing = db_service.get_workspace_by_slug(request.slug)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Workspace with slug '{request.slug}' already exists"
        )

    # Also check if team slug is available
    existing_team = db_service.get_team_by_slug(request.slug)
    if existing_team:
        raise HTTPException(
            status_code=400,
            detail=f"Team with slug '{request.slug}' already exists"
        )

    # Validate app template if provided
    app_template = None
    if request.app_template_slug:
        app_template = db_service.get_app_template_by_slug(request.app_template_slug)
        if not app_template:
            raise HTTPException(
                status_code=400,
                detail=f"App template '{request.app_template_slug}' not found"
            )
        if not app_template.get("active", True):
            raise HTTPException(
                status_code=400,
                detail=f"App template '{request.app_template_slug}' is not active"
            )

    # Create workspace record
    # Note: owner is added as a member with role="owner" when workspace becomes active
    # We store created_by so the workspace appears in their list immediately during provisioning
    workspace_data = {
        "slug": request.slug,
        "name": request.name,
        "description": request.description,
        "created_by": auth.user["id"],  # Track who created the workspace
        "kanban_team_id": None,  # Will be set during provisioning
        "app_template_id": app_template["id"] if app_template else None,
        "github_org": request.github_org,
        "github_repo_url": None,  # Will be set during provisioning
        "github_repo_name": None,  # Will be set during provisioning
        "app_database_name": None,  # Will be set during provisioning
    }

    workspace = db_service.create_workspace(workspace_data)

    # Get user info for task
    user_email = auth.user.get("email")
    user_name = auth.user.get("display_name")

    # Create provisioning task
    task_id = await task_service.create_workspace_provision_task(
        workspace_id=workspace["id"],
        workspace_slug=workspace["slug"],
        owner_id=auth.user["id"],
        owner_email=user_email,
        owner_name=user_name,
        app_template_id=workspace.get("app_template_id"),
        template_owner=app_template.get("github_template_owner") if app_template else None,
        template_repo=app_template.get("github_template_repo") if app_template else None,
        github_org=request.github_org,
    )

    logger.info(
        f"Workspace creation started: {workspace['slug']} "
        f"(template: {request.app_template_slug or 'kanban-only'}) "
        f"by {auth.user['id']}"
    )

    return {
        "message": "Workspace creation started",
        "workspace": _workspace_to_response(workspace, auth.user["id"]),
        "task_id": task_id
    }


@router.get("/{slug}/status", response_model=WorkspaceStatusResponse)
async def get_workspace_status(
    slug: str,
    auth: AuthContext = Depends(require_scope("workspaces:read"))
):
    """
    Get workspace provisioning status.

    Access: Owner or team member (any role)

    Authentication: JWT or Portal API token
    Required scope: workspaces:read
    """
    workspace, _ = get_workspace_with_access(slug, auth.user["id"])

    # Get latest task for this workspace (check owner's tasks)
    workspace_task = None
    if workspace.get("kanban_team_id"):
        owner = db_service.get_team_owner(workspace["kanban_team_id"])
        if owner:
            tasks = await task_service.get_user_tasks(owner["id"], limit=50)
            for task in tasks:
                payload = task.get("payload", {})
                if payload.get("workspace_id") == workspace["id"]:
                    workspace_task = task
                    break

    return WorkspaceStatusResponse(
        workspace_id=workspace["id"],
        status=workspace["status"],
        progress=workspace_task.get("progress") if workspace_task else None,
        current_step=workspace_task.get("current_step") if workspace_task else None,
        error=workspace_task.get("error") if workspace_task else None,
    )


@router.put("/{slug}", response_model=WorkspaceResponse)
async def update_workspace(
    slug: str,
    request: WorkspaceUpdateRequest,
    auth: AuthContext = Depends(require_scope("workspaces:write"))
):
    """
    Update workspace details.

    Access: Owner or admin only

    Authentication: JWT or Portal API token
    Required scope: workspaces:write
    """
    workspace, membership = get_workspace_with_access(
        slug, auth.user["id"], require_role="admin"
    )

    updates = {}
    if request.name is not None:
        updates["name"] = request.name
    if request.description is not None:
        updates["description"] = request.description

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    updated = db_service.update_workspace(workspace["id"], updates)
    logger.info(f"Workspace updated: {slug} by {auth.user['id']}")

    return _workspace_to_response(updated, auth.user["id"])


@router.delete("/{slug}")
async def delete_workspace(
    slug: str,
    request: DeleteWorkspaceRequest = DeleteWorkspaceRequest(),
    auth: AuthContext = Depends(require_scope("workspaces:write"))
):
    """
    Delete a workspace.

    This starts an async deletion process that will:
    1. Delete all sandboxes
    2. Delete the app (if present)
    3. Delete the kanban team
    4. Delete the GitHub repo (if delete_github_repo=True)
    5. Remove all data

    Access: Owner only

    Authentication: JWT or Portal API token
    Required scope: workspaces:write
    """
    workspace, membership = get_workspace_with_access(
        slug, auth.user["id"], require_role="owner"
    )

    # Get sandboxes to delete
    sandboxes = db_service.get_sandboxes_by_workspace(workspace["id"])
    sandbox_list = [
        {"id": s["id"], "full_slug": s["full_slug"]}
        for s in sandboxes
    ]

    # Create deletion task
    task_id = await task_service.create_workspace_delete_task(
        workspace_id=workspace["id"],
        workspace_slug=workspace["slug"],
        user_id=auth.user["id"],
        azure_object_id=workspace.get("azure_object_id"),
        sandboxes=sandbox_list,
        github_org=workspace.get("github_org"),
        github_repo_name=workspace.get("github_repo_name"),
        delete_github_repo=request.delete_github_repo,
    )

    # Update status to deleting
    db_service.update_workspace(workspace["id"], {"status": "deleting"})

    logger.info(f"Workspace deletion started: {slug} by {auth.user['id']} (delete_repo={request.delete_github_repo})")

    return {
        "message": "Workspace deletion started",
        "task_id": task_id
    }


class WorkspaceRestartRequest(BaseModel):
    """Request to restart workspace containers"""
    rebuild: bool = False  # If true, rebuild images from scratch
    restart_app: bool = True  # If true, also restart app containers


@router.post("/{slug}/restart")
async def restart_workspace(
    slug: str,
    request: WorkspaceRestartRequest = WorkspaceRestartRequest(),
    auth: AuthContext = Depends(require_scope("workspaces:write"))
):
    """
    Restart/rebuild workspace containers.

    This starts an async restart process that will:
    1. Stop kanban containers
    2. If rebuild=True, rebuild kanban images from scratch
    3. Start kanban containers
    4. If restart_app=True and app exists, restart/rebuild app containers
    5. Run health check

    Access: Owner or admin only

    Authentication: JWT or Portal API token
    Required scope: workspaces:write
    """
    workspace, membership = get_workspace_with_access(
        slug, auth.user["id"], require_role="admin"
    )

    # Check workspace is active
    if workspace.get("status") not in ["active", None]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot restart workspace with status '{workspace.get('status')}'"
        )

    # Create restart task
    task_id = await task_service.create_workspace_restart_task(
        workspace_id=workspace["id"],
        workspace_slug=workspace["slug"],
        user_id=auth.user["id"],
        rebuild=request.rebuild,
        restart_app=request.restart_app,
    )

    logger.info(
        f"Workspace restart started: {slug} by {auth.user['id']} "
        f"(rebuild={request.rebuild}, restart_app={request.restart_app})"
    )

    return {
        "message": "Workspace restart started",
        "task_id": task_id,
        "rebuild": request.rebuild,
        "restart_app": request.restart_app
    }


@router.post("/{slug}/start")
async def start_workspace(
    slug: str,
    auth: AuthContext = Depends(require_scope("workspaces:write"))
):
    """
    Start workspace containers (rebuild and start all components).

    This starts an async process that will:
    1. Validate workspace
    2. Rebuild and start kanban containers
    3. Rebuild and start app containers (if exists)
    4. Rebuild and start sandbox containers (if any)
    5. Run health check

    Access: Owner or admin only

    Authentication: JWT or Portal API token
    Required scope: workspaces:write
    """
    workspace, membership = get_workspace_with_access(
        slug, auth.user["id"], require_role="admin"
    )

    # Check workspace is active (not provisioning or deleted)
    if workspace.get("status") not in ["active", None]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start workspace with status '{workspace.get('status')}'"
        )

    # Create start task
    task_id = await task_service.create_workspace_start_task(
        workspace_id=workspace["id"],
        workspace_slug=workspace["slug"],
        user_id=auth.user["id"],
    )

    logger.info(f"Workspace start initiated: {slug} by {auth.user['id']}")

    return {
        "message": "Workspace start initiated",
        "task_id": task_id
    }


@router.post("/{slug}/start-kanban")
async def start_workspace_kanban(
    slug: str,
    auth: AuthContext = Depends(require_scope("workspaces:write"))
):
    """
    Start only the kanban containers for this workspace.

    This is a faster alternative to /start when the user only needs to
    access the kanban board. It will NOT start app or sandbox containers.

    This starts an async process that will:
    1. Validate workspace
    2. Rebuild and start kanban containers
    3. Run health check (kanban only)

    Access: Owner or admin only

    Authentication: JWT or Portal API token
    Required scope: workspaces:write
    """
    workspace, membership = get_workspace_with_access(
        slug, auth.user["id"], require_role="admin"
    )

    # Check workspace is active (not provisioning or deleted)
    if workspace.get("status") not in ["active", None]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start workspace with status '{workspace.get('status')}'"
        )

    # Create start task with kanban_only flag
    task_id = await task_service.create_workspace_start_task(
        workspace_id=workspace["id"],
        workspace_slug=workspace["slug"],
        user_id=auth.user["id"],
        kanban_only=True,
    )

    logger.info(f"Workspace kanban start initiated: {slug} by {auth.user['id']}")

    return {
        "message": "Kanban start initiated",
        "task_id": task_id
    }


# ============================================================================
# Link/Unlink App Endpoints
# ============================================================================


@router.post("/{slug}/link-app")
async def link_app_to_workspace(
    slug: str,
    request: LinkAppFromTemplateRequest | LinkAppFromRepoRequest,
    auth: AuthContext = Depends(require_scope("workspaces:write"))
):
    """
    Link an app to an existing kanban-only workspace.

    Two modes:
    1. From template: Creates a new GitHub repo from the app template
    2. From existing repo: Uses an existing GitHub repository

    This starts an async provisioning process that will:
    1. Create or validate GitHub repository
    2. Create Azure app registration
    3. Clone repository locally
    4. Create app database
    5. Deploy Docker containers
    6. Create foundation sandbox

    Access: Owner or admin only

    Authentication: JWT or Portal API token
    Required scope: workspaces:write
    """
    import re

    workspace, membership = get_workspace_with_access(
        slug, auth.user["id"], require_role="admin"
    )

    # Validate workspace is active
    if workspace.get("status") != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot link app to workspace with status '{workspace.get('status')}'"
        )

    # Validate workspace doesn't already have an app
    if workspace.get("app_template_id"):
        raise HTTPException(
            status_code=400,
            detail="Workspace already has an app linked"
        )

    # Determine mode and validate
    app_template = None
    github_repo_url = None
    github_repo_name = None
    github_org = None

    if isinstance(request, LinkAppFromTemplateRequest):
        # Template mode - validate template exists and is active
        app_template = db_service.get_app_template_by_slug(request.app_template_slug)
        if not app_template:
            raise HTTPException(
                status_code=400,
                detail=f"App template '{request.app_template_slug}' not found"
            )
        if not app_template.get("active", True):
            raise HTTPException(
                status_code=400,
                detail=f"App template '{request.app_template_slug}' is not active"
            )
        github_org = request.github_org
    else:
        # Existing repo mode - parse URL
        github_repo_url = request.github_repo_url
        match = re.match(r"https://github\.com/([\w-]+)/([\w.-]+)", github_repo_url)
        if not match:
            raise HTTPException(
                status_code=400,
                detail="Invalid GitHub repository URL format"
            )
        github_org = match.group(1)
        github_repo_name = match.group(2)

    # Update workspace status to linking
    db_service.update_workspace(workspace["id"], {"status": "linking_app"})

    # Create link app task
    task_id = await task_service.create_workspace_link_app_task(
        workspace_id=workspace["id"],
        workspace_slug=workspace["slug"],
        user_id=auth.user["id"],
        app_template_id=app_template["id"] if app_template else None,
        template_owner=app_template.get("github_template_owner") if app_template else None,
        template_repo=app_template.get("github_template_repo") if app_template else None,
        github_org=github_org,
        github_repo_url=github_repo_url,
        github_repo_name=github_repo_name,
    )

    logger.info(
        f"App linking started for workspace {slug} "
        f"(template: {app_template['slug'] if app_template else 'existing-repo'}) "
        f"by {auth.user['id']}"
    )

    # Refresh workspace data
    workspace = db_service.get_workspace_by_slug(slug)

    return {
        "message": "App linking started",
        "workspace": _workspace_to_response(workspace, auth.user["id"]),
        "task_id": task_id
    }


@router.post("/{slug}/unlink-app")
async def unlink_app_from_workspace(
    slug: str,
    request: UnlinkAppRequest,
    auth: AuthContext = Depends(require_scope("workspaces:write"))
):
    """
    Unlink app from workspace, keeping kanban team intact.

    This starts an async process that will:
    1. Delete all sandboxes associated with the app
    2. Stop and remove app containers
    3. Delete Azure app registration
    4. Optionally delete GitHub repository
    5. Clear app-related fields from workspace

    Access: Owner or admin only

    Authentication: JWT or Portal API token
    Required scope: workspaces:write
    """
    workspace, membership = get_workspace_with_access(
        slug, auth.user["id"], require_role="admin"
    )

    # Validate workspace is active
    if workspace.get("status") != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot unlink app from workspace with status '{workspace.get('status')}'"
        )

    # Validate workspace has an app
    if not workspace.get("app_template_id") and not workspace.get("github_repo_url"):
        raise HTTPException(
            status_code=400,
            detail="Workspace does not have an app to unlink"
        )

    # Update workspace status to unlinking
    db_service.update_workspace(workspace["id"], {"status": "unlinking_app"})

    # Create unlink app task
    task_id = await task_service.create_workspace_unlink_app_task(
        workspace_id=workspace["id"],
        workspace_slug=workspace["slug"],
        user_id=auth.user["id"],
        azure_object_id=workspace.get("azure_object_id"),
        github_org=workspace.get("github_org"),
        github_repo_name=workspace.get("github_repo_name"),
        delete_github_repo=request.delete_github_repo,
    )

    logger.info(
        f"App unlinking started for workspace {slug} "
        f"(delete_repo={request.delete_github_repo}) by {auth.user['id']}"
    )

    return {
        "message": "App unlinking started",
        "task_id": task_id
    }


@router.get("/health/batch")
async def get_workspaces_health_batch(
    auth: AuthContext = Depends(require_scope("workspaces:read"))
):
    """
    Get health status for all user's workspaces.

    Returns the running status of containers for all workspaces the user has access to.

    Authentication: JWT or Portal API token
    Required scope: workspaces:read
    """
    from app.models.workspace import WorkspaceHealthResponse, WorkspaceHealthBatchResponse, SandboxHealthStatus
    import uuid
    import asyncio

    # Get all workspaces for this user
    workspaces = db_service.get_user_workspaces(auth.user["id"])
    if not workspaces:
        return WorkspaceHealthBatchResponse(workspaces={})

    # Only check active workspaces
    active_workspaces = [w for w in workspaces if w.get("status") == "active"]
    if not active_workspaces:
        return WorkspaceHealthBatchResponse(workspaces={})

    # Request health check for all workspaces
    request_id = str(uuid.uuid4())
    workspace_slugs = [w["slug"] for w in active_workspaces]
    health_request = {
        "request_id": request_id,
        "workspace_slugs": workspace_slugs
    }

    # Get Redis connection
    from app.services.redis_service import redis_service

    # Push health check request
    await redis_service.client.lpush("health_check:requests", json.dumps(health_request))

    # Wait for result (poll for up to 15 seconds for batch)
    for _ in range(150):  # 150 * 0.1s = 15s timeout
        result = await redis_service.client.get(f"health_check:{request_id}:result")
        if result:
            health_data = json.loads(result)

            # Build response with workspace IDs
            workspace_health = {}
            for ws in active_workspaces:
                ws_health = health_data.get(ws["slug"], {})
                sandboxes = [
                    SandboxHealthStatus(
                        slug=s.get("slug", ""),
                        full_slug=s.get("full_slug", ""),
                        running=s.get("running", False)
                    )
                    for s in ws_health.get("sandboxes", [])
                ]
                workspace_health[ws["slug"]] = WorkspaceHealthResponse(
                    workspace_id=ws["id"],
                    workspace_slug=ws["slug"],
                    kanban_running=ws_health.get("kanban_running", False),
                    app_running=ws_health.get("app_running"),
                    sandboxes=sandboxes,
                    all_healthy=ws_health.get("all_healthy", False)
                )

            return WorkspaceHealthBatchResponse(workspaces=workspace_health)
        await asyncio.sleep(0.1)

    # Timeout - return unknown status
    raise HTTPException(
        status_code=504,
        detail="Health check timeout - orchestrator may be unavailable"
    )


@router.get("/{slug}/health")
async def get_workspace_health(
    slug: str,
    auth: AuthContext = Depends(require_scope("workspaces:read"))
):
    """
    Get workspace container health status.

    Returns the running status of kanban, app, and sandbox containers.

    Access: Any team member

    Authentication: JWT or Portal API token
    Required scope: workspaces:read
    """
    from app.models.workspace import WorkspaceHealthResponse, SandboxHealthStatus
    import uuid

    workspace, _ = get_workspace_with_access(slug, auth.user["id"])

    # Request health check from orchestrator via Redis
    request_id = str(uuid.uuid4())
    health_request = {
        "request_id": request_id,
        "workspace_slugs": [workspace["slug"]]
    }

    # Get Redis connection
    from app.services.redis_service import redis_service

    # Push health check request
    await redis_service.client.lpush("health_check:requests", json.dumps(health_request))

    # Wait for result (poll for up to 10 seconds)
    import asyncio
    for _ in range(100):  # 100 * 0.1s = 10s timeout
        result = await redis_service.client.get(f"health_check:{request_id}:result")
        if result:
            health_data = json.loads(result)
            workspace_health = health_data.get(workspace["slug"], {})

            # Convert sandbox data to SandboxHealthStatus objects
            sandboxes = [
                SandboxHealthStatus(
                    slug=s.get("slug", ""),
                    full_slug=s.get("full_slug", ""),
                    running=s.get("running", False)
                )
                for s in workspace_health.get("sandboxes", [])
            ]

            return WorkspaceHealthResponse(
                workspace_id=workspace["id"],
                workspace_slug=workspace["slug"],
                kanban_running=workspace_health.get("kanban_running", False),
                app_running=workspace_health.get("app_running"),
                sandboxes=sandboxes,
                all_healthy=workspace_health.get("all_healthy", False)
            )
        await asyncio.sleep(0.1)

    # Timeout - return unknown status
    raise HTTPException(
        status_code=504,
        detail="Health check timeout - orchestrator may be unavailable"
    )


# ============================================================================
# Workspace Member Endpoints
# Members are inherited from the workspace's kanban team
# ============================================================================


@router.get("/{slug}/members", response_model=WorkspaceMembersListResponse)
async def list_workspace_members(
    slug: str,
    auth: AuthContext = Depends(require_scope("members:read"))
):
    """
    List workspace members.

    Members are inherited from the workspace's kanban team.

    Access: Any team member can view members

    Authentication: JWT or Portal API token
    Required scope: members:read
    """
    workspace, _ = get_workspace_with_access(slug, auth.user["id"])

    if not workspace.get("kanban_team_id"):
        return WorkspaceMembersListResponse(members=[], total=0)

    # Get team members
    team_members = db_service.get_team_members(workspace["kanban_team_id"])

    members = [
        WorkspaceMemberResponse(
            user_id=m["id"],
            email=m["email"],
            name=m.get("display_name") or m.get("name"),
            role=m["role"],
            joined_at=m.get("joined_at")
        )
        for m in team_members
    ]

    return WorkspaceMembersListResponse(
        members=members,
        total=len(members)
    )


@router.get("/internal/{slug}/members", response_model=WorkspaceMembersListResponse)
async def list_workspace_members_internal(
    slug: str,
    x_service_secret: str = Header(None, alias="X-Service-Secret")
):
    """
    Internal endpoint for service-to-service member list access.

    This endpoint is called by team backends to get workspace members
    without user authentication, using service-to-service secret.

    Authentication: X-Service-Secret header with cross-domain secret
    """
    # Verify service secret
    if x_service_secret != settings.cross_domain_secret:
        raise HTTPException(status_code=403, detail="Invalid service secret")

    # Get workspace by slug
    workspace = db_service.get_workspace_by_slug(slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if not workspace.get("kanban_team_id"):
        return WorkspaceMembersListResponse(members=[], total=0)

    # Get team members
    team_members = db_service.get_team_members(workspace["kanban_team_id"])

    members = [
        WorkspaceMemberResponse(
            user_id=m["id"],
            email=m["email"],
            name=m.get("display_name") or m.get("name"),
            role=m["role"],
            joined_at=m.get("joined_at")
        )
        for m in team_members
    ]

    return WorkspaceMembersListResponse(
        members=members,
        total=len(members)
    )


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "member"  # owner, admin, member, viewer


class WorkspaceInvitationResponse(BaseModel):
    id: str
    workspace_id: str
    email: str
    role: str
    status: str
    invite_url: str
    invited_by: str
    created_at: str
    expires_at: str


class WorkspaceInvitationsListResponse(BaseModel):
    invitations: list[WorkspaceInvitationResponse]
    total: int


def _get_invite_url(token: str) -> str:
    """Generate the invitation URL"""
    base_domain = _get_base_domain()
    base_url = f"https://kanban.{base_domain}"
    if settings.port != 443:
        base_url = f"{base_url}:{settings.port}"
    return f"{base_url}/accept-invite?token={token}"


def _invitation_to_response(invitation: dict) -> WorkspaceInvitationResponse:
    """Convert database invitation to response model"""
    return WorkspaceInvitationResponse(
        id=invitation["id"],
        workspace_id=invitation["workspace_id"],
        email=invitation["email"],
        role=invitation["role"],
        status=invitation["status"],
        invite_url=_get_invite_url(invitation["token"]),
        invited_by=invitation["invited_by"],
        created_at=invitation["created_at"],
        expires_at=invitation["expires_at"],
    )


@router.post("/{slug}/members", response_model=WorkspaceInvitationResponse)
async def invite_workspace_member(
    slug: str,
    request: InviteMemberRequest,
    auth: AuthContext = Depends(require_scope("members:write"))
):
    """
    Invite a member to the workspace.

    Creates an invitation that can be shared with the user. When the user
    signs in and accepts the invitation, they will be added to the workspace.

    If the user already has an account, they can accept immediately.
    If not, they can sign up and then accept the invitation.

    Access rules:
    - Owners can invite members with any role (owner, admin, member, viewer)
    - Admins can invite members as admin, member, or viewer
    - Admins cannot invite as owner

    Authentication: JWT or Portal API token
    Required scope: members:write
    """
    workspace, caller_membership = get_workspace_with_access(
        slug, auth.user["id"], require_role="admin"
    )

    if not workspace.get("kanban_team_id"):
        raise HTTPException(
            status_code=400,
            detail="Workspace does not have a kanban team yet"
        )

    # Validate role
    valid_roles = ["owner", "admin", "member", "viewer"]
    if request.role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}"
        )

    # Get caller's membership to check permissions
    caller_is_owner = caller_membership and caller_membership["role"] == "owner"

    # Only owners can invite as owner
    if request.role == "owner" and not caller_is_owner:
        raise HTTPException(
            status_code=403,
            detail="Only owners can invite members as owner"
        )

    # Check if user is already a member
    user = db_service.get_user_by_email(request.email)
    if user:
        existing = db_service.get_membership(workspace["kanban_team_id"], user["id"])
        if existing:
            raise HTTPException(
                status_code=400,
                detail="User is already a member of this workspace"
            )

    # Check if there's already a pending invitation
    existing_invite = db_service.get_pending_invitation_for_email(
        workspace["id"], request.email
    )
    if existing_invite:
        raise HTTPException(
            status_code=400,
            detail="There is already a pending invitation for this email"
        )

    # Create invitation
    invitation = db_service.create_workspace_invitation(
        workspace_id=workspace["id"],
        email=request.email,
        role=request.role,
        invited_by=auth.user["id"],
    )

    # Generate invite URL
    invite_url = _get_invite_url(invitation["token"])

    # Get inviter name for email
    inviter_name = auth.user.get("display_name") or auth.user.get("email", "A workspace admin")

    # Send invitation email
    email_result = send_workspace_invitation_email(
        to_email=request.email,
        invite_link=invite_url,
        workspace_name=workspace["name"],
        invited_by=inviter_name,
        role=request.role,
    )

    if email_result.get("sent"):
        logger.info(
            f"Invitation email sent to {request.email} for workspace {slug} "
            f"with role {request.role} by {auth.user['id']}"
        )
    else:
        logger.warning(
            f"Failed to send invitation email to {request.email}: {email_result.get('error')}. "
            f"Invitation was created but email not sent."
        )

    return _invitation_to_response(invitation)


@router.patch("/{slug}/members/{user_id}", response_model=WorkspaceMemberResponse)
async def update_workspace_member(
    slug: str,
    user_id: str,
    request: UpdateMemberRequest,
    auth: AuthContext = Depends(require_scope("members:write"))
):
    """
    Update a workspace member's role.

    Access rules:
    - Owners can change any member's role (including other owners)
    - Owners can promote/demote to any role (owner, admin, member, viewer)
    - Admins can promote members/viewers to admin
    - Admins can change between admin, member, and viewer roles (except for existing admins/owners)
    - Admins cannot change existing admin or owner roles
    - Admins cannot promote to owner

    Authentication: JWT or Portal API token
    Required scope: members:write
    """
    workspace, caller_membership = get_workspace_with_access(
        slug, auth.user["id"], require_role="admin"
    )

    if not workspace.get("kanban_team_id"):
        raise HTTPException(
            status_code=400,
            detail="Workspace does not have a kanban team yet"
        )

    # Validate role
    valid_roles = ["owner", "admin", "member", "viewer"]
    if request.role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}"
        )

    # Check if user is a member
    membership = db_service.get_membership(workspace["kanban_team_id"], user_id)
    if not membership:
        raise HTTPException(
            status_code=404,
            detail="User is not a member of this workspace"
        )

    # Determine if caller is an owner
    caller_is_owner = caller_membership and caller_membership["role"] == "owner"

    # Role hierarchy for permission checks
    role_hierarchy = {"owner": 4, "admin": 3, "member": 2, "viewer": 1}
    target_current_level = role_hierarchy.get(membership["role"], 0)
    target_new_level = role_hierarchy.get(request.role, 0)
    caller_level = role_hierarchy.get(caller_membership["role"], 0)

    # Prevent owners from changing their own role
    if caller_is_owner and user_id == auth.user["id"] and membership["role"] == "owner":
        raise HTTPException(
            status_code=400,
            detail="Owners cannot change their own role"
        )

    # Only owners can change roles to/from owner
    if (request.role == "owner" or membership["role"] == "owner") and not caller_is_owner:
        raise HTTPException(
            status_code=403,
            detail="Only owners can change owner roles"
        )

    # Admins can promote to admin but not to owner, and cannot change existing admins/owners
    if not caller_is_owner:
        # Check if target is currently an admin or owner
        if target_current_level >= role_hierarchy["admin"]:
            raise HTTPException(
                status_code=403,
                detail="Only owners can change existing admin or owner roles"
            )
        # Check if trying to promote to owner
        if target_new_level >= role_hierarchy["owner"]:
            raise HTTPException(
                status_code=403,
                detail="Only owners can promote members to owner"
            )

    # Update role
    db_service.update_membership(
        workspace["kanban_team_id"],
        user_id,
        request.role
    )

    # Get updated user info
    user = db_service.get_user_by_id(user_id)

    logger.info(
        f"Updated member {user_id} role to {request.role} "
        f"in workspace {slug} by {auth.user['id']}"
    )

    return WorkspaceMemberResponse(
        user_id=user_id,
        email=user["email"] if user else "",
        name=user.get("display_name") or user.get("name") if user else None,
        role=request.role,
        joined_at=membership.get("joined_at")
    )


@router.delete("/{slug}/members/{user_id}")
async def remove_workspace_member(
    slug: str,
    user_id: str,
    auth: AuthContext = Depends(require_scope("members:write"))
):
    """
    Remove a member from the workspace.

    Access rules:
    - Owners can remove other owners, admins, members, and viewers
    - Owners cannot remove themselves
    - Admins can remove members and viewers

    Authentication: JWT or Portal API token
    Required scope: members:write
    """
    workspace, caller_membership = get_workspace_with_access(
        slug, auth.user["id"], require_role="admin"
    )

    if not workspace.get("kanban_team_id"):
        raise HTTPException(
            status_code=400,
            detail="Workspace does not have a kanban team yet"
        )

    # Check if user is a member
    membership = db_service.get_membership(workspace["kanban_team_id"], user_id)
    if not membership:
        raise HTTPException(
            status_code=404,
            detail="User is not a member of this workspace"
        )

    # Determine if caller is an owner
    caller_is_owner = caller_membership and caller_membership["role"] == "owner"

    # Owners cannot remove themselves (but can remove other owners)
    if caller_is_owner and user_id == auth.user["id"]:
        raise HTTPException(
            status_code=400,
            detail="Owners cannot remove themselves from the workspace"
        )

    # Only owners can remove other owners or admins
    if membership["role"] in ["owner", "admin"] and not caller_is_owner:
        raise HTTPException(
            status_code=403,
            detail="Only owners can remove admins and other owners"
        )

    # Remove from team
    db_service.remove_team_member(workspace["kanban_team_id"], user_id)

    logger.info(
        f"Removed member {user_id} from workspace {slug} by {auth.user['id']}"
    )

    return {"message": "Member removed successfully"}


# ============================================================================
# Workspace Invitation Endpoints
# ============================================================================


@router.get("/{slug}/invitations", response_model=WorkspaceInvitationsListResponse)
async def list_workspace_invitations(
    slug: str,
    status: Optional[str] = None,
    auth: AuthContext = Depends(require_scope("members:read"))
):
    """
    List invitations for a workspace.

    Access: Any workspace member can view invitations

    Authentication: JWT or Portal API token
    Required scope: members:read
    """
    workspace, _ = get_workspace_with_access(slug, auth.user["id"])

    invitations = db_service.get_workspace_invitations(
        workspace["id"], status=status
    )

    return WorkspaceInvitationsListResponse(
        invitations=[_invitation_to_response(i) for i in invitations],
        total=len(invitations)
    )


@router.delete("/{slug}/invitations/{invitation_id}")
async def cancel_workspace_invitation(
    slug: str,
    invitation_id: str,
    auth: AuthContext = Depends(require_scope("members:write"))
):
    """
    Cancel a pending workspace invitation.

    Access: Owner or admin only

    Authentication: JWT or Portal API token
    Required scope: members:write
    """
    workspace, _ = get_workspace_with_access(
        slug, auth.user["id"], require_role="admin"
    )

    # Get invitation
    invitation = db_service.get_workspace_invitation_by_id(invitation_id)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    # Verify invitation belongs to this workspace
    if invitation["workspace_id"] != workspace["id"]:
        raise HTTPException(status_code=404, detail="Invitation not found")

    # Can only cancel pending invitations
    if invitation["status"] != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel invitation with status '{invitation['status']}'"
        )

    db_service.cancel_workspace_invitation(invitation_id)

    logger.info(
        f"Cancelled invitation {invitation_id} for workspace {slug} "
        f"by {auth.user['id']}"
    )

    return {"message": "Invitation cancelled successfully"}


@router.post("/invitations/accept")
async def accept_workspace_invitation(
    token: str,
    auth: AuthContext = Depends(require_scope("workspaces:read"))
):
    """
    Accept a workspace invitation using the invitation token.

    This endpoint is called when a user clicks an invitation link.
    The user must be authenticated (signed in).

    Authentication: JWT only
    Required scope: workspaces:read
    """
    from datetime import datetime

    # Get invitation by token
    invitation = db_service.get_workspace_invitation_by_token(token)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid invitation token")

    # Check if invitation is still pending
    if invitation["status"] != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"This invitation has already been {invitation['status']}"
        )

    # Check if invitation has expired
    expires_at = datetime.fromisoformat(invitation["expires_at"])
    if datetime.utcnow() > expires_at:
        # Mark as expired
        db_service.cancel_workspace_invitation(invitation["id"])
        raise HTTPException(
            status_code=400,
            detail="This invitation has expired"
        )

    # Verify user email matches invitation (optional - can be removed for flexibility)
    user_email = auth.user.get("email", "").lower()
    if invitation["email"].lower() != user_email:
        raise HTTPException(
            status_code=403,
            detail=f"This invitation was sent to {invitation['email']}, but you are signed in as {user_email}"
        )

    # Get workspace
    workspace = db_service.get_workspace_by_id(invitation["workspace_id"])
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if not workspace.get("kanban_team_id"):
        raise HTTPException(
            status_code=400,
            detail="Workspace is not ready yet"
        )

    # Check if already a member
    existing = db_service.get_membership(workspace["kanban_team_id"], auth.user["id"])
    if existing:
        # Mark invitation as accepted anyway
        db_service.accept_workspace_invitation(invitation["id"], auth.user["id"])
        return {
            "message": "You are already a member of this workspace",
            "workspace_slug": workspace["slug"],
            "already_member": True
        }

    # Add user to portal's team membership
    db_service.add_team_member(
        workspace["kanban_team_id"],
        auth.user["id"],
        invitation["role"]
    )

    # Add user to kanban-team's members database
    await _add_member_to_kanban_team(
        workspace_slug=workspace["slug"],
        user_id=auth.user["id"],
        user_email=auth.user.get("email", ""),
        user_name=auth.user.get("display_name", ""),
        role=invitation["role"]
    )

    # Mark invitation as accepted
    db_service.accept_workspace_invitation(invitation["id"], auth.user["id"])

    logger.info(
        f"User {auth.user['id']} accepted invitation to workspace {workspace['slug']} "
        f"with role {invitation['role']}"
    )

    return {
        "message": "Invitation accepted successfully",
        "workspace_slug": workspace["slug"],
        "role": invitation["role"],
        "already_member": False
    }


@router.get("/invitations/info")
async def get_invitation_info(token: str):
    """
    Get information about an invitation without accepting it.

    This endpoint is public and used to show invitation details
    before the user signs in.

    Authentication: None required
    """
    from datetime import datetime

    # Get invitation by token
    invitation = db_service.get_workspace_invitation_by_token(token)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid invitation token")

    # Get workspace
    workspace = db_service.get_workspace_by_id(invitation["workspace_id"])
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check if expired
    expires_at = datetime.fromisoformat(invitation["expires_at"])
    is_expired = datetime.utcnow() > expires_at

    # Get inviter info
    inviter = db_service.get_user_by_id(invitation["invited_by"])
    inviter_name = inviter.get("display_name") or inviter.get("email") if inviter else "Unknown"

    return {
        "workspace_name": workspace["name"],
        "workspace_slug": workspace["slug"],
        "email": invitation["email"],
        "role": invitation["role"],
        "status": "expired" if is_expired else invitation["status"],
        "invited_by": inviter_name,
        "expires_at": invitation["expires_at"],
    }
