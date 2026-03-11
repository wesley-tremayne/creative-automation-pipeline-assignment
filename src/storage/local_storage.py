"""
Local filesystem storage backend.

Wraps standard file I/O under the StorageBackend interface.
This is the default backend — no additional dependencies required.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .base import StorageBackend

logger = logging.getLogger(__name__)

# Default output root, relative to the project root
_DEFAULT_OUTPUTS = Path(__file__).parent.parent.parent / "outputs"


class LocalStorageBackend(StorageBackend):
    """Stores pipeline outputs on the local filesystem.

    Args:
        base_dir: Root directory for all stored files. Defaults to outputs/.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = base_dir or _DEFAULT_OUTPUTS

    def save_file(self, data: bytes, destination: str) -> str:
        """Write bytes to a file under base_dir, creating parent dirs as needed.

        Args:
            data: File contents as bytes.
            destination: Relative path inside base_dir.

        Returns:
            Absolute path to the saved file.
        """
        full_path = self._base / destination
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(data)
        logger.debug("Saved file → %s", full_path)
        return str(full_path)

    def file_exists(self, path: str) -> bool:
        """Return True if the file exists under base_dir.

        Args:
            path: Relative path inside base_dir, or absolute path.
        """
        candidate = Path(path) if Path(path).is_absolute() else self._base / path
        return candidate.exists()

    def get_file(self, path: str) -> bytes:
        """Read and return file contents.

        Args:
            path: Relative path inside base_dir, or absolute path.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        candidate = Path(path) if Path(path).is_absolute() else self._base / path
        if not candidate.exists():
            raise FileNotFoundError(f"File not found: {candidate}")
        return candidate.read_bytes()

    def list_files(self, prefix: str) -> list[str]:
        """List all files whose path starts with prefix (relative to base_dir).

        Args:
            prefix: Path prefix to filter by (e.g. "campaign_id/").

        Returns:
            List of absolute path strings matching the prefix.
        """
        target = self._base / prefix
        if not target.exists():
            return []
        return [str(p) for p in target.rglob("*") if p.is_file()]

    def delete_file(self, path: str) -> None:
        """Delete a file under base_dir (or at the given absolute path).

        Args:
            path: Relative path inside base_dir, or absolute path.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        candidate = Path(path) if Path(path).is_absolute() else self._base / path
        if not candidate.exists():
            raise FileNotFoundError(f"File not found: {candidate}")
        candidate.unlink()
        logger.debug("Deleted file → %s", candidate)

    def get_url(self, path: str) -> str:
        """Return the absolute local path for the file.

        Args:
            path: Relative path inside base_dir, or absolute path.
        """
        if Path(path).is_absolute():
            return path
        return str(self._base / path)
