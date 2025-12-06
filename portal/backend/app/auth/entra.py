"""Microsoft Entra ID authentication service"""

import logging
from typing import Optional
from urllib.parse import urlencode

import httpx
from msal import ConfidentialClientApplication

from app.config import settings

logger = logging.getLogger(__name__)


class EntraAuthService:
    """Microsoft Entra ID authentication service"""

    # Microsoft Identity Platform endpoints
    AUTHORITY = "https://login.microsoftonline.com"

    # Scopes for authentication
    SCOPES = ["openid", "profile", "email"]

    def __init__(self):
        self.client_id = settings.entra_client_id
        self.client_secret = settings.entra_client_secret
        self.tenant_id = settings.entra_tenant_id or "common"
        self.redirect_uri = f"https://api.{settings.domain}:{settings.port}/auth/callback"

        self._msal_app: Optional[ConfidentialClientApplication] = None

    @property
    def msal_app(self) -> ConfidentialClientApplication:
        """Get MSAL application instance"""
        if self._msal_app is None and self.client_id and self.client_secret:
            self._msal_app = ConfidentialClientApplication(
                client_id=self.client_id,
                client_credential=self.client_secret,
                authority=f"{self.AUTHORITY}/{self.tenant_id}"
            )
        return self._msal_app

    def get_authorization_url(self, state: str = None) -> str:
        """Get URL to redirect user for authentication"""
        if not self.client_id:
            raise ValueError("Entra ID client ID not configured")

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.SCOPES),
            "response_mode": "query",
            "prompt": "select_account"  # Always show account picker
        }

        if state:
            params["state"] = state

        auth_url = f"{self.AUTHORITY}/{self.tenant_id}/oauth2/v2.0/authorize"
        return f"{auth_url}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str) -> dict:
        """Exchange authorization code for tokens"""
        if not self.client_id or not self.client_secret:
            raise ValueError("Entra ID credentials not configured")

        token_url = f"{self.AUTHORITY}/{self.tenant_id}/oauth2/v2.0/token"

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
            "scope": " ".join(self.SCOPES)
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)

            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.text}")
                raise ValueError(f"Token exchange failed: {response.status_code}")

            return response.json()

    async def get_user_info(self, access_token: str) -> dict:
        """Get user information from Microsoft Graph"""
        graph_url = "https://graph.microsoft.com/v1.0/me"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                graph_url,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                logger.error(f"Failed to get user info: {response.text}")
                raise ValueError("Failed to get user information")

            return response.json()

    def decode_id_token(self, id_token: str) -> dict:
        """Decode and validate ID token"""
        import base64
        import json

        # Split token into parts
        parts = id_token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid ID token format")

        # Decode payload (second part)
        payload = parts[1]
        # Add padding if needed
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding

        try:
            decoded = base64.urlsafe_b64decode(payload)
            return json.loads(decoded)
        except Exception as e:
            logger.error(f"Failed to decode ID token: {e}")
            raise ValueError("Failed to decode ID token")

    async def authenticate(self, code: str) -> dict:
        """
        Complete authentication flow:
        1. Exchange code for tokens
        2. Decode ID token to get user info
        3. Return user data
        """
        # Get tokens
        token_response = await self.exchange_code_for_token(code)

        # Decode ID token
        id_token = token_response.get("id_token")
        if not id_token:
            raise ValueError("No ID token in response")

        user_info = self.decode_id_token(id_token)

        # Get additional info from Graph API if needed
        access_token = token_response.get("access_token")
        if access_token:
            try:
                graph_info = await self.get_user_info(access_token)
                user_info["graph"] = graph_info
            except Exception as e:
                logger.warning(f"Failed to get Graph info: {e}")

        # Try multiple fields for email (personal vs work accounts differ)
        email = (
            user_info.get("preferred_username") or
            user_info.get("email") or
            user_info.get("upn") or
            user_info.get("unique_name") or
            (user_info.get("graph", {}).get("mail")) or
            (user_info.get("graph", {}).get("userPrincipalName")) or
            ""
        )

        logger.info(f"Entra auth: oid={user_info.get('oid')}, email={email}, name={user_info.get('name')}")

        return {
            "oid": user_info.get("oid"),
            "email": email,
            "name": user_info.get("name"),
            "idp": user_info.get("idp", "microsoft"),
            "access_token": access_token
        }


# Singleton instance
entra_auth = EntraAuthService()
