"""Application configuration with Azure Key Vault integration"""

import logging
from functools import lru_cache
from typing import Optional, Dict, Any

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# Global cache for Key Vault secrets (singleton client)
_keyvault_client = None
_secrets_cache: Dict[str, str] = {}


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Application
    app_name: str = "Kanban Portal API"
    debug: bool = False
    domain: str = "localhost"
    port: int = 4443
    cert_mode: str = "development"  # "development" or "production"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Security
    portal_secret_key: str = "dev-secret-change-me"
    cross_domain_secret: str = "dev-cross-domain-secret"
    access_token_expire_minutes: int = 60 * 24  # 24 hours

    # Azure Key Vault
    azure_key_vault_url: Optional[str] = None
    azure_client_id: Optional[str] = None
    azure_client_secret: Optional[str] = None
    azure_tenant_id: Optional[str] = None

    # Entra ID (Authentication)
    entra_client_id: Optional[str] = None
    entra_client_secret: Optional[str] = None
    entra_tenant_id: Optional[str] = None
    entra_authority: Optional[str] = None  # Custom authority URL for Entra External ID (CIAM)
    entra_scopes: str = "openid profile email"  # Scopes for Entra External ID

    # Database
    database_path: str = "/app/data/portal.json"

    # Certificate settings
    certbot_email: str = "admin@localhost"
    letsencrypt_staging: bool = False  # Use staging server for testing

    # Test credentials (loaded from Key Vault for integration testing)
    test_user_email: Optional[str] = None
    test_user_password: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


class KeyVaultService:
    """Azure Key Vault service with connection pooling and caching"""

    # Map of Key Vault secret names to settings attributes
    SECRET_MAPPINGS = {
        "portal-secret-key": "portal_secret_key",
        "cross-domain-secret": "cross_domain_secret",
        "entra-client-id": "entra_client_id",
        "entra-client-secret": "entra_client_secret",
        "entra-tenant-id": "entra_tenant_id",
        "entra-authority": "entra_authority",
        "entra-scopes": "entra_scopes",
        "redis-url": "redis_url",
        "certbot-email": "certbot_email",
        # Test credentials for integration testing
        "test-user-email": "test_user_email",
        "test-user-password": "test_user_password",
    }

    def __init__(self, vault_url: str):
        self.vault_url = vault_url
        self._client = None
        self._cache: Dict[str, str] = {}

    @property
    def client(self):
        """Lazy-load Key Vault client (singleton pattern)"""
        if self._client is None:
            try:
                from azure.identity import DefaultAzureCredential, ClientSecretCredential
                from azure.keyvault.secrets import SecretClient
                import os

                # Use ClientSecretCredential if all credentials are provided
                client_id = os.environ.get("AZURE_CLIENT_ID")
                client_secret = os.environ.get("AZURE_CLIENT_SECRET")
                tenant_id = os.environ.get("AZURE_TENANT_ID")

                if client_id and client_secret and tenant_id:
                    credential = ClientSecretCredential(
                        tenant_id=tenant_id,
                        client_id=client_id,
                        client_secret=client_secret
                    )
                    logger.info("Using ClientSecretCredential for Key Vault")
                else:
                    credential = DefaultAzureCredential()
                    logger.info("Using DefaultAzureCredential for Key Vault")

                self._client = SecretClient(vault_url=self.vault_url, credential=credential)
            except ImportError:
                logger.warning("Azure SDK not installed. Key Vault integration disabled.")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize Key Vault client: {e}")
                raise

        return self._client

    def get_secret(self, secret_name: str, use_cache: bool = True) -> Optional[str]:
        """Fetch a secret from Azure Key Vault with caching"""
        # Check cache first
        if use_cache and secret_name in self._cache:
            return self._cache[secret_name]

        try:
            secret = self.client.get_secret(secret_name)
            value = secret.value
            self._cache[secret_name] = value
            return value
        except Exception as e:
            logger.warning(f"Failed to fetch secret '{secret_name}': {e}")
            return None

    def get_secrets_batch(self, secret_names: list) -> Dict[str, Optional[str]]:
        """Fetch multiple secrets efficiently"""
        results = {}
        for name in secret_names:
            results[name] = self.get_secret(name)
        return results

    def clear_cache(self):
        """Clear the secrets cache (useful for rotation)"""
        self._cache.clear()
        logger.info("Key Vault secrets cache cleared")


def get_keyvault_service(vault_url: str) -> Optional[KeyVaultService]:
    """Get or create Key Vault service instance"""
    global _keyvault_client

    if _keyvault_client is None and vault_url:
        try:
            _keyvault_client = KeyVaultService(vault_url)
        except Exception as e:
            logger.error(f"Failed to create Key Vault service: {e}")
            return None

    return _keyvault_client


def load_keyvault_secrets(settings: Settings) -> Settings:
    """Load secrets from Azure Key Vault if configured"""
    if not settings.azure_key_vault_url:
        logger.info("No Azure Key Vault URL configured. Using environment variables.")
        return settings

    logger.info(f"Loading secrets from Key Vault: {settings.azure_key_vault_url}")

    kv_service = get_keyvault_service(settings.azure_key_vault_url)
    if not kv_service:
        logger.warning("Key Vault service unavailable. Using environment variables.")
        return settings

    # Fetch all secrets in batch
    secrets = kv_service.get_secrets_batch(list(KeyVaultService.SECRET_MAPPINGS.keys()))

    loaded_count = 0
    for secret_name, attr_name in KeyVaultService.SECRET_MAPPINGS.items():
        value = secrets.get(secret_name)
        if value:
            setattr(settings, attr_name, value)
            loaded_count += 1
            logger.debug(f"Loaded secret: {secret_name}")

    logger.info(f"Loaded {loaded_count}/{len(KeyVaultService.SECRET_MAPPINGS)} secrets from Key Vault")
    return settings


def validate_production_settings(settings: Settings) -> list:
    """Validate that all required settings are configured for production"""
    errors = []

    if settings.portal_secret_key == "dev-secret-change-me":
        errors.append("PORTAL_SECRET_KEY must be changed from default value")

    if settings.cross_domain_secret == "dev-cross-domain-secret":
        errors.append("CROSS_DOMAIN_SECRET must be changed from default value")

    if not settings.entra_client_id:
        errors.append("ENTRA_CLIENT_ID is required for authentication")

    if not settings.entra_client_secret:
        errors.append("ENTRA_CLIENT_SECRET is required for authentication")

    if settings.certbot_email == "admin@localhost":
        errors.append("CERTBOT_EMAIL should be set to a valid email for Let's Encrypt")

    return errors


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance with Key Vault secrets loaded"""
    base_settings = Settings()

    # Load from Key Vault in production mode
    if base_settings.cert_mode == "production":
        base_settings = load_keyvault_secrets(base_settings)

        # Validate production settings
        errors = validate_production_settings(base_settings)
        if errors:
            for error in errors:
                logger.warning(f"Production config warning: {error}")

    return base_settings


# Convenience access
settings = get_settings()
