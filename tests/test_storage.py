"""Tests for the storage backend module (src/storage/)."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.storage import _validate_connection_string, get_storage_backend
from src.storage.base import StorageBackend
from src.storage.local_storage import LocalStorageBackend


_VALID_CONN_STR = (
    "DefaultEndpointsProtocol=https;AccountName=myaccount;"
    "AccountKey=mybase64key==;EndpointSuffix=core.windows.net"
)


class TestValidateConnectionString:
    """Unit tests for _validate_connection_string()."""

    def test_valid_string_no_error(self):
        """A well-formed connection string with all required keys passes validation."""
        # Should not raise
        _validate_connection_string(_VALID_CONN_STR)

    def test_empty_string_raises_listing_all_missing_keys(self):
        """An empty string raises ValueError listing all three required keys."""
        with pytest.raises(ValueError) as exc_info:
            _validate_connection_string("")
        msg = str(exc_info.value)
        assert "AccountKey" in msg
        assert "AccountName" in msg
        assert "DefaultEndpointsProtocol" in msg

    def test_partial_string_missing_account_key_raises(self):
        """A string missing AccountKey raises ValueError mentioning that key."""
        partial = "DefaultEndpointsProtocol=https;AccountName=myaccount"
        with pytest.raises(ValueError) as exc_info:
            _validate_connection_string(partial)
        assert "AccountKey" in str(exc_info.value)

    def test_partial_string_missing_account_name_raises(self):
        """A string missing AccountName raises ValueError mentioning that key."""
        partial = "DefaultEndpointsProtocol=https;AccountKey=mykey"
        with pytest.raises(ValueError) as exc_info:
            _validate_connection_string(partial)
        assert "AccountName" in str(exc_info.value)

    def test_gibberish_string_raises(self):
        """A completely malformed string (no key=value pairs) raises ValueError."""
        with pytest.raises(ValueError, match="AZURE_STORAGE_CONNECTION_STRING"):
            _validate_connection_string("invalid_nonsense")

    def test_error_message_includes_expected_format(self):
        """ValueError message includes the expected connection string format hint."""
        with pytest.raises(ValueError) as exc_info:
            _validate_connection_string("")
        assert "DefaultEndpointsProtocol=https" in str(exc_info.value)


class TestGetStorageBackendAzureValidation:
    """Tests for get_storage_backend() with azure_blob backend validation."""

    def test_azure_blob_with_malformed_connection_string_raises_clear_error(self):
        """get_storage_backend() with a malformed connection string raises a clear ValueError."""
        env = {
            "STORAGE_BACKEND": "azure_blob",
            "AZURE_STORAGE_CONNECTION_STRING": "invalid_string",
        }
        with patch.dict(os.environ, env):
            with pytest.raises(ValueError, match="AZURE_STORAGE_CONNECTION_STRING"):
                get_storage_backend()

    def test_azure_blob_with_partial_connection_string_raises(self):
        """get_storage_backend() with a partial connection string raises ValueError."""
        env = {
            "STORAGE_BACKEND": "azure_blob",
            "AZURE_STORAGE_CONNECTION_STRING": "AccountName=only",
        }
        with patch.dict(os.environ, env):
            with pytest.raises(ValueError) as exc_info:
                get_storage_backend()
        msg = str(exc_info.value)
        # Should mention at least one missing key
        assert "AccountKey" in msg or "DefaultEndpointsProtocol" in msg

    def test_local_backend_unaffected_by_azure_env(self):
        """STORAGE_BACKEND=local returns LocalStorageBackend even with AZURE env vars set."""
        env = {
            "STORAGE_BACKEND": "local",
            "AZURE_STORAGE_CONNECTION_STRING": "invalid_junk",
        }
        with patch.dict(os.environ, env):
            backend = get_storage_backend()
        assert isinstance(backend, LocalStorageBackend)


class TestStorageBackendABC:
    """Verify the ABC contract is enforced."""

    def test_storage_backend_is_abstract(self):
        """StorageBackend cannot be instantiated directly."""
        with pytest.raises(TypeError):
            StorageBackend()  # type: ignore[abstract]

    def test_local_backend_is_storage_backend(self, tmp_path):
        """LocalStorageBackend is a concrete StorageBackend."""
        backend = LocalStorageBackend(base_dir=tmp_path)
        assert isinstance(backend, StorageBackend)


class TestGetStorageBackendFactory:
    """Unit tests for the get_storage_backend() factory function."""

    def test_defaults_to_local_backend(self, tmp_path):
        """Without STORAGE_BACKEND set, factory returns LocalStorageBackend."""
        with patch.dict(os.environ, {"STORAGE_BACKEND": "local"}):
            backend = get_storage_backend()
        assert isinstance(backend, LocalStorageBackend)

    def test_local_backend_explicit(self, tmp_path):
        """STORAGE_BACKEND=local returns LocalStorageBackend."""
        with patch.dict(os.environ, {"STORAGE_BACKEND": "local"}):
            backend = get_storage_backend()
        assert isinstance(backend, LocalStorageBackend)

    def test_azure_blob_without_connection_string_raises(self):
        """STORAGE_BACKEND=azure_blob without connection string raises ValueError."""
        env = {"STORAGE_BACKEND": "azure_blob"}
        # Remove AZURE_STORAGE_CONNECTION_STRING if set
        with patch.dict(os.environ, env):
            os.environ.pop("AZURE_STORAGE_CONNECTION_STRING", None)
            with pytest.raises(ValueError, match="AZURE_STORAGE_CONNECTION_STRING"):
                get_storage_backend()


class TestLocalStorageBackend:
    """Unit tests for LocalStorageBackend."""

    @pytest.fixture
    def storage(self, tmp_path) -> LocalStorageBackend:
        return LocalStorageBackend(base_dir=tmp_path)

    # --- save_file ---

    def test_save_file_creates_file(self, storage, tmp_path):
        """save_file writes bytes to disk and returns the absolute path."""
        result = storage.save_file(b"hello", "campaign/product/image.png")
        expected = tmp_path / "campaign" / "product" / "image.png"
        assert expected.exists()
        assert result == str(expected)

    def test_save_file_creates_parent_dirs(self, storage, tmp_path):
        """save_file creates intermediate directories automatically."""
        storage.save_file(b"data", "a/b/c/d/file.txt")
        assert (tmp_path / "a" / "b" / "c" / "d" / "file.txt").exists()

    def test_save_file_returns_absolute_path(self, storage):
        """save_file return value is an absolute path string."""
        result = storage.save_file(b"x", "test.bin")
        assert Path(result).is_absolute()

    def test_save_file_content_correct(self, storage):
        """Saved file contains the exact bytes that were passed."""
        data = b"\x00\x01\x02\x03"
        path = storage.save_file(data, "binary.bin")
        assert Path(path).read_bytes() == data

    # --- file_exists ---

    def test_file_exists_true_after_save(self, storage):
        """file_exists returns True for a file that was just saved."""
        storage.save_file(b"x", "exists.txt")
        assert storage.file_exists("exists.txt") is True

    def test_file_exists_false_for_missing(self, storage):
        """file_exists returns False for a path that has not been saved."""
        assert storage.file_exists("nonexistent.txt") is False

    def test_file_exists_accepts_absolute_path(self, storage, tmp_path):
        """file_exists works with an absolute path."""
        storage.save_file(b"y", "abs_check.txt")
        abs_path = str(tmp_path / "abs_check.txt")
        assert storage.file_exists(abs_path) is True

    # --- get_file ---

    def test_get_file_returns_bytes(self, storage):
        """get_file returns the exact bytes that were saved."""
        storage.save_file(b"roundtrip", "data.bin")
        assert storage.get_file("data.bin") == b"roundtrip"

    def test_get_file_raises_for_missing(self, storage):
        """get_file raises FileNotFoundError for a missing path."""
        with pytest.raises(FileNotFoundError):
            storage.get_file("missing.bin")

    def test_get_file_accepts_absolute_path(self, storage, tmp_path):
        """get_file works with an absolute path."""
        storage.save_file(b"abs", "absolute.txt")
        abs_path = str(tmp_path / "absolute.txt")
        assert storage.get_file(abs_path) == b"abs"

    # --- list_files ---

    def test_list_files_returns_saved_files(self, storage):
        """list_files returns paths for all files under the given prefix."""
        storage.save_file(b"a", "camp/prod/1.png")
        storage.save_file(b"b", "camp/prod/2.png")
        files = storage.list_files("camp/prod")
        assert len(files) == 2

    def test_list_files_empty_for_missing_prefix(self, storage):
        """list_files returns an empty list when prefix does not exist."""
        assert storage.list_files("no_such_prefix") == []

    def test_list_files_scoped_to_prefix(self, storage):
        """list_files does not return files outside the requested prefix."""
        storage.save_file(b"in", "scope/file.png")
        storage.save_file(b"out", "other/file.png")
        files = storage.list_files("scope")
        assert all("scope" in f for f in files)
        assert len(files) == 1

    # --- get_url ---

    def test_get_url_relative_path_returns_absolute(self, storage, tmp_path):
        """get_url for a relative path returns abs path under base_dir."""
        url = storage.get_url("campaign/image.png")
        assert url == str(tmp_path / "campaign" / "image.png")

    def test_get_url_absolute_path_returned_as_is(self, storage, tmp_path):
        """get_url for an absolute path returns it unchanged."""
        abs_path = str(tmp_path / "some" / "file.png")
        assert storage.get_url(abs_path) == abs_path

    # --- delete_file ---

    def test_delete_file_removes_file(self, storage, tmp_path):
        """delete_file removes a file that exists."""
        storage.save_file(b"data", "to_delete.txt")
        assert (tmp_path / "to_delete.txt").exists()
        storage.delete_file("to_delete.txt")
        assert not (tmp_path / "to_delete.txt").exists()

    def test_delete_file_raises_for_missing(self, storage):
        """delete_file raises FileNotFoundError for a non-existent file."""
        with pytest.raises(FileNotFoundError):
            storage.delete_file("nonexistent.txt")

    def test_delete_file_accepts_absolute_path(self, storage, tmp_path):
        """delete_file works with an absolute path."""
        storage.save_file(b"x", "abs_delete.txt")
        abs_path = str(tmp_path / "abs_delete.txt")
        storage.delete_file(abs_path)
        assert not (tmp_path / "abs_delete.txt").exists()

    def test_delete_file_does_not_affect_other_files(self, storage, tmp_path):
        """delete_file only removes the target file, not siblings."""
        storage.save_file(b"a", "keep.txt")
        storage.save_file(b"b", "remove.txt")
        storage.delete_file("remove.txt")
        assert (tmp_path / "keep.txt").exists()
        assert not (tmp_path / "remove.txt").exists()
