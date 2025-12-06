"""Application configuration"""

import os
import logging
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Application
    app_name: str = "Kanban Portal API"
    debug: bool = False
    domain: str = "localhost"
    port: int = 4443
    cert_mode: str = "development"

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

    # Database
    database_path: str = "/app/data/portal.json"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


def get_keyvault_secret(vault_url: str, secret_name: str) -> Optional[str]:
    """Fetch a secret from Azure Key Vault"""
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)
        secret = client.get_secret(secret_name)
        return secret.value
    except ImportError:
        logger.warning("Azure SDK not installed. Skipping Key Vault integration.")
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch secret '{secret_name}' from Key Vault: {e}")
        return None


def load_keyvault_secrets(settings: Settings) -> Settings:
    """Load secrets from Azure Key Vault if configured"""
    if not settings.azure_key_vault_url:
        logger.info("No Azure Key Vault URL configured. Using environment variables.")
        return settings

    logger.info(f"Loading secrets from Key Vault: {settings.azure_key_vault_url}")

    # Map of Key Vault secret names to settings attributes
    secret_mappings = {
        "portal-secret-key": "portal_secret_key",
        "cross-domain-secret": "cross_domain_secret",
        "entra-client-id": "entra_client_id",
        "entra-client-secret": "entra_client_secret",
        "entra-tenant-id": "entra_tenant_id",
        "redis-url": "redis_url",
    }

    for secret_name, attr_name in secret_mappings.items():
        value = get_keyvault_secret(settings.azure_key_vault_url, secret_name)
        if value:
            setattr(settings, attr_name, value)
            logger.info(f"Loaded secret: {secret_name}")

    return settings


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance with Key Vault secrets loaded"""
    base_settings = Settings()

    # Only load from Key Vault in production mode
    if base_settings.cert_mode == "production":
        return load_keyvault_secrets(base_settings)

    return base_settings


# Convenience access
settings = get_settings()
