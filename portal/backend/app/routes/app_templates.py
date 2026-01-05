"""App Template management routes"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.auth.unified import AuthContext, require_scope
from app.models.app_template import (
    AppTemplateCreateRequest,
    AppTemplateUpdateRequest,
    AppTemplateResponse,
    AppTemplateListResponse,
)
from app.services.database_service import db_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _template_to_response(template: dict) -> AppTemplateResponse:
    """Convert database template to response model"""
    return AppTemplateResponse(
        id=template["id"],
        slug=template["slug"],
        name=template["name"],
        description=template.get("description"),
        github_template_owner=template["github_template_owner"],
        github_template_repo=template["github_template_repo"],
        active=template.get("active", True),
        created_at=template["created_at"],
    )


@router.get("", response_model=AppTemplateListResponse)
async def list_app_templates(
    include_inactive: bool = False,
    auth: AuthContext = Depends(require_scope("templates:read"))
):
    """
    List available app templates.

    Authentication: JWT or Portal API token
    Required scope: templates:read

    By default, only active templates are returned.
    Set include_inactive=true to include inactive templates (admin only).
    """
    templates = db_service.list_app_templates(active_only=not include_inactive)

    return AppTemplateListResponse(
        templates=[_template_to_response(t) for t in templates],
        total=len(templates)
    )


@router.get("/{slug}", response_model=AppTemplateResponse)
async def get_app_template(
    slug: str,
    auth: AuthContext = Depends(require_scope("templates:read"))
):
    """
    Get app template details by slug.

    Authentication: JWT or Portal API token
    Required scope: templates:read
    """
    template = db_service.get_app_template_by_slug(slug)
    if not template:
        raise HTTPException(status_code=404, detail="App template not found")

    return _template_to_response(template)


@router.post("", response_model=AppTemplateResponse)
async def create_app_template(
    request: AppTemplateCreateRequest,
    auth: AuthContext = Depends(require_scope("templates:write"))
):
    """
    Create a new app template.

    Authentication: JWT or Portal API token
    Required scope: templates:write

    Note: This is an admin operation. The GitHub repository must be
    configured as a template repository.
    """
    # Check if slug already exists
    existing = db_service.get_app_template_by_slug(request.slug)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"App template with slug '{request.slug}' already exists"
        )

    template_data = {
        "slug": request.slug,
        "name": request.name,
        "description": request.description,
        "github_template_owner": request.github_template_owner,
        "github_template_repo": request.github_template_repo,
        "active": True,
    }

    template = db_service.create_app_template(template_data)
    logger.info(f"App template created: {template['slug']} by {auth.user["id"]}")

    return _template_to_response(template)


@router.put("/{slug}", response_model=AppTemplateResponse)
async def update_app_template(
    slug: str,
    request: AppTemplateUpdateRequest,
    auth: AuthContext = Depends(require_scope("templates:write"))
):
    """
    Update an app template.

    Authentication: JWT or Portal API token
    Required scope: templates:write
    """
    template = db_service.get_app_template_by_slug(slug)
    if not template:
        raise HTTPException(status_code=404, detail="App template not found")

    updates = {}
    if request.name is not None:
        updates["name"] = request.name
    if request.description is not None:
        updates["description"] = request.description
    if request.github_template_owner is not None:
        updates["github_template_owner"] = request.github_template_owner
    if request.github_template_repo is not None:
        updates["github_template_repo"] = request.github_template_repo
    if request.active is not None:
        updates["active"] = request.active

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    updated = db_service.update_app_template(template["id"], updates)
    logger.info(f"App template updated: {slug} by {auth.user["id"]}")

    return _template_to_response(updated)


@router.delete("/{slug}")
async def delete_app_template(
    slug: str,
    auth: AuthContext = Depends(require_scope("templates:write"))
):
    """
    Delete an app template.

    Authentication: JWT or Portal API token
    Required scope: templates:write

    Note: This is an admin operation. Consider deactivating instead of deleting.
    """
    template = db_service.get_app_template_by_slug(slug)
    if not template:
        raise HTTPException(status_code=404, detail="App template not found")

    # TODO: Check if any workspaces use this template before deleting

    db_service.delete_app_template(template["id"])
    logger.info(f"App template deleted: {slug} by {auth.user["id"]}")

    return {"message": f"App template '{slug}' deleted successfully"}
