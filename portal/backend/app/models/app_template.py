"""App Template models - Registry of available application templates"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator
import re


class AppTemplateCreateRequest(BaseModel):
    """Request model for creating a new app template"""
    slug: str
    name: str
    description: Optional[str] = None
    github_template_owner: str
    github_template_repo: str

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


class AppTemplateUpdateRequest(BaseModel):
    """Request model for updating an app template"""
    name: Optional[str] = None
    description: Optional[str] = None
    github_template_owner: Optional[str] = None
    github_template_repo: Optional[str] = None
    active: Optional[bool] = None


class AppTemplateResponse(BaseModel):
    """Response model for app template"""
    id: str
    slug: str
    name: str
    description: Optional[str] = None
    github_template_owner: str
    github_template_repo: str
    active: bool
    created_at: str


class AppTemplateListResponse(BaseModel):
    """Response model for listing app templates"""
    templates: list[AppTemplateResponse]
    total: int
