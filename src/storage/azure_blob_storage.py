# pip install azure-storage-blob
"""
Azure Blob Storage backend.

Stores pipeline outputs as blobs in an Azure Storage container.
Blob names follow the pattern: {campaign_id}/{product}/{ratio}/{filename}

Requirements:
    pip install azure-storage-blob

Configuration (via environment or Settings):
    STORAGE_BACKEND=azure_blob
    AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;...
    AZURE_STORAGE_CONTAINER=creatives  # optional, defaults to "creatives"
"""
from __future__ import annotations

import logging

from .base import StorageBackend

logger = logging.getLogger(__name__)


class AzureBlobStorageBackend(StorageBackend):
    """Stores pipeline outputs in Azure Blob Storage.

    Args:
        connection_string: Azure Storage connection string. Never logged.
        container_name: Blob container name. Defaults to "creatives".
    """

    def __init__(self, connection_string: str, container_name: str = "creatives") -> None:
        try:
            from azure.storage.blob import BlobServiceClient  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "azure-storage-blob is required for Azure storage. "
                "Install it with: pip install azure-storage-blob"
            ) from exc

        # connection_string is intentionally not stored as a public attribute
        try:
            self._client = BlobServiceClient.from_connection_string(connection_string)
        except ValueError as exc:
            raise ValueError(
                f"Azure connection string is malformed. Expected format: "
                "DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;"
                f"EndpointSuffix=core.windows.net — detail: {exc}"
            ) from exc
        self._container = container_name
        try:
            self._ensure_container()
        except Exception as exc:
            raise RuntimeError(
                f"Connected to Azure but failed to access container '{container_name}': "
                f"{exc}. Check credentials and network."
            ) from exc
        logger.info("Azure Blob Storage backend initialised (container: %s)", container_name)

    def _ensure_container(self) -> None:
        """Create the container if it does not already exist."""
        try:
            container_client = self._client.get_container_client(self._container)
            container_client.get_container_properties()
        except Exception:
            self._client.create_container(self._container)
            logger.info("Created Azure Blob container: %s", self._container)

    def save_file(self, data: bytes, destination: str) -> str:
        """Upload bytes to a blob.

        Args:
            data: File contents as bytes.
            destination: Blob name (relative path used as the blob key).

        Returns:
            The blob URL.
        """
        blob_client = self._client.get_blob_client(
            container=self._container, blob=destination
        )
        blob_client.upload_blob(data, overwrite=True)
        url = blob_client.url
        logger.debug("Uploaded blob → %s", destination)
        return url

    def file_exists(self, path: str) -> bool:
        """Return True if a blob with the given name exists.

        Args:
            path: Blob name to check.
        """
        blob_client = self._client.get_blob_client(container=self._container, blob=path)
        try:
            blob_client.get_blob_properties()
            return True
        except Exception:
            return False

    def get_file(self, path: str) -> bytes:
        """Download and return blob contents.

        Args:
            path: Blob name to retrieve.

        Raises:
            FileNotFoundError: If the blob does not exist.
        """
        blob_client = self._client.get_blob_client(container=self._container, blob=path)
        try:
            return blob_client.download_blob().readall()
        except Exception as exc:
            raise FileNotFoundError(f"Blob not found: {path}") from exc

    def list_files(self, prefix: str) -> list[str]:
        """List blob names matching a prefix.

        Args:
            prefix: Blob name prefix to filter by.

        Returns:
            List of matching blob names.
        """
        container_client = self._client.get_container_client(self._container)
        return [b.name for b in container_client.list_blobs(name_starts_with=prefix)]

    def delete_file(self, path: str) -> None:
        """Delete a blob from the container.

        Args:
            path: Blob name to delete.

        Raises:
            FileNotFoundError: If the blob does not exist.
        """
        blob_client = self._client.get_blob_client(container=self._container, blob=path)
        try:
            blob_client.delete_blob()
            logger.debug("Deleted blob → %s", path)
        except Exception as exc:
            raise FileNotFoundError(f"Blob not found: {path}") from exc

    def get_url(self, path: str) -> str:
        """Return the HTTPS URL for a blob.

        Args:
            path: Blob name.
        """
        blob_client = self._client.get_blob_client(container=self._container, blob=path)
        return blob_client.url
