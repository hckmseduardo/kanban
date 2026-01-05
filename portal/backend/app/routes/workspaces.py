"""Workspace management routes"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.auth.unified import AuthContext, require_scope
from app.config import settings
from app.models.workspace import (
    WorkspaceCreateRequest,
    WorkspaceUpdateRequest,
    WorkspaceResponse,
    WorkspaceListResponse,
    WorkspaceStatusResponse,
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


def _workspace_to_response(workspace: dict) -> WorkspaceResponse:
    """Convert database workspace to response model"""
    # Get template slug if workspace has an app
    app_template_slug = None
    if workspace.get("app_template_id"):
        template = db_service.get_app_template_by_id(workspace["app_template_id"])
        if template:
            app_template_slug = template["slug"]

    return WorkspaceResponse(
        id=workspace["id"],
        slug=workspace["slug"],
        name=workspace["name"],
        description=workspace.get("description"),
        owner_id=workspace["owner_id"],
        kanban_team_id=workspace["kanban_team_id"],
        kanban_subdomain=get_kanban_subdomain(workspace["slug"]),
        app_template_id=workspace.get("app_template_id"),
        app_template_slug=app_template_slug,
        github_repo_url=workspace.get("github_repo_url"),
        github_repo_name=workspace.get("github_repo_name"),
        app_subdomain=get_app_subdomain(workspace["slug"]) if workspace.get("app_template_id") else None,
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

    Authentication: JWT or Portal API token
    Required scope: workspaces:read
    """
    workspaces = db_service.get_user_workspaces(auth.user["id"])

    return WorkspaceListResponse(
        workspaces=[_workspace_to_response(w) for w in workspaces],
        total=len(workspaces)
    )


@router.get("/{slug}", response_model=WorkspaceResponse)
async def get_workspace(
    slug: str,
    auth: AuthContext = Depends(require_scope("workspaces:read"))
):
    """
    Get workspace details by slug.

    Authentication: JWT or Portal API token
    Required scope: workspaces:read
    """
    workspace = db_service.get_workspace_by_slug(slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check access (owner or team member)
    if workspace["owner_id"] != auth.user["id"]:
        # TODO: Check team membership
        raise HTTPException(status_code=403, detail="Access denied")

    return _workspace_to_response(workspace)


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
    workspace_data = {
        "slug": request.slug,
        "name": request.name,
        "description": request.description,
        "owner_id": auth.user["id"],
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
        "workspace": _workspace_to_response(workspace),
        "task_id": task_id
    }


@router.get("/{slug}/status", response_model=WorkspaceStatusResponse)
async def get_workspace_status(
    slug: str,
    auth: AuthContext = Depends(require_scope("workspaces:read"))
):
    """
    Get workspace provisioning status.

    Authentication: JWT or Portal API token
    Required scope: workspaces:read
    """
    workspace = db_service.get_workspace_by_slug(slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check access
    if workspace["owner_id"] != auth.user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get latest task for this workspace
    tasks = await task_service.get_user_tasks(auth.user["id"], limit=50)
    workspace_task = None
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

    Authentication: JWT or Portal API token
    Required scope: workspaces:write
    """
    workspace = db_service.get_workspace_by_slug(slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check access (owner only for updates)
    if workspace["owner_id"] != auth.user["id"]:
        raise HTTPException(status_code=403, detail="Only workspace owner can update")

    updates = {}
    if request.name is not None:
        updates["name"] = request.name
    if request.description is not None:
        updates["description"] = request.description

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    updated = db_service.update_workspace(workspace["id"], updates)
    logger.info(f"Workspace updated: {slug} by {auth.user['id']}")

    return _workspace_to_response(updated)


@router.delete("/{slug}")
async def delete_workspace(
    slug: str,
    auth: AuthContext = Depends(require_scope("workspaces:write"))
):
    """
    Delete a workspace.

    This starts an async deletion process that will:
    1. Delete all sandboxes
    2. Delete the app (if present)
    3. Delete the kanban team
    4. Delete the GitHub repo (optional)
    5. Remove all data

    Authentication: JWT or Portal API token
    Required scope: workspaces:write
    """
    workspace = db_service.get_workspace_by_slug(slug)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check access (owner only for deletion)
    if workspace["owner_id"] != auth.user["id"]:
        raise HTTPException(status_code=403, detail="Only workspace owner can delete")

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
    )

    # Update status to deleting
    db_service.update_workspace(workspace["id"], {"status": "deleting"})

    logger.info(f"Workspace deletion started: {slug} by {auth.user['id']}")

    return {
        "message": "Workspace deletion started",
        "task_id": task_id
    }
