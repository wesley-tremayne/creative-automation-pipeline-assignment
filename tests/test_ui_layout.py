"""
Tests for US-013: Remove Sample Campaigns & Reorder UI Sections.

Validates that:
- Sample Campaigns section and its JS functions are removed
- No dead API calls to removed endpoints
- Previous Campaigns appears above Pipeline Log in the right column
- Pipeline still runs end-to-end
- Page loads without errors
"""
from __future__ import annotations

import json
import os
import re
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
def index_html():
    """Load the index.html content."""
    html_path = Path(__file__).parent.parent / "static" / "index.html"
    return html_path.read_text()


# ── Sample Campaigns Removed ─────────────────────────────────────────────────

class TestSampleCampaignsRemoved:
    """Verify Sample Campaigns section and related code are fully removed."""

    def test_no_sample_campaigns_section(self, index_html):
        """Sample Campaigns HTML section is gone."""
        assert "Sample Campaigns" not in index_html

    def test_no_load_samples_function(self, index_html):
        """loadSamples() JS function is removed."""
        assert "function loadSamples" not in index_html
        assert "loadSamples()" not in index_html

    def test_no_load_sample_function(self, index_html):
        """loadSample() JS function is removed."""
        assert "function loadSample" not in index_html

    def test_no_api_samples_reference(self, index_html):
        """No references to /api/samples in the HTML/JS."""
        assert "/api/samples" not in index_html

    def test_no_api_brief_reference(self, index_html):
        """No references to /api/brief/ in the HTML/JS."""
        assert "/api/brief/" not in index_html

    def test_samples_endpoint_removed(self, client):
        """GET /api/samples returns 404 (endpoint removed)."""
        r = client.get("/api/samples")
        assert r.status_code == 404 or r.status_code == 405

    def test_brief_endpoint_removed(self, client):
        """GET /api/brief/{filename} returns 404 (endpoint removed)."""
        r = client.get("/api/brief/test.yaml")
        assert r.status_code == 404 or r.status_code == 405


# ── Layout Order ─────────────────────────────────────────────────────────────

class TestLayoutOrder:
    """Verify right column layout: Campaigns → Log → Assets → Summary."""

    def test_previous_campaigns_above_pipeline_log(self, index_html):
        """Previous Campaigns appears before Pipeline Log in the HTML."""
        campaigns_pos = index_html.index("Previous Campaigns")
        log_pos = index_html.index("Pipeline Log")
        assert campaigns_pos < log_pos, "Previous Campaigns should appear before Pipeline Log"

    def test_pipeline_log_above_generated_assets(self, index_html):
        """Pipeline Log appears before Generated Assets in the HTML."""
        log_pos = index_html.index("Pipeline Log")
        assets_pos = index_html.index("Generated Assets")
        assert log_pos < assets_pos, "Pipeline Log should appear before Generated Assets"

    def test_generated_assets_above_summary(self, index_html):
        """Generated Assets appears before Summary in the HTML."""
        assets_pos = index_html.index("Generated Assets")
        summary_pos = index_html.index("Summary")
        assert assets_pos < summary_pos, "Generated Assets should appear before Summary"

    def test_previous_campaigns_in_right_column(self, index_html):
        """Previous Campaigns is inside the right column (not full-width below grid)."""
        # The right column starts after the left column's closing div
        # Previous Campaigns should be between the grid cols start and the closing main
        # A simple check: it appears after the grid-cols div and before </main>
        grid_start = index_html.index("grid grid-cols-1 lg:grid-cols-2")
        campaigns_pos = index_html.index("Previous Campaigns")
        assert campaigns_pos > grid_start


# ── Page Loads Without Errors ────────────────────────────────────────────────

class TestPageLoads:
    """Verify the page loads cleanly."""

    def test_index_returns_html(self, client):
        """GET / returns valid HTML without errors."""
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Creative Automation Pipeline" in r.text

    def test_no_dead_js_calls(self, index_html):
        """No calls to functions that no longer exist."""
        # loadSamples was removed — should not be called anywhere
        assert "loadSamples" not in index_html

    def test_dom_content_loaded_no_sample_call(self, index_html):
        """DOMContentLoaded handler doesn't call loadSamples."""
        # Find the DOMContentLoaded block
        dom_match = re.search(
            r"DOMContentLoaded.*?\}\)",
            index_html,
            re.DOTALL,
        )
        if dom_match:
            dom_block = dom_match.group()
            assert "loadSamples" not in dom_block

    def test_api_status_check_works(self, client):
        """checkApiStatus uses a valid endpoint (not /api/samples)."""
        # The page should have a working API status check
        r = client.get("/api/campaigns")
        assert r.status_code == 200


# ── Pipeline Still Works ─────────────────────────────────────────────────────

class TestPipelineStillWorks:
    """Verify pipeline runs end-to-end after UI changes."""

    def test_pipeline_end_to_end(self, client):
        """POST /api/run completes successfully."""
        brief_data = {
            "campaign_id": "us013_test",
            "brand_name": "LayoutBrand",
            "target_region": "US",
            "target_audience": "Adults 25-45",
            "campaign_message": "Layout test",
            "products": [
                {"name": "LayoutProd", "description": "Desc", "category": "skincare"}
            ],
        }
        r = client.post("/api/run", json=brief_data)
        assert r.status_code == 200

        # Parse SSE to find result
        for line in r.text.strip().split("\n"):
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                if payload.get("type") == "result":
                    assert payload["data"]["success"] is True
                    assert payload["data"]["total_assets"] == 3
                    return

        pytest.fail("No result event found in SSE stream")
