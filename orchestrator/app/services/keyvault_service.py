"""Azure Key Vault service for fetching secrets.

This service fetches secrets from Azure Key Vault for use in team container deployment.
It uses the same credentials as the portal to ensure secret consistency.
"""

import logging
import os
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Configuration from environment
AZURE_KEY_VAULT_URL = os.getenv("AZURE_KEY_VAULT_URL", "")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")

# Fallback values for development
CROSS_DOMAIN_SECRET_DEFAULT = os.getenv("CROSS_DOMAIN_SECRET", "dev-cross-domain-secret")


class KeyVaultService:
    """Service for fetching secrets from Azure Key Vault."""

    # Map of Key Vault secret names to environment variable names
    SECRET_MAPPINGS = {
        "cross-domain-secret": "CROSS_DOMAIN_SECRET",
        "test-user-email": "TEST_USER_EMAIL",
        "test-user-password": "TEST_USER_PASSWORD",
        "github-pat": "GITHUB_TOKEN",
    }

    def __init__(self):
        self._client = None
        self._cache: Dict[str, str] = {}
        self._initialized = False

    def _get_client(self):
        """Lazy-load Key Vault client."""
        if self._client is not None:
            return self._client

        if not AZURE_KEY_VAULT_URL:
            logger.info("No Azure Key Vault URL configured. Using environment variables.")
            return None

        try:
            from azure.identity import ClientSecretCredential
            from azure.keyvault.secrets import SecretClient

            if AZURE_CLIENT_ID and AZURE_CLIENT_SECRET and AZURE_TENANT_ID:
                credential = ClientSecretCredential(
                    tenant_id=AZURE_TENANT_ID,
                    client_id=AZURE_CLIENT_ID,
                    client_secret=AZURE_CLIENT_SECRET
                )
                self._client = SecretClient(vault_url=AZURE_KEY_VAULT_URL, credential=credential)
                logger.info(f"Connected to Azure Key Vault: {AZURE_KEY_VAULT_URL}")
            else:
                logger.warning("Azure Key Vault credentials not fully configured.")
                return None

        except ImportError:
            logger.warning("Azure SDK not installed. Key Vault integration disabled.")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize Key Vault client: {e}")
            return None

        return self._client

    def get_secret(self, secret_name: str, use_cache: bool = True) -> Optional[str]:
        """Fetch a secret from Azure Key Vault with caching."""
        # Check cache first
        if use_cache and secret_name in self._cache:
            return self._cache[secret_name]

        client = self._get_client()
        if not client:
            # Fallback to environment variable
            env_var = self.SECRET_MAPPINGS.get(secret_name)
            if env_var:
                return os.getenv(env_var)
            return None

        try:
            secret = client.get_secret(secret_name)
            value = secret.value
            self._cache[secret_name] = value
            logger.debug(f"Loaded secret from Key Vault: {secret_name}")
            return value
        except Exception as e:
            logger.warning(f"Failed to fetch secret '{secret_name}': {e}")
            # Fallback to environment variable
            env_var = self.SECRET_MAPPINGS.get(secret_name)
            if env_var:
                return os.getenv(env_var)
            return None

    def get_cross_domain_secret(self) -> str:
        """Get the cross-domain secret for service-to-service auth.

        This is the primary secret used for authenticating with the portal API.
        Falls back to environment variable if Key Vault is not configured.
        """
        secret = self.get_secret("cross-domain-secret")
        if secret:
            return secret
        return CROSS_DOMAIN_SECRET_DEFAULT

    def get_github_token(self) -> Optional[str]:
        """Get the GitHub Personal Access Token from Key Vault.

        Falls back to GITHUB_TOKEN environment variable if Key Vault is not configured.
        """
        return self.get_secret("github-pat")

    def clear_cache(self):
        """Clear the secrets cache."""
        self._cache.clear()
        logger.info("Key Vault secrets cache cleared")


# Singleton instance
keyvault_service = KeyVaultService()
