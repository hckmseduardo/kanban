"""Link preview service for fetching OpenGraph metadata"""

import httpx
from bs4 import BeautifulSoup
from typing import Optional
from pydantic import BaseModel
from urllib.parse import urlparse
import logging
import asyncio
from functools import lru_cache

logger = logging.getLogger(__name__)

# Cache for link previews (simple in-memory cache)
_preview_cache: dict[str, dict] = {}


class LinkPreview(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    site_name: Optional[str] = None
    favicon: Optional[str] = None


async def fetch_link_preview(url: str) -> Optional[LinkPreview]:
    """Fetch OpenGraph metadata from a URL"""

    # Check cache first
    if url in _preview_cache:
        return LinkPreview(**_preview_cache[url])

    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None

        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; KanbanBot/1.0; +https://kanban.io)"
            }
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                return None

            soup = BeautifulSoup(response.text, "html.parser")

            # Extract OpenGraph metadata
            preview_data = {
                "url": url,
                "title": None,
                "description": None,
                "image": None,
                "site_name": None,
                "favicon": None
            }

            # OpenGraph tags
            og_title = soup.find("meta", property="og:title")
            og_desc = soup.find("meta", property="og:description")
            og_image = soup.find("meta", property="og:image")
            og_site = soup.find("meta", property="og:site_name")

            # Twitter card fallbacks
            tw_title = soup.find("meta", attrs={"name": "twitter:title"})
            tw_desc = soup.find("meta", attrs={"name": "twitter:description"})
            tw_image = soup.find("meta", attrs={"name": "twitter:image"})

            # Standard meta fallbacks
            meta_desc = soup.find("meta", attrs={"name": "description"})
            title_tag = soup.find("title")

            # Priority: OpenGraph > Twitter > Standard
            preview_data["title"] = (
                og_title.get("content") if og_title else
                tw_title.get("content") if tw_title else
                title_tag.string if title_tag else None
            )

            preview_data["description"] = (
                og_desc.get("content") if og_desc else
                tw_desc.get("content") if tw_desc else
                meta_desc.get("content") if meta_desc else None
            )

            preview_data["image"] = (
                og_image.get("content") if og_image else
                tw_image.get("content") if tw_image else None
            )

            if preview_data["image"] and not preview_data["image"].startswith("http"):
                # Make relative URLs absolute
                preview_data["image"] = f"{parsed.scheme}://{parsed.netloc}{preview_data['image']}"

            preview_data["site_name"] = og_site.get("content") if og_site else parsed.netloc

            # Favicon
            favicon = soup.find("link", rel=lambda x: x and "icon" in x.lower() if isinstance(x, str) else False)
            if not favicon:
                favicon = soup.find("link", rel="icon")
            if not favicon:
                favicon = soup.find("link", rel="shortcut icon")

            if favicon and favicon.get("href"):
                favicon_url = favicon["href"]
                if not favicon_url.startswith("http"):
                    if favicon_url.startswith("//"):
                        favicon_url = f"{parsed.scheme}:{favicon_url}"
                    elif favicon_url.startswith("/"):
                        favicon_url = f"{parsed.scheme}://{parsed.netloc}{favicon_url}"
                    else:
                        favicon_url = f"{parsed.scheme}://{parsed.netloc}/{favicon_url}"
                preview_data["favicon"] = favicon_url
            else:
                # Default favicon location
                preview_data["favicon"] = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"

            # Cache the result
            _preview_cache[url] = preview_data

            return LinkPreview(**preview_data)

    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching preview for {url}")
        return None
    except httpx.HTTPStatusError as e:
        logger.warning(f"HTTP error fetching preview for {url}: {e.response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Error fetching preview for {url}: {e}")
        return None


def extract_urls(text: str) -> list[str]:
    """Extract URLs from text"""
    import re
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    return re.findall(url_pattern, text)


def clear_cache():
    """Clear the preview cache"""
    global _preview_cache
    _preview_cache = {}
