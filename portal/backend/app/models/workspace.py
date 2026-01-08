"""Workspace models - Represents a kanban team with optional app"""

from typing import Optional
from pydantic import BaseModel, field_validator
import re


class WorkspaceCreateRequest(BaseModel):
    """Request model for creating a new workspace"""
    name: str
    slug: str
    description: Optional[str] = None
    app_template_slug: Optional[str] = None  # None = kanban-only
    github_org: str = "hckmseduardo"  # GitHub user/org where repos will be created

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        slug = v.lower().strip()
        if not re.match(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", slug):
            raise ValueError(
                "Slug must be 3-63 characters, lowercase alphanumeric and hyphens, "
                "start and end with alphanumeric"
            )
        # Reserved slugs
        reserved = ["app", "api", "www", "mail", "admin", "portal", "static", "assets", "sandbox"]
        if slug in reserved:
            raise ValueError(f"Slug '{slug}' is reserved")
        return slug


class WorkspaceUpdateRequest(BaseModel):
    """Request model for updating a workspace"""
    name: Optional[str] = None
    description: Optional[str] = None


class WorkspaceResponse(BaseModel):
    """Response model for workspace"""
    id: str
    slug: str
    name: str
    description: Optional[str] = None
    user_role: Optional[str] = None  # Current user's role: owner, admin, member, viewer

    # Kanban team (set during provisioning)
    kanban_team_id: Optional[str] = None
    kanban_subdomain: str

    # App (optional - null for kanban-only workspaces)
    app_template_id: Optional[str] = None
    app_template_slug: Optional[str] = None
    github_repo_url: Optional[str] = None
    github_repo_name: Optional[str] = None
    app_subdomain: Optional[str] = None
    app_database_name: Optional[str] = None

    # Azure AD (for app authentication - client_secret not exposed)
    azure_app_id: Optional[str] = None  # Application (client) ID
    azure_object_id: Optional[str] = None  # For Graph API operations

    status: str
    created_at: str
    provisioned_at: Optional[str] = None


class WorkspaceListResponse(BaseModel):
    """Response model for listing workspaces"""
    workspaces: list[WorkspaceResponse]
    total: int


class WorkspaceStatusResponse(BaseModel):
    """Response model for workspace provisioning status"""
    workspace_id: str
    status: str
    progress: Optional[int] = None
    current_step: Optional[str] = None
    error: Optional[str] = None


class SandboxHealthStatus(BaseModel):
    """Health status for a sandbox"""
    slug: str
    full_slug: str
    running: bool


class WorkspaceHealthResponse(BaseModel):
    """Response model for workspace container health"""
    workspace_id: str
    workspace_slug: str
    kanban_running: bool
    app_running: Optional[bool] = None  # None if no app
    sandboxes: list[SandboxHealthStatus] = []
    all_healthy: bool


class WorkspaceHealthBatchResponse(BaseModel):
    """Response model for batch workspace health check"""
    workspaces: dict[str, WorkspaceHealthResponse]
