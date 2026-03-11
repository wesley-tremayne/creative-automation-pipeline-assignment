"""Tests for centralized application config (src/config.py)."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import Settings, load_settings


class TestSettingsDefaults:
    """Verify default field values on Settings."""

    def test_default_storage_backend_is_local(self):
        s = Settings()
        assert s.storage_backend == "local"

    def test_default_openai_api_key_is_none(self):
        s = Settings()
        assert s.openai_api_key is None

    def test_default_log_level_is_info(self):
        s = Settings()
        assert s.log_level == "INFO"

    def test_default_host_and_port(self):
        s = Settings()
        assert s.host == "0.0.0.0"
        assert s.port == 8000

    def test_default_paths_are_path_objects(self):
        s = Settings()
        assert isinstance(s.base_dir, Path)
        assert isinstance(s.outputs_dir, Path)
        assert isinstance(s.assets_dir, Path)
        assert isinstance(s.config_dir, Path)

    def test_settings_is_immutable(self):
        """Settings is a frozen dataclass — attributes cannot be reassigned."""
        s = Settings()
        with pytest.raises((AttributeError, TypeError)):
            s.log_level = "DEBUG"  # type: ignore[misc]


class TestSettingsHelpers:
    """Unit tests for has_openai_key() and has_azure_storage()."""

    def test_has_openai_key_false_when_none(self):
        s = Settings(openai_api_key=None)
        assert s.has_openai_key() is False

    def test_has_openai_key_false_when_empty(self):
        s = Settings(openai_api_key="")
        assert s.has_openai_key() is False

    def test_has_openai_key_false_for_placeholder(self):
        s = Settings(openai_api_key="sk-...your-key-here...")
        assert s.has_openai_key() is False

    def test_has_openai_key_true_for_real_key(self):
        s = Settings(openai_api_key="sk-real-key-value")
        assert s.has_openai_key() is True

    def test_has_azure_storage_false_by_default(self):
        s = Settings()
        assert s.has_azure_storage() is False

    def test_has_azure_storage_false_without_connection_string(self):
        s = Settings(storage_backend="azure_blob", azure_storage_connection_string=None)
        assert s.has_azure_storage() is False

    def test_has_azure_storage_true_when_configured(self):
        s = Settings(
            storage_backend="azure_blob",
            azure_storage_connection_string="DefaultEndpointsProtocol=https;...",
        )
        assert s.has_azure_storage() is True


class TestLoadSettings:
    """Unit tests for load_settings() — reads from environment variables."""

    def test_load_settings_returns_settings_instance(self):
        with patch.dict(os.environ, {}, clear=False):
            result = load_settings()
        assert isinstance(result, Settings)

    def test_load_settings_reads_openai_api_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env-key"}):
            s = load_settings()
        assert s.openai_api_key == "sk-env-key"

    def test_load_settings_reads_storage_backend(self):
        with patch.dict(os.environ, {"STORAGE_BACKEND": "local"}):
            s = load_settings()
        assert s.storage_backend == "local"

    def test_load_settings_reads_log_level(self):
        with patch.dict(os.environ, {"LOG_LEVEL": "debug"}):
            s = load_settings()
        assert s.log_level == "DEBUG"  # uppercased

    def test_load_settings_reads_host_and_port(self):
        with patch.dict(os.environ, {"HOST": "127.0.0.1", "PORT": "9000"}):
            s = load_settings()
        assert s.host == "127.0.0.1"
        assert s.port == 9000

    def test_load_settings_azure_blob_without_connection_string_raises(self):
        """Fail fast: azure_blob backend requires a connection string."""
        env = {"STORAGE_BACKEND": "azure_blob"}
        with patch.dict(os.environ, env):
            os.environ.pop("AZURE_STORAGE_CONNECTION_STRING", None)
            with pytest.raises(ValueError, match="AZURE_STORAGE_CONNECTION_STRING"):
                load_settings()

    def test_load_settings_azure_blob_with_connection_string_succeeds(self):
        env = {
            "STORAGE_BACKEND": "azure_blob",
            "AZURE_STORAGE_CONNECTION_STRING": "DefaultEndpointsProtocol=https;AccountName=test",
        }
        with patch.dict(os.environ, env):
            s = load_settings()
        assert s.storage_backend == "azure_blob"
        assert s.azure_storage_connection_string == "DefaultEndpointsProtocol=https;AccountName=test"
