"""
Tests for US-012: Reuse & Delete Previous Campaigns.

Validates that:
- Pipeline saves brief.json to the output folder
- GET /api/campaigns/{id}/brief returns the saved brief
- GET brief returns 404 for legacy campaigns without brief.json
- DELETE /api/campaigns/{id} removes the campaign folder
- DELETE returns 404 for nonexistent campaigns
- Path traversal attempts in campaign_id are rejected
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.models import CampaignBrief, Product
from src.pipeline import run_pipeline


@pytest.fixture
def client():
    """Create a FastAPI TestClient."""
    from app import app
    return TestClient(app)


@pytest.fixture
def run_campaign():
    """Run a single campaign and return the brief used."""
    brief = CampaignBrief(
        campaign_id="reuse_test",
        brand_name="ReuseBrand",
        target_region="US",
        target_market="United States",
        target_audience="Adults 25-45",
        campaign_message="Reuse test message",
        offer="20% OFF",
        cta="Buy Now",
        language="es",
        tone="bold, modern",
        website="https://example.com",
        products=[
            Product(
                name="ReuseProd",
                description="A reusable product",
                category="skincare",
                tagline="Reuse me",
            ),
        ],
    )
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
        run_pipeline(brief)
    yield brief


# ── brief.json Persistence ───────────────────────────────────────────────────

class TestBriefPersistence:
    """Verify pipeline saves brief.json to the output folder."""

    def test_brief_json_written(self, run_campaign, outputs_root):
        """brief.json exists in the campaign output folder after pipeline run."""
        brief_path = outputs_root / "reuse_test" / "brief.json"
        assert brief_path.exists(), "brief.json was not written to output folder"

    def test_brief_json_contains_all_fields(self, run_campaign, outputs_root):
        """brief.json contains all original brief fields."""
        brief_path = outputs_root / "reuse_test" / "brief.json"
        data = json.loads(brief_path.read_text())

        assert data["campaign_id"] == "reuse_test"
        assert data["brand_name"] == "ReuseBrand"
        assert data["target_region"] == "US"
        assert data["target_market"] == "United States"
        assert data["target_audience"] == "Adults 25-45"
        assert data["campaign_message"] == "Reuse test message"
        assert data["offer"] == "20% OFF"
        assert data["cta"] == "Buy Now"
        assert data["language"] == "es"
        assert data["tone"] == "bold, modern"
        assert data["website"] == "https://example.com"

    def test_brief_json_contains_products(self, run_campaign, outputs_root):
        """brief.json includes full product data."""
        brief_path = outputs_root / "reuse_test" / "brief.json"
        data = json.loads(brief_path.read_text())

        assert len(data["products"]) == 1
        product = data["products"][0]
        assert product["name"] == "ReuseProd"
        assert product["description"] == "A reusable product"
        assert product["category"] == "skincare"
        assert product["tagline"] == "Reuse me"

    def test_brief_json_is_valid_campaign_brief(self, run_campaign, outputs_root):
        """brief.json can be deserialized back into a CampaignBrief."""
        brief_path = outputs_root / "reuse_test" / "brief.json"
        data = json.loads(brief_path.read_text())
        brief = CampaignBrief(**data)
        assert brief.campaign_id == "reuse_test"
        assert len(brief.products) == 1


# ── GET /api/campaigns/{id}/brief ────────────────────────────────────────────

class TestGetBriefEndpoint:
    """Verify the brief retrieval endpoint."""

    def test_returns_brief_data(self, client, run_campaign):
        """GET returns the saved brief JSON."""
        r = client.get("/api/campaigns/reuse_test/brief")
        assert r.status_code == 200
        data = r.json()
        assert data["campaign_id"] == "reuse_test"
        assert data["brand_name"] == "ReuseBrand"
        assert len(data["products"]) == 1

    def test_404_for_missing_brief(self, client, outputs_root):
        """GET returns 404 when brief.json doesn't exist (legacy campaign)."""
        # Create a campaign folder without brief.json
        legacy_dir = outputs_root / "legacy_no_brief"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "campaign_manifest.json").write_text("{}")

        try:
            r = client.get("/api/campaigns/legacy_no_brief/brief")
            assert r.status_code == 404
        finally:
            import shutil
            shutil.rmtree(legacy_dir, ignore_errors=True)

    def test_404_for_nonexistent_campaign(self, client):
        """GET returns 404 for a campaign that doesn't exist at all."""
        r = client.get("/api/campaigns/totally_nonexistent_xyz/brief")
        assert r.status_code == 404


# ── DELETE /api/campaigns/{id} ───────────────────────────────────────────────

class TestDeleteEndpoint:
    """Verify the campaign deletion endpoint."""

    def test_delete_removes_campaign(self, client, run_campaign, outputs_root):
        """DELETE removes the campaign folder and returns 204."""
        campaign_dir = outputs_root / "reuse_test"
        assert campaign_dir.exists()

        r = client.delete("/api/campaigns/reuse_test")
        assert r.status_code == 204
        assert not campaign_dir.exists()

    def test_delete_removes_all_files(self, client, run_campaign, outputs_root):
        """DELETE removes report, manifest, brief, and all assets."""
        campaign_dir = outputs_root / "reuse_test"
        # Verify files exist before delete
        assert (campaign_dir / "brief.json").exists()
        assert (campaign_dir / "campaign_manifest.json").exists()

        r = client.delete("/api/campaigns/reuse_test")
        assert r.status_code == 204
        assert not campaign_dir.exists()

    def test_delete_404_for_nonexistent(self, client):
        """DELETE returns 404 for a campaign that doesn't exist."""
        r = client.delete("/api/campaigns/nonexistent_campaign_xyz")
        assert r.status_code == 404

    def test_campaigns_list_updated_after_delete(self, client, run_campaign):
        """Campaign list no longer includes deleted campaign."""
        # Verify it's in the list first
        r = client.get("/api/campaigns")
        ids = {c["campaign_id"] for c in r.json()["campaigns"]}
        assert "reuse_test" in ids

        # Delete it
        client.delete("/api/campaigns/reuse_test")

        # Verify it's gone from the list
        r = client.get("/api/campaigns")
        ids = {c["campaign_id"] for c in r.json()["campaigns"]}
        assert "reuse_test" not in ids


# ── Path Traversal Security ──────────────────────────────────────────────────

class TestPathTraversalSecurity:
    """Verify path traversal attempts are rejected."""

    @pytest.mark.parametrize("malicious_id", [
        "../../../etc/passwd",
        "..%2F..%2Fetc",
        "campaign/../../../secrets",
        "campaign/../../etc",
        "campaign\\..\\..\\etc",
        "..\\windows\\system32",
    ])
    def test_get_brief_rejects_traversal(self, client, malicious_id):
        """GET brief rejects campaign IDs with path traversal."""
        r = client.get(f"/api/campaigns/{malicious_id}/brief")
        assert r.status_code in (400, 404, 422)

    @pytest.mark.parametrize("malicious_id", [
        "../../../etc/passwd",
        "campaign/../../../secrets",
        "campaign\\..\\..\\etc",
    ])
    def test_delete_rejects_traversal(self, client, malicious_id):
        """DELETE rejects campaign IDs with path traversal."""
        r = client.delete(f"/api/campaigns/{malicious_id}")
        assert r.status_code in (400, 404, 422)


# ── UI Elements ──────────────────────────────────────────────────────────────

class TestUIElements:
    """Verify Reuse and Delete buttons exist in the HTML."""

    @pytest.fixture
    def index_html(self):
        """Load combined static content: index.html + app.js (JS extracted to separate file)."""
        static_dir = Path(__file__).parent.parent / "static"
        parts = [(static_dir / "index.html").read_text()]
        app_js = static_dir / "js" / "app.js"
        if app_js.exists():
            parts.append(app_js.read_text())
        return "\n".join(parts)

    def test_reuse_button_exists(self, index_html):
        """Campaign cards include a Reuse button."""
        assert "reuseCampaign" in index_html
        assert "Reuse" in index_html

    def test_delete_button_exists(self, index_html):
        """Campaign cards include a Delete button."""
        assert "deleteCampaign" in index_html

    def test_delete_has_confirmation(self, index_html):
        """Delete uses a confirmation dialog before proceeding."""
        assert "confirm(" in index_html

    def test_reuse_modifies_campaign_id(self, index_html):
        """Reuse appends _v2 to the campaign ID to prevent overwriting."""
        assert "_v2" in index_html

    def test_reuse_populates_form(self, index_html):
        """Reuse calls populateForm to fill the form fields."""
        assert "populateForm(data)" in index_html

    def test_reuse_switches_to_form_mode(self, index_html):
        """Reuse switches to form mode after loading the brief."""
        assert "switchMode('form')" in index_html
