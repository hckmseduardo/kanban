"""Azure service for Microsoft Entra External ID (CIAM) app registration management.

This service handles Entra External ID app registration operations for workspace provisioning,
including creating app registrations, configuring redirect URIs, and generating secrets.

Entra External ID (CIAM) uses a different authority URL pattern than standard Azure AD:
- Standard Azure AD: https://login.microsoftonline.com/{tenant-id}
- Entra External ID: https://{domain}.ciamlogin.com/{tenant-id}
"""

import logging
import os
import secrets
from typing import Optional
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)

# Configuration from environment
# Uses AZURE_APP_FACTORY_* vars for the service principal that creates app registrations
# in the CIAM tenant
AZURE_TENANT_ID = os.getenv("AZURE_APP_FACTORY_TENANT_ID", os.getenv("AZURE_TENANT_ID", ""))
AZURE_CLIENT_ID = os.getenv("AZURE_APP_FACTORY_CLIENT_ID", os.getenv("AZURE_CLIENT_ID", ""))
AZURE_CLIENT_SECRET = os.getenv("AZURE_APP_FACTORY_CLIENT_SECRET", os.getenv("AZURE_CLIENT_SECRET", ""))

# CIAM-specific configuration
ENTRA_CIAM_AUTHORITY = os.getenv("ENTRA_CIAM_AUTHORITY", "")


@dataclass
class AppRegistrationResult:
    """Result of creating an Entra External ID app registration."""
    app_id: str  # Application (client) ID
    object_id: str  # Object ID for Graph API operations
    client_secret: str  # Generated client secret
    tenant_id: str  # Tenant ID
    authority: str  # CIAM authority URL (e.g., https://domain.ciamlogin.com/tenant-id)


class AzureService:
    """Service for Entra External ID (CIAM) app registration operations."""

    GRAPH_URL = "https://graph.microsoft.com/v1.0"
    LOGIN_URL = "https://login.microsoftonline.com"

    def __init__(
        self,
        tenant_id: str = None,
        client_id: str = None,
        client_secret: str = None,
        ciam_authority: str = None,
    ):
        self._tenant_id = tenant_id or AZURE_TENANT_ID
        self._client_id = client_id or AZURE_CLIENT_ID
        self._client_secret = client_secret or AZURE_CLIENT_SECRET
        self._ciam_authority = ciam_authority or ENTRA_CIAM_AUTHORITY
        self._access_token: Optional[str] = None

    @property
    def tenant_id(self) -> str:
        if not self._tenant_id:
            raise ValueError("Azure tenant ID not configured. Set AZURE_APP_FACTORY_TENANT_ID.")
        return self._tenant_id

    @property
    def ciam_authority(self) -> str:
        """Get the CIAM authority URL for the tenant."""
        if self._ciam_authority:
            return self._ciam_authority
        # Fallback to standard Azure AD authority if CIAM not configured
        return f"{self.LOGIN_URL}/{self.tenant_id}"

    async def _get_access_token(self) -> str:
        """Get access token for Microsoft Graph API using client credentials flow."""
        if self._access_token:
            return self._access_token

        if not self._client_id or not self._client_secret:
            raise ValueError(
                "Azure App Factory credentials not configured. "
                "Set AZURE_APP_FACTORY_CLIENT_ID and AZURE_APP_FACTORY_CLIENT_SECRET."
            )

        url = f"{self.LOGIN_URL}/{self.tenant_id}/oauth2/v2.0/token"

        data = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, timeout=30.0)

            if response.status_code == 200:
                token_data = response.json()
                self._access_token = token_data["access_token"]
                return self._access_token
            else:
                error = response.json().get("error_description", response.text)
                logger.error(f"Failed to get Azure access token: {error}")
                raise Exception(f"Failed to authenticate with Azure: {error}")

    async def _graph_request(
        self,
        method: str,
        endpoint: str,
        json_data: dict = None,
    ) -> dict:
        """Make a request to Microsoft Graph API."""
        token = await self._get_access_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        url = f"{self.GRAPH_URL}{endpoint}"

        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(url, headers=headers, timeout=30.0)
            elif method == "POST":
                response = await client.post(
                    url, headers=headers, json=json_data, timeout=30.0
                )
            elif method == "PATCH":
                response = await client.patch(
                    url, headers=headers, json=json_data, timeout=30.0
                )
            elif method == "DELETE":
                response = await client.delete(url, headers=headers, timeout=30.0)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            return {
                "status_code": response.status_code,
                "data": response.json() if response.content else None,
            }

    async def create_app_registration(
        self,
        display_name: str,
        redirect_uris: list[str],
        homepage_url: str = None,
    ) -> AppRegistrationResult:
        """Create a new Entra External ID (CIAM) app registration.

        Args:
            display_name: Display name for the app registration
            redirect_uris: List of redirect URIs for OAuth callbacks
            homepage_url: Optional homepage URL

        Returns:
            AppRegistrationResult with app credentials including CIAM authority URL
        """
        # Create the app registration
        # For Entra External ID (CIAM), use AzureADMyOrg since CIAM has its own user directory
        app_data = {
            "displayName": display_name,
            "signInAudience": "AzureADMyOrg",  # Single tenant - CIAM tenant only
            "web": {
                "redirectUris": redirect_uris,
                "implicitGrantSettings": {
                    "enableIdTokenIssuance": True,
                    "enableAccessTokenIssuance": False,
                },
            },
            "requiredResourceAccess": [
                {
                    # Microsoft Graph
                    "resourceAppId": "00000003-0000-0000-c000-000000000000",
                    "resourceAccess": [
                        {
                            # openid
                            "id": "37f7f235-527c-4136-accd-4a02d197296e",
                            "type": "Scope",
                        },
                        {
                            # profile
                            "id": "14dad69e-099b-42c9-810b-d002981feec1",
                            "type": "Scope",
                        },
                        {
                            # email
                            "id": "64a6cdd6-aab1-4aaf-94b8-3cc8405e90d0",
                            "type": "Scope",
                        },
                        {
                            # User.Read
                            "id": "e1fe6dd8-ba31-4d61-89e7-88639da4683d",
                            "type": "Scope",
                        },
                    ],
                }
            ],
        }

        if homepage_url:
            app_data["web"]["homePageUrl"] = homepage_url

        result = await self._graph_request("POST", "/applications", app_data)

        if result["status_code"] != 201:
            error = result["data"].get("error", {}).get("message", "Unknown error")
            logger.error(f"Failed to create app registration: {error}")
            raise Exception(f"Failed to create Azure app registration: {error}")

        app = result["data"]
        app_id = app["appId"]
        object_id = app["id"]

        logger.info(f"Created Azure app registration: {display_name} ({app_id}), object_id: {object_id}")

        # Wait for app to propagate in Azure AD
        import asyncio
        await asyncio.sleep(2)

        # Create a service principal for the app
        sp_result = await self._graph_request(
            "POST",
            "/servicePrincipals",
            {"appId": app_id},
        )

        if sp_result["status_code"] != 201:
            logger.warning(
                f"Failed to create service principal: {sp_result['data']}"
            )

        # Add a client secret with retry logic
        secret_result = None
        for attempt in range(3):
            secret_result = await self._graph_request(
                "POST",
                f"/applications/{object_id}/addPassword",
                {
                    "passwordCredential": {
                        "displayName": "App Factory Generated Secret",
                        "endDateTime": "2099-12-31T23:59:59Z",
                    }
                },
            )
            if secret_result["status_code"] == 200:
                break
            logger.warning(f"addPassword attempt {attempt + 1} failed, retrying...")
            await asyncio.sleep(2)

        if secret_result["status_code"] != 200:
            error = secret_result["data"].get("error", {}).get("message", "Unknown")
            logger.error(f"Failed to create client secret: {error}")
            raise Exception(f"Failed to create Azure client secret: {error}")

        client_secret = secret_result["data"]["secretText"]

        logger.info(f"Created client secret for app: {app_id}")

        return AppRegistrationResult(
            app_id=app_id,
            object_id=object_id,
            client_secret=client_secret,
            tenant_id=self.tenant_id,
            authority=self.ciam_authority,
        )

    async def get_app_registration(self, object_id: str) -> Optional[dict]:
        """Get app registration by object ID."""
        result = await self._graph_request("GET", f"/applications/{object_id}")

        if result["status_code"] == 200:
            return result["data"]
        elif result["status_code"] == 404:
            return None
        else:
            error = result["data"].get("error", {}).get("message", "Unknown")
            raise Exception(f"Failed to get Azure app registration: {error}")

    async def update_redirect_uris(
        self,
        object_id: str,
        redirect_uris: list[str],
    ) -> bool:
        """Update redirect URIs for an app registration."""
        result = await self._graph_request(
            "PATCH",
            f"/applications/{object_id}",
            {
                "web": {
                    "redirectUris": redirect_uris,
                }
            },
        )

        if result["status_code"] == 204:
            logger.info(f"Updated redirect URIs for app: {object_id}")
            return True
        else:
            error = result["data"].get("error", {}).get("message", "Unknown")
            logger.error(f"Failed to update redirect URIs: {error}")
            return False

    async def delete_app_registration(self, object_id: str) -> bool:
        """Delete an Azure AD app registration."""
        result = await self._graph_request("DELETE", f"/applications/{object_id}")

        if result["status_code"] == 204:
            logger.info(f"Deleted Azure app registration: {object_id}")
            return True
        elif result["status_code"] == 404:
            logger.warning(f"App registration not found for deletion: {object_id}")
            return False
        else:
            error = result["data"].get("error", {}).get("message", "Unknown")
            logger.error(f"Failed to delete app registration: {error}")
            return False


# Singleton instance
azure_service = AzureService()
