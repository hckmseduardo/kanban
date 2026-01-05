"""Sandbox models - Isolated development environments for workspace apps"""

from typing import Optional
from pydantic import BaseModel, field_validator
import re


class SandboxCreateRequest(BaseModel):
    """Request model for creating a new sandbox"""
    name: str
    slug: str
    description: Optional[str] = None
    source_branch: str = "main"  # Branch to create sandbox from

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        slug = v.lower().strip()
        if not re.match(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", slug):
            raise ValueError(
                "Slug must be 3-63 characters, lowercase alphanumeric and hyphens, "
                "start and end with alphanumeric"
            )
        return slug


class SandboxUpdateRequest(BaseModel):
    """Request model for updating a sandbox"""
    name: Optional[str] = None
    description: Optional[str] = None


class SandboxResponse(BaseModel):
    """Response model for sandbox"""
    id: str
    workspace_id: str
    slug: str
    full_slug: str  # {workspace_slug}-{sandbox_slug}
    name: str
    description: Optional[str] = None
    owner_id: str

    # Git branch
    git_branch: str  # sandbox/{full_slug}
    source_branch: str  # Branch it was created from

    # Subdomain
    subdomain: str  # {workspace}-{sandbox}.sandbox.amazing-ai.tools

    # Database
    database_name: str

    # Agent
    agent_container_name: str
    agent_webhook_url: str
    agent_webhook_secret: Optional[str] = None  # Only returned on create

    status: str
    created_at: str
    provisioned_at: Optional[str] = None


class SandboxListResponse(BaseModel):
    """Response model for listing sandboxes"""
    sandboxes: list[SandboxResponse]
    total: int


class SandboxStatusResponse(BaseModel):
    """Response model for sandbox provisioning status"""
    sandbox_id: str
    status: str
    progress: Optional[int] = None
    current_step: Optional[str] = None
    error: Optional[str] = None


class SandboxAgentRestartResponse(BaseModel):
    """Response model for agent restart"""
    sandbox_id: str
    agent_container_name: str
    new_webhook_secret: Optional[str] = None  # Only if regenerated
    message: str
