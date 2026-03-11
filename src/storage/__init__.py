"""
Storage backend package for the Creative Automation Pipeline.

Provides a factory function that returns the configured storage backend.
The backend is selected via the STORAGE_BACKEND environment variable:
  - "local"      (default) — LocalStorageBackend, writes to outputs/
  - "azure_blob"           — AzureBlobStorageBackend, writes to Azure Blob Storage

Usage:
    from src.storage import get_storage_backend
    storage = get_storage_backend()
    storage.save_file(data, "campaign/product/1x1/image.png")
"""
from __future__ import annotations

import os
from pathlib import Path

from .base import StorageBackend
from .local_storage import LocalStorageBackend

OUTPUTS_ROOT = Path(__file__).parent.parent.parent / "outputs"

__all__ = ["StorageBackend", "LocalStorageBackend", "get_storage_backend"]


_REQUIRED_CONN_STR_KEYS = {"DefaultEndpointsProtocol", "AccountName", "AccountKey"}


def _validate_connection_string(conn_str: str) -> None:
    """Validate that an Azure Storage connection string contains the required keys.

    Args:
        conn_str: The connection string to validate.

    Raises:
        ValueError: If any required keys are missing or the string is malformed.
    """
    # Parse semicolon-delimited key=value pairs
    parsed: dict[str, str] = {}
    for part in conn_str.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key, _, value = part.partition("=")
            parsed[key.strip()] = value.strip()

    missing = _REQUIRED_CONN_STR_KEYS - parsed.keys()
    if missing:
        raise ValueError(
            f"AZURE_STORAGE_CONNECTION_STRING is missing required keys: {', '.join(sorted(missing))}. "
            "Expected format: DefaultEndpointsProtocol=https;AccountName=<name>;"
            "AccountKey=<key>;EndpointSuffix=core.windows.net"
        )


def get_storage_backend() -> StorageBackend:
    """Factory: return the configured storage backend.

    Reads STORAGE_BACKEND from the environment (default: "local").
    For azure_blob, also requires AZURE_STORAGE_CONNECTION_STRING.

    Returns:
        A configured StorageBackend instance.

    Raises:
        ValueError: If azure_blob is selected but connection string is missing or malformed.
        ImportError: If azure-storage-blob SDK is not installed.
    """
    backend = os.getenv("STORAGE_BACKEND", "local").lower()

    if backend == "azure_blob":
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            raise ValueError(
                "STORAGE_BACKEND=azure_blob requires AZURE_STORAGE_CONNECTION_STRING. "
                "Add it to your .env file."
            )
        _validate_connection_string(connection_string)
        from .azure_blob_storage import AzureBlobStorageBackend  # noqa: PLC0415

        return AzureBlobStorageBackend(
            connection_string=connection_string,
            container_name=os.getenv("AZURE_STORAGE_CONTAINER", "creatives"),
        )

    return LocalStorageBackend(base_dir=OUTPUTS_ROOT)
