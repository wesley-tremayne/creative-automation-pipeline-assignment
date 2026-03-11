"""
Application configuration.

Loads settings from environment variables with validation.
All secrets are accessed through this module — never read os.environ directly elsewhere.

Usage:
    from src.config import load_settings
    settings = load_settings()
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Immutable application settings loaded from environment."""

    # API Keys (never logged — use has_openai_key() to check presence)
    openai_api_key: str | None = None

    # Storage
    storage_backend: str = "local"  # "local" or "azure_blob"
    azure_storage_connection_string: str | None = None
    azure_storage_container: str = "creatives"

    # Paths
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    outputs_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "outputs")
    assets_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "assets")
    config_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "config")

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    def has_openai_key(self) -> bool:
        """Check if OpenAI API key is configured (without exposing the value)."""
        return bool(self.openai_api_key and self.openai_api_key != "sk-...your-key-here...")

    def has_azure_storage(self) -> bool:
        """Check if Azure storage is fully configured."""
        return self.storage_backend == "azure_blob" and bool(self.azure_storage_connection_string)


def load_settings() -> Settings:
    """Load settings from environment variables.

    Call once at startup. Pass the resulting Settings object through the
    application — do not re-read os.environ elsewhere.

    Raises:
        ValueError: If azure_blob storage is configured but connection string is missing.
    """
    backend = os.getenv("STORAGE_BACKEND", "local").lower()

    # Fail fast: azure_blob requires a connection string
    if backend == "azure_blob" and not os.getenv("AZURE_STORAGE_CONNECTION_STRING"):
        raise ValueError(
            "STORAGE_BACKEND=azure_blob requires AZURE_STORAGE_CONNECTION_STRING to be set. "
            "Add it to your .env file or environment."
        )

    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        storage_backend=backend,
        azure_storage_connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
        azure_storage_container=os.getenv("AZURE_STORAGE_CONTAINER", "creatives"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )
