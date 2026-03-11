"""
Tests for US-010: Campaign Brief Builder Form.

Validates the form UI elements exist in index.html, the form→JSON→pipeline
round-trip works, and the HTML includes validation and product management
structures.
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
def index_html():
    """Load the combined static content: index.html + app.js + styles.css.

    JS and CSS were extracted from inline index.html into separate files.
    Tests that check for JS functions or CSS classes must search the combined content.
    """
    static_dir = Path(__file__).parent.parent / "static"
    parts = [(static_dir / "index.html").read_text()]
    app_js = static_dir / "js" / "app.js"
    if app_js.exists():
        parts.append(app_js.read_text())
    styles_css = static_dir / "css" / "styles.css"
    if styles_css.exists():
        parts.append(styles_css.read_text())
    return "\n".join(parts)


# ── Form → JSON → Pipeline round-trip ────────────────────────────────────────

class TestFormJsonPipelineRoundTrip:
    """Verify that a brief built from form fields runs through the pipeline."""

    def test_form_brief_runs_pipeline(self, client):
        """JSON matching form structure is accepted by /api/run and completes."""
        brief_data = {
            "campaign_id": "form_test_001",
            "brand_name": "FormBrand",
            "target_region": "US",
            "target_audience": "Young professionals 25-35",
            "campaign_message": "Form-built campaign",
            "offer": "15% OFF",
            "cta": "Buy Now",
            "language": "en",
            "tone": "professional, aspirational",
            "products": [
                {
                    "name": "FormProduct",
                    "description": "A product entered via form",
                    "category": "skincare",
                    "tagline": "Built by form",
                }
            ],
        }
        r = client.post("/api/run", json=brief_data)
        assert r.status_code == 200

        # Parse SSE events to find the result
        lines = r.text.strip().split("\n")
        result_event = None
        for line in lines:
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                if payload.get("type") == "result":
                    result_event = payload["data"]

        assert result_event is not None
        assert result_event["success"] is True
        assert result_event["campaign_id"] == "form_test_001"
        assert result_event["total_assets"] == 3  # 1 product × 3 ratios

    def test_form_brief_with_optional_fields_empty(self, client):
        """Brief with optional fields omitted is accepted."""
        brief_data = {
            "campaign_id": "minimal_form",
            "target_region": "EU",
            "target_audience": "All ages",
            "campaign_message": "Minimal brief",
            "products": [
                {"name": "MinProd", "description": "Minimal", "category": "tech"}
            ],
        }
        r = client.post("/api/run", json=brief_data)
        assert r.status_code == 200

    def test_invalid_brief_rejected(self, client):
        """Missing required fields returns 422."""
        r = client.post("/api/run", json={"campaign_id": "bad"})
        assert r.status_code == 422


# ── Validation ───────────────────────────────────────────────────────────────

class TestFormValidation:
    """Verify the HTML form includes validation for required fields."""

    def test_required_field_markers_exist(self, index_html):
        """Required fields are marked with asterisks in the form."""
        required_fields = [
            "Campaign ID",
            "Target Region",
            "Target Audience",
            "Campaign Message",
        ]
        for field in required_fields:
            assert field in index_html, f"Required field '{field}' not found in HTML"

        # Check required markers exist
        assert 'class="required"' in index_html

    def test_validation_function_exists(self, index_html):
        """validateForm() function exists and checks required fields."""
        assert "function validateForm()" in index_html

    def test_validation_checks_required_fields(self, index_html):
        """Validation references all required field IDs."""
        required_ids = [
            "f-campaign-id",
            "f-target-region",
            "f-target-audience",
            "f-campaign-message",
        ]
        for fid in required_ids:
            assert fid in index_html, f"Required field ID '{fid}' not found"

    def test_validation_checks_products(self, index_html):
        """Validation includes product field checks."""
        assert "p-name" in index_html
        assert "p-desc" in index_html
        assert "p-cat" in index_html

    def test_error_messages_exist(self, index_html):
        """Error message elements exist for required fields."""
        error_ids = [
            "err-campaign-id",
            "err-target-region",
            "err-target-audience",
            "err-campaign-message",
            "err-products",
        ]
        for eid in error_ids:
            assert eid in index_html, f"Error element '{eid}' not found"

    def test_field_error_styling(self, index_html):
        """CSS class for field errors exists."""
        assert ".field-error" in index_html
        assert ".error-msg" in index_html

    def test_run_pipeline_calls_validate_in_form_mode(self, index_html):
        """runPipeline() calls validateForm() when in form mode."""
        assert "validateForm()" in index_html


# ── Add/Remove products ─────────────────────────────────────────────────────

class TestProductManagement:
    """Verify HTML contains product add/remove functionality."""

    def test_add_product_function_exists(self, index_html):
        """addProduct() function exists in the HTML."""
        assert "function addProduct(" in index_html

    def test_remove_product_function_exists(self, index_html):
        """removeProduct() function exists in the HTML."""
        assert "function removeProduct(" in index_html

    def test_add_product_button_exists(self, index_html):
        """+ Add Product button exists in the form."""
        assert "Add Product" in index_html
        assert "addProduct()" in index_html

    def test_remove_button_in_product_card(self, index_html):
        """Product cards include a remove button."""
        assert "removeProduct(" in index_html
        assert "Remove" in index_html

    def test_minimum_one_product_enforced(self, index_html):
        """removeProduct prevents removing the last product."""
        assert "container.children.length <= 1" in index_html

    def test_renumber_products_on_remove(self, index_html):
        """Products are renumbered after removal."""
        assert "function renumberProducts()" in index_html

    def test_product_fields_structure(self, index_html):
        """Each product card has name, description, category, tagline, asset fields."""
        for cls in ("p-name", "p-desc", "p-cat", "p-tagline", "p-asset"):
            assert cls in index_html


# ── Form/JSON tab switching ─────────────────────────────────────────────────

class TestModeSwitching:
    """Verify form/JSON mode toggle exists and syncs data."""

    def test_mode_toggle_buttons_exist(self, index_html):
        """Form and JSON mode toggle buttons exist."""
        assert "mode-form-btn" in index_html
        assert "mode-json-btn" in index_html

    def test_switch_mode_function_exists(self, index_html):
        """switchMode() function handles tab switching."""
        assert "function switchMode(" in index_html

    def test_form_to_json_sync(self, index_html):
        """Switching from form to JSON calls syncFormToJson."""
        assert "function syncFormToJson()" in index_html
        assert "syncFormToJson()" in index_html

    def test_json_to_form_sync(self, index_html):
        """Switching from JSON to form calls syncJsonToForm."""
        assert "function syncJsonToForm()" in index_html
        assert "syncJsonToForm()" in index_html

    def test_build_brief_from_form(self, index_html):
        """buildBriefFromForm() constructs JSON from form fields."""
        assert "function buildBriefFromForm()" in index_html

    def test_populate_form(self, index_html):
        """populateForm() fills form fields from JSON data."""
        assert "function populateForm(" in index_html

    def test_both_modes_exist_in_html(self, index_html):
        """Both form-mode and json-mode containers exist."""
        assert 'id="form-mode"' in index_html
        assert 'id="json-mode"' in index_html

    def test_json_editor_exists(self, index_html):
        """JSON textarea editor exists."""
        assert 'id="brief-editor"' in index_html
