"""Team Proxy Service - Forwards API requests to team instances"""

import logging
from typing import Optional, Any
from urllib.parse import urljoin

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Timeout settings
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0


class TeamProxyService:
    """Service to proxy requests to team API instances"""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=CONNECT_TIMEOUT,
                    read=READ_TIMEOUT,
                    write=READ_TIMEOUT,
                    pool=READ_TIMEOUT
                ),
                verify=False  # Allow self-signed certs for internal calls
            )
        return self._client

    def _get_team_api_url(self, team_slug: str) -> str:
        """Get the internal API URL for a team"""
        # In production, use Docker internal networking
        # Format: http://kanban-team-{slug}-api-1:8000
        return f"http://kanban-team-{team_slug}-api-1:8000"

    async def request(
        self,
        team_slug: str,
        method: str,
        path: str,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        auth_token: Optional[str] = None
    ) -> tuple[int, Any]:
        """
        Make a request to a team's API.

        Args:
            team_slug: Team slug identifier
            method: HTTP method
            path: API path
            json: JSON body
            params: Query parameters
            headers: Additional headers
            auth_token: Authorization token to pass through

        Returns:
            Tuple of (status_code, response_data)
        """
        client = await self._get_client()
        base_url = self._get_team_api_url(team_slug)
        url = urljoin(base_url + "/", path.lstrip("/"))

        # Build headers, including auth if provided
        request_headers = headers.copy() if headers else {}
        if auth_token:
            request_headers["Authorization"] = f"Bearer {auth_token}"

        logger.debug(f"Proxying {method} {url}")

        try:
            response = await client.request(
                method=method,
                url=url,
                json=json,
                params=params,
                headers=request_headers
            )

            # Try to parse JSON response
            try:
                data = response.json()
            except Exception:
                data = response.text

            return response.status_code, data

        except httpx.ConnectError as e:
            logger.error(f"Failed to connect to team API {team_slug}: {e}")
            return 503, {"detail": f"Team API unavailable. The team may be suspended."}
        except httpx.TimeoutException as e:
            logger.error(f"Timeout connecting to team API {team_slug}: {e}")
            return 504, {"detail": "Team API timeout"}
        except Exception as e:
            logger.error(f"Error proxying to team API {team_slug}: {e}")
            return 500, {"detail": f"Error connecting to team API: {str(e)}"}

    async def get(
        self,
        team_slug: str,
        path: str,
        params: Optional[dict] = None,
        auth_token: Optional[str] = None
    ) -> tuple[int, Any]:
        """GET request to team API"""
        return await self.request(team_slug, "GET", path, params=params, auth_token=auth_token)

    async def post(
        self,
        team_slug: str,
        path: str,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
        auth_token: Optional[str] = None
    ) -> tuple[int, Any]:
        """POST request to team API"""
        return await self.request(team_slug, "POST", path, json=json, params=params, auth_token=auth_token)

    async def patch(
        self,
        team_slug: str,
        path: str,
        json: Optional[dict] = None,
        auth_token: Optional[str] = None
    ) -> tuple[int, Any]:
        """PATCH request to team API"""
        return await self.request(team_slug, "PATCH", path, json=json, auth_token=auth_token)

    async def put(
        self,
        team_slug: str,
        path: str,
        json: Optional[dict] = None,
        auth_token: Optional[str] = None
    ) -> tuple[int, Any]:
        """PUT request to team API"""
        return await self.request(team_slug, "PUT", path, json=json, auth_token=auth_token)

    async def delete(
        self,
        team_slug: str,
        path: str,
        auth_token: Optional[str] = None
    ) -> tuple[int, Any]:
        """DELETE request to team API"""
        return await self.request(team_slug, "DELETE", path, auth_token=auth_token)

    async def close(self):
        """Close the HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


# Singleton instance
team_proxy = TeamProxyService()
