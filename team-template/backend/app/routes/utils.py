"""Utility routes including link preview"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, HttpUrl
from typing import Optional

from ..services.link_preview import fetch_link_preview, extract_urls, LinkPreview

router = APIRouter()


class LinkPreviewRequest(BaseModel):
    url: str


class LinkPreviewResponse(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    site_name: Optional[str] = None
    favicon: Optional[str] = None


@router.get("/link-preview", response_model=LinkPreviewResponse)
async def get_link_preview(url: str = Query(..., description="URL to fetch preview for")):
    """Fetch OpenGraph metadata for a URL"""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL: must start with http:// or https://")

    preview = await fetch_link_preview(url)

    if not preview:
        raise HTTPException(status_code=404, detail="Could not fetch preview for URL")

    return preview


@router.post("/extract-urls")
async def extract_urls_from_text(text: str = Query(..., description="Text to extract URLs from")):
    """Extract all URLs from a text string"""
    urls = extract_urls(text)
    return {"urls": urls}
