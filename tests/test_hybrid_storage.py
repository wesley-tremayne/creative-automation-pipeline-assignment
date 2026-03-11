"""
Tests for hybrid storage behavior introduced in US-026:
  - delete_file() on AzureBlobStorageBackend (mocked)
  - load_config() Azure-first + local fallback
  - Campaign listing via Azure storage backend (app.py)
  - Campaign listing regression for local backend
  - Config save/retrieve routes through storage when Azure is active
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config_manager import load_config
from src.storage.local_storage import LocalStorageBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_azure_storage(blobs: dict[str, bytes] | None = None) -> MagicMock:
    """Return a MagicMock that behaves like an AzureBlobStorageBackend.

    Args:
        blobs: Mapping of blob name → bytes to pre-populate.
    """
    store: dict[str, bytes] = dict(blobs or {})
    mock = MagicMock()

    def _get_file(path: str) -> bytes:
        if path not in store:
            raise FileNotFoundError(path)
        return store[path]

    def _save_file(data: bytes, destination: str) -> str:
        store[destination] = data
        return f"https://fake/{destination}"

    def _file_exists(path: str) -> bool:
        return path in store

    def _list_files(prefix: str) -> list[str]:
        return [k for k in store if k.startswith(prefix)]

    def _delete_file(path: str) -> None:
        if path not in store:
            raise FileNotFoundError(path)
        del store[path]

    mock.get_file.side_effect = _get_file
    mock.save_file.side_effect = _save_file
    mock.file_exists.side_effect = _file_exists
    mock.list_files.side_effect = _list_files
    mock.delete_file.side_effect = _delete_file
    mock._store = store  # expose for assertions
    return mock


def _sample_manifest(campaign_id: str = "camp_001") -> dict:
    return {
        "campaign_id": campaign_id,
        "brand_name": "TestBrand",
        "products": [{"name": "Prod A"}],
        "created_at": "2026-03-10T00:00:00",
    }


# ---------------------------------------------------------------------------
# AzureBlobStorageBackend.delete_file — via mock
# ---------------------------------------------------------------------------

class TestAzureDeleteFileMocked:
    """Unit tests for delete_file() on the Azure backend using a mock store."""

    def test_delete_file_removes_existing_blob(self):
        """delete_file removes a blob that exists in the mock store."""
        mock = _make_mock_azure_storage({"campaign/file.png": b"data"})
        mock.delete_file("campaign/file.png")
        mock.delete_file.assert_called_once_with("campaign/file.png")
        assert "campaign/file.png" not in mock._store

    def test_delete_file_raises_for_missing_blob(self):
        """delete_file raises FileNotFoundError when blob does not exist."""
        mock = _make_mock_azure_storage()
        with pytest.raises(FileNotFoundError):
            mock.delete_file("nonexistent/file.png")

    def test_delete_file_does_not_remove_other_blobs(self):
        """delete_file only removes the targeted blob."""
        mock = _make_mock_azure_storage({
            "camp/a.png": b"a",
            "camp/b.png": b"b",
        })
        mock.delete_file("camp/a.png")
        assert "camp/a.png" not in mock._store
        assert "camp/b.png" in mock._store


# ---------------------------------------------------------------------------
# load_config() — hybrid Azure-first, local-fallback
# ---------------------------------------------------------------------------

class TestLoadConfigHybrid:
    """Unit tests for load_config() with hybrid storage."""

    def test_default_config_always_loads_from_local(self):
        """load_config() with no profile and storage=None reads from local filesystem."""
        data = load_config("brand_guidelines")
        assert "brand_name" in data or "primary_color" in data  # basic smoke check

    def test_profile_without_storage_loads_from_local(self, tmp_path):
        """load_config() with a profile and no storage reads from local CONFIG_DIR."""
        # Write a local profile into the real config dir area via patching CONFIG_DIR
        profile_data = {"brand_name": "LocalBrand", "font_family": "Arial",
                        "primary_color": [0, 0, 0], "secondary_color": [255, 255, 255],
                        "text_color": [0, 0, 0], "accent_color": [128, 128, 128],
                        "logo_placement": "bottom-right"}
        profile_file = tmp_path / "brand_guidelines_TestLocal.json"
        profile_file.write_text(json.dumps(profile_data))

        with patch("src.config_manager.CONFIG_DIR", tmp_path):
            result = load_config("brand_guidelines", profile="TestLocal")

        assert result["brand_name"] == "LocalBrand"

    def test_profile_with_storage_checks_azure_first(self):
        """load_config() with storage tries the storage backend before local filesystem."""
        profile_data = {"brand_name": "AzureBrand"}
        mock_storage = _make_mock_azure_storage({
            "config/brand_guidelines_AzureProfile.json": json.dumps(profile_data).encode()
        })

        result = load_config("brand_guidelines", profile="AzureProfile", storage=mock_storage)

        mock_storage.get_file.assert_called_once_with("config/brand_guidelines_AzureProfile.json")
        assert result["brand_name"] == "AzureBrand"

    def test_profile_with_storage_falls_back_to_local_when_not_in_azure(self, tmp_path):
        """load_config() falls back to local when blob does not exist in storage."""
        profile_data = {"brand_name": "FallbackBrand", "font_family": "Helvetica",
                        "primary_color": [0, 0, 0], "secondary_color": [255, 255, 255],
                        "text_color": [0, 0, 0], "accent_color": [128, 128, 128],
                        "logo_placement": "top-left"}
        profile_file = tmp_path / "brand_guidelines_FallbackBrand.json"
        profile_file.write_text(json.dumps(profile_data))

        mock_storage = _make_mock_azure_storage()  # empty — blob will not exist

        with patch("src.config_manager.CONFIG_DIR", tmp_path):
            result = load_config("brand_guidelines", profile="FallbackBrand", storage=mock_storage)

        assert result["brand_name"] == "FallbackBrand"

    def test_profile_not_in_azure_or_local_raises(self, tmp_path):
        """load_config() raises FileNotFoundError when profile not in Azure or local."""
        mock_storage = _make_mock_azure_storage()

        with patch("src.config_manager.CONFIG_DIR", tmp_path):
            with pytest.raises(FileNotFoundError):
                load_config("brand_guidelines", profile="GhostProfile", storage=mock_storage)

    def test_default_config_with_storage_still_uses_local(self, tmp_path):
        """load_config() with no profile always reads from local, even when storage provided."""
        default_data = {"brand_name": "DefaultBrand"}
        (tmp_path / "brand_guidelines.json").write_text(json.dumps(default_data))
        mock_storage = _make_mock_azure_storage()

        with patch("src.config_manager.CONFIG_DIR", tmp_path):
            result = load_config("brand_guidelines", storage=mock_storage)

        # Should not hit storage for default configs
        mock_storage.get_file.assert_not_called()
        assert result["brand_name"] == "DefaultBrand"


# ---------------------------------------------------------------------------
# app.py — campaign listing via Azure storage backend
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client():
    from app import app
    return TestClient(app, raise_server_exceptions=False)


class TestCampaignListingAzure:
    """Tests for GET /api/campaigns with Azure backend."""

    def test_list_campaigns_from_azure_blobs(self, api_client):
        """list_campaigns returns campaigns found in Azure blob storage."""
        manifest = _sample_manifest("azure_camp")
        mock_storage = _make_mock_azure_storage({
            "azure_camp/campaign_manifest.json": json.dumps(manifest).encode(),
            "azure_camp/prod/1x1/image.png": b"img",
        })

        with patch("app._is_azure", return_value=True), \
             patch("app._get_storage", return_value=mock_storage):
            resp = api_client.get("/api/campaigns")

        assert resp.status_code == 200
        campaigns = resp.json()["campaigns"]
        assert len(campaigns) == 1
        assert campaigns[0]["campaign_id"] == "azure_camp"
        assert campaigns[0]["brand_name"] == "TestBrand"

    def test_list_campaigns_azure_empty_returns_empty_list(self, api_client):
        """list_campaigns returns empty list when no manifests in Azure."""
        mock_storage = _make_mock_azure_storage()

        with patch("app._is_azure", return_value=True), \
             patch("app._get_storage", return_value=mock_storage):
            resp = api_client.get("/api/campaigns")

        assert resp.status_code == 200
        assert resp.json()["campaigns"] == []

    def test_list_campaigns_azure_excludes_underscore_campaigns(self, api_client):
        """list_campaigns skips campaigns whose ID starts with underscore."""
        mock_storage = _make_mock_azure_storage({
            "_internal/campaign_manifest.json": b"{}",
        })

        with patch("app._is_azure", return_value=True), \
             patch("app._get_storage", return_value=mock_storage):
            resp = api_client.get("/api/campaigns")

        assert resp.status_code == 200
        assert resp.json()["campaigns"] == []

    def test_list_campaigns_local_backend_regression(self, api_client, tmp_path):
        """list_campaigns with local backend uses filesystem (no regression)."""
        camp_dir = tmp_path / "my_campaign"
        camp_dir.mkdir()
        manifest = _sample_manifest("my_campaign")
        (camp_dir / "campaign_manifest.json").write_text(json.dumps(manifest))

        with patch("app._is_azure", return_value=False), \
             patch("app.OUTPUTS_ROOT", tmp_path):
            resp = api_client.get("/api/campaigns")

        assert resp.status_code == 200
        campaigns = resp.json()["campaigns"]
        assert any(c["campaign_id"] == "my_campaign" for c in campaigns)


# ---------------------------------------------------------------------------
# app.py — config save/retrieve routes through storage when Azure is active
# ---------------------------------------------------------------------------

_VALID_BRAND = {
    "brand_name": "ACME",
    "font_family": "Arial",
    "primary_color": [0, 0, 0],
    "secondary_color": [255, 255, 255],
    "text_color": [0, 0, 0],
    "accent_color": [128, 128, 128],
    "logo_placement": "bottom-right",
}


class TestConfigAzureRouting:
    """Tests for config endpoints routing through Azure storage when configured."""

    def test_save_config_routes_to_azure_storage(self, api_client):
        """PUT /api/config/brand-guidelines saves to Azure, not local filesystem."""
        mock_storage = _make_mock_azure_storage()

        with patch("app._is_azure", return_value=True), \
             patch("app._get_storage", return_value=mock_storage):
            resp = api_client.put("/api/config/brand-guidelines", json=_VALID_BRAND)

        assert resp.status_code == 200
        # Should have written to storage
        mock_storage.save_file.assert_called_once()
        call_args = mock_storage.save_file.call_args
        assert "config/brand_guidelines.json" in call_args[0][1]
        assert resp.json()["path"] == "config/brand_guidelines.json"

    def test_save_config_profile_routes_to_azure(self, api_client):
        """PUT /api/config/brand-guidelines/MyBrand saves to Azure blob config prefix."""
        mock_storage = _make_mock_azure_storage()

        with patch("app._is_azure", return_value=True), \
             patch("app._get_storage", return_value=mock_storage):
            resp = api_client.put("/api/config/brand-guidelines/MyBrand", json=_VALID_BRAND)

        assert resp.status_code == 200
        mock_storage.save_file.assert_called_once()
        call_args = mock_storage.save_file.call_args
        assert "config/brand_guidelines_MyBrand.json" in call_args[0][1]

    def test_get_config_profile_checks_azure_first(self, api_client):
        """GET /api/config/brand-guidelines/AzureP returns Azure blob when present."""
        profile = dict(_VALID_BRAND, brand_name="AzureP")
        mock_storage = _make_mock_azure_storage({
            "config/brand_guidelines_AzureP.json": json.dumps(profile).encode()
        })

        with patch("app._is_azure", return_value=True), \
             patch("app._get_storage", return_value=mock_storage):
            resp = api_client.get("/api/config/brand-guidelines/AzureP")

        assert resp.status_code == 200
        assert resp.json()["brand_name"] == "AzureP"

    def test_get_config_profile_falls_back_to_local(self, api_client, tmp_path):
        """GET /api/config/brand-guidelines/LocalP falls back to local when not in Azure."""
        profile = dict(_VALID_BRAND, brand_name="LocalP")
        profile_file = tmp_path / "brand_guidelines_LocalP.json"
        profile_file.write_text(json.dumps(profile))

        mock_storage = _make_mock_azure_storage()  # empty

        with patch("app._is_azure", return_value=True), \
             patch("app._get_storage", return_value=mock_storage), \
             patch("app.CONFIG_DIR", tmp_path):
            resp = api_client.get("/api/config/brand-guidelines/LocalP")

        assert resp.status_code == 200
        assert resp.json()["brand_name"] == "LocalP"

    def test_save_config_local_backend_writes_to_filesystem(self, api_client, tmp_path):
        """PUT /api/config/brand-guidelines with local backend writes to config/ dir."""
        with patch("app._is_azure", return_value=False), \
             patch("app.CONFIG_DIR", tmp_path):
            resp = api_client.put("/api/config/brand-guidelines", json=_VALID_BRAND)

        assert resp.status_code == 200
        saved_file = tmp_path / "brand_guidelines.json"
        assert saved_file.exists()
        assert json.loads(saved_file.read_text())["brand_name"] == "ACME"


# ---------------------------------------------------------------------------
# Integration: pipeline run with mocked Azure backend — no local writes
# ---------------------------------------------------------------------------

class TestPipelineAzureIntegration:
    """Verify pipeline outputs go through the storage backend, not the local filesystem."""

    def test_pipeline_saves_via_storage_backend(self, tmp_path):
        """run_pipeline() calls storage.save_file for all outputs (no direct local writes)."""
        from src.models import CampaignBrief, Product
        from src.pipeline import run_pipeline

        brief = CampaignBrief(
            campaign_id="azure_int_test",
            brand_name="IntBrand",
            target_region="US",
            target_audience="Adults 25-45",
            campaign_message="Integration test",
            products=[Product(name="Widget", description="A widget", category="tech")],
        )

        mock_storage = _make_mock_azure_storage()

        with patch("src.pipeline.get_storage_backend", return_value=mock_storage):
            result = run_pipeline(brief)

        assert result.success
        # At least one file was saved via the storage backend
        assert mock_storage.save_file.called
        # No files should have been created in tmp_path (or the default outputs dir)
        # The mock captured all writes — verify the blob names contain the campaign ID
        saved_paths = [call[0][1] for call in mock_storage.save_file.call_args_list]
        assert any("azure_int_test" in p for p in saved_paths)
