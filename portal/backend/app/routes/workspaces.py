"""Workspace management routes

Workspace members are inherited from the workspace's kanban team.
This means:
- Workspace owner = Team owner
- Workspace members = Team members
- Access to workspace requires team membership
"""

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
)
from app.services.database_service import db_service
from app.services.task_service import task_service
from app.services.email_service import send_workspace_invitation_email

logger = logging.getLogger(__name__)

router = APIRouter()


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
    workspace_data = {
        "slug": request.slug,
        "name": request.name,
        "description": request.description,
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
    )

    # Update status to deleting
    db_service.update_workspace(workspace["id"], {"status": "deleting"})

    logger.info(f"Workspace deletion started: {slug} by {auth.user['id']}")

    return {
        "message": "Workspace deletion started",
        "task_id": task_id
    }


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

    # Add user to team
    db_service.add_team_member(
        workspace["kanban_team_id"],
        auth.user["id"],
        invitation["role"]
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
