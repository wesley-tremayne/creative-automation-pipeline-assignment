"""
Tests for US-009: Previous Campaigns — Rich Report Browser.

Validates the /api/campaigns endpoint returns enriched manifest data,
handles empty state, and that View Report links serve correct reports.
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
def _run_two_campaigns(tmp_path):
    """Run two pipeline campaigns so the campaigns list is populated."""
    briefs = [
        CampaignBrief(
            campaign_id="camp_alpha",
            brand_name="AlphaBrand",
            target_region="US",
            target_audience="Adults 25-45",
            campaign_message="Alpha message",
            products=[
                Product(name="Alpha Widget", description="Desc A", category="skincare"),
            ],
        ),
        CampaignBrief(
            campaign_id="camp_beta",
            brand_name="BetaBrand",
            target_region="EU",
            target_audience="Teens 16-22",
            campaign_message="Beta message",
            products=[
                Product(name="Beta Gadget", description="Desc B", category="tech"),
                Product(name="Beta Gizmo", description="Desc C", category="beverage"),
            ],
        ),
    ]
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
        for brief in briefs:
            run_pipeline(brief)
    yield briefs


class TestCampaignsList:
    """Verify /api/campaigns returns enriched card data."""

    def test_campaigns_with_manifests(self, client, _run_two_campaigns):
        """Cards contain brand_name, product_count, created_at from manifest."""
        r = client.get("/api/campaigns")
        assert r.status_code == 200
        data = r.json()
        campaigns = data["campaigns"]

        ids = {c["campaign_id"] for c in campaigns}
        assert "camp_alpha" in ids
        assert "camp_beta" in ids

        alpha = next(c for c in campaigns if c["campaign_id"] == "camp_alpha")
        assert alpha["brand_name"] == "AlphaBrand"
        assert alpha["product_count"] == 1
        assert alpha["has_report"] is True
        assert alpha["asset_count"] >= 3  # at least 1 product × 3 ratios
        assert "created_at" in alpha

        beta = next(c for c in campaigns if c["campaign_id"] == "camp_beta")
        assert beta["brand_name"] == "BetaBrand"
        assert beta["product_count"] == 2
        assert beta["asset_count"] >= 6  # at least 2 products × 3 ratios

    def test_manifest_written_during_pipeline(self, _run_two_campaigns, outputs_root):
        """Pipeline writes campaign_manifest.json with expected fields."""
        manifest_path = outputs_root / "camp_alpha" / "campaign_manifest.json"
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text())
        assert manifest["campaign_id"] == "camp_alpha"
        assert manifest["brand_name"] == "AlphaBrand"
        assert manifest["products"] == ["Alpha Widget"]
        assert manifest["asset_count"] == 3
        assert "created_at" in manifest


class TestEmptyState:
    """Verify /api/campaigns returns a clean empty response when no campaigns exist."""

    def test_empty_campaigns_list(self, client, tmp_path):
        """When outputs folder is empty or missing, return an empty list."""
        with patch("app.OUTPUTS_ROOT", tmp_path / "nonexistent_outputs"):
            r = client.get("/api/campaigns")
        assert r.status_code == 200
        assert r.json() == {"campaigns": []}


class TestViewReport:
    """Verify View Report links serve correct HTML reports."""

    def test_report_endpoint_serves_html(self, client, _run_two_campaigns):
        """GET /api/report/{campaign_id} returns the report HTML."""
        r = client.get("/api/report/camp_alpha")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "camp_alpha" in r.text

    def test_report_404_for_missing_campaign(self, client):
        """Non-existent campaign returns 404."""
        r = client.get("/api/report/nonexistent_campaign_xyz")
        assert r.status_code == 404

    def test_report_link_in_campaign_card_data(self, client, _run_two_campaigns):
        """Campaign entries with reports have has_report=True."""
        r = client.get("/api/campaigns")
        campaigns = r.json()["campaigns"]
        for c in campaigns:
            if c["campaign_id"] in ("camp_alpha", "camp_beta"):
                assert c["has_report"] is True
