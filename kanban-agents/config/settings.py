"""
Configuration Settings

Centralized configuration management using Pydantic settings.
"""

from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Kanban API
    kanban_url: str = Field(
        default="http://localhost:8000",
        description="Base URL of the Kanban API"
    )

    # Repository
    repo_path: str = Field(
        default="/path/to/repo",
        description="Path to the code repository agents will work on"
    )

    # Anthropic
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API key for Claude"
    )

    # Agent configuration
    agent_label: str = Field(
        default="agent",
        description="Label that marks cards for agent processing"
    )
    board_id: str = Field(
        default="",
        description="Default board ID to monitor"
    )
    poll_interval: int = Field(
        default=30,
        description="Seconds between polling cycles"
    )
    cooldown_minutes: int = Field(
        default=5,
        description="Minutes before reprocessing same card"
    )

    # Webhook server
    webhook_secret: str = Field(
        default="",
        description="Secret for validating webhook signatures"
    )
    webhook_port: int = Field(
        default=8080,
        description="Port for webhook server"
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()
