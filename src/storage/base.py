"""
Abstract storage backend interface.

All storage implementations must inherit from `StorageBackend` and implement
every abstract method. This ensures the pipeline can switch between local
filesystem and cloud storage (e.g. Azure Blob) via configuration only.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Abstract storage backend for pipeline outputs."""

    @abstractmethod
    def save_file(self, data: bytes, destination: str) -> str:
        """Save raw bytes to the given destination path.

        Args:
            data: File contents as bytes.
            destination: Relative path / blob name for the file.

        Returns:
            The final path or URL where the file can be accessed.
        """
        ...

    @abstractmethod
    def file_exists(self, path: str) -> bool:
        """Return True if a file exists at the given path/blob name.

        Args:
            path: Relative path or blob name to check.
        """
        ...

    @abstractmethod
    def get_file(self, path: str) -> bytes:
        """Retrieve file contents as bytes.

        Args:
            path: Relative path or blob name to read.

        Returns:
            File contents as bytes.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        ...

    @abstractmethod
    def list_files(self, prefix: str) -> list[str]:
        """List all file paths/blob names matching a prefix.

        Args:
            prefix: Path prefix to filter by (e.g. "campaign_id/product/").

        Returns:
            List of matching paths or blob names.
        """
        ...

    @abstractmethod
    def delete_file(self, path: str) -> None:
        """Delete a file at the given path/blob name.

        Args:
            path: Relative path or blob name to delete.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        ...

    @abstractmethod
    def get_url(self, path: str) -> str:
        """Return a URL or local path that can be used to access the file.

        Args:
            path: Relative path or blob name.

        Returns:
            A full local path string (local backend) or HTTPS blob URL (Azure).
        """
        ...
