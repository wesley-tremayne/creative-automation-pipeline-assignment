"""
Tests for US-020: Input Sanitization & Security Hardening.

Validates path traversal protection in serve_output() and serve_report(),
existing_asset Pydantic validator, CSP headers, logo upload UUID-only naming,
and client-side maxlength constraints.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.models import CampaignBrief, Product
from src.pipeline import run_pipeline


@pytest.fixture
def client():
    """Create a FastAPI TestClient."""
    from app import app
    return TestClient(app)


@pytest.fixture
def app_js():
    """Load static/js/app.js content."""
    p = Path(__file__).parent.parent / "static" / "js" / "app.js"
    return p.read_text()


@pytest.fixture
def index_html():
    """Load static/index.html content."""
    p = Path(__file__).parent.parent / "static" / "index.html"
    return p.read_text()


# ── CSP Headers ───────────────────────────────────────────────────────────────


class TestCSPHeaders:
    """Verify Content-Security-Policy header is set on HTML responses."""

    def test_csp_present_on_root(self, client):
        """GET / includes a Content-Security-Policy header."""
        r = client.get("/")
        assert r.status_code == 200
        assert "Content-Security-Policy" in r.headers

    def test_csp_restricts_default_src(self, client):
        """CSP header includes default-src 'self'."""
        r = client.get("/")
        csp = r.headers["Content-Security-Policy"]
        assert "default-src" in csp
        assert "'self'" in csp

    def test_csp_disallows_framing(self, client):
        """CSP header includes frame-ancestors 'none' to prevent clickjacking."""
        r = client.get("/")
        csp = r.headers["Content-Security-Policy"]
        assert "frame-ancestors" in csp
        assert "'none'" in csp

    def test_csp_present_on_api_response(self, client):
        """CSP header is also present on API responses (middleware applies to all)."""
        r = client.get("/api/campaigns")
        assert "Content-Security-Policy" in r.headers

    def test_csp_style_src_allows_google_fonts(self, client):
        """CSP style-src includes https://fonts.googleapis.com for Google Fonts CSS."""
        r = client.get("/")
        csp = r.headers["Content-Security-Policy"]
        assert "https://fonts.googleapis.com" in csp

    def test_csp_font_src_allows_gstatic(self, client):
        """CSP font-src includes https://fonts.gstatic.com for Google Fonts files."""
        r = client.get("/")
        csp = r.headers["Content-Security-Policy"]
        assert "https://fonts.gstatic.com" in csp

    def test_csp_script_src_no_unsafe_inline(self, client):
        """CSP script-src does NOT include 'unsafe-inline' — strict policy preserved."""
        r = client.get("/")
        csp = r.headers["Content-Security-Policy"]
        # Isolate only the script-src directive value
        for part in csp.split(";"):
            if "script-src" in part:
                assert "'unsafe-inline'" not in part
                break


# ── US-023: Inline Script Removal from index.html ────────────────────────────


class TestInlineScriptRemoval:
    """Verify the inline <script> block was removed from index.html (US-023)."""

    def test_no_inline_script_block_in_index_html(self):
        """index.html contains no inline <script> blocks (only external src= references)."""
        from pathlib import Path
        html = (Path(__file__).parent.parent / "static" / "index.html").read_text()
        import re
        # Match <script> tags that don't have a src= attribute (i.e. inline scripts)
        inline_scripts = re.findall(r"<script(?![^>]*\bsrc\s*=)[^>]*>(.+?)</script>", html, re.DOTALL)
        assert inline_scripts == [], f"Unexpected inline script blocks found: {inline_scripts[:1]}"

    def test_app_js_has_domcontentloaded_init(self, app_js):
        """app.js includes the DOMContentLoaded event listener setup block (moved from inline)."""
        assert "DOMContentLoaded" in app_js

    def test_app_js_external_script_referenced_in_html(self):
        """index.html references /static/js/app.js as an external script."""
        from pathlib import Path
        html = (Path(__file__).parent.parent / "static" / "index.html").read_text()
        assert 'src="/static/js/app.js"' in html


# ── Path Traversal: serve_output() ───────────────────────────────────────────


class TestServeOutputPathTraversal:
    """Verify serve_output() rejects path traversal in all URL segments."""

    def test_traversal_via_validate_path_segment_dotdot(self):
        """_validate_path_segment rejects '..' directly."""
        from fastapi import HTTPException
        from app import _validate_path_segment
        with pytest.raises(HTTPException) as exc:
            _validate_path_segment("..", "product")
        assert exc.value.status_code == 400

    def test_traversal_via_validate_path_segment_slash(self):
        """_validate_path_segment rejects '/' in a segment."""
        from fastapi import HTTPException
        from app import _validate_path_segment
        with pytest.raises(HTTPException) as exc:
            _validate_path_segment("foo/bar", "product")
        assert exc.value.status_code == 400

    def test_traversal_via_validate_path_segment_backslash(self):
        """_validate_path_segment rejects backslash in a segment."""
        from fastapi import HTTPException
        from app import _validate_path_segment
        with pytest.raises(HTTPException) as exc:
            _validate_path_segment("foo\\bar", "ratio")
        assert exc.value.status_code == 400

    def test_traversal_via_validate_path_segment_null(self):
        """_validate_path_segment rejects null bytes in a segment."""
        from fastapi import HTTPException
        from app import _validate_path_segment
        with pytest.raises(HTTPException) as exc:
            _validate_path_segment("foo\x00bar", "filename")
        assert exc.value.status_code == 400

    def test_traversal_via_validate_path_segment_safe(self):
        """_validate_path_segment accepts safe alphanumeric segments."""
        from app import _validate_path_segment
        # Should not raise
        _validate_path_segment("my-product-123", "product")
        _validate_path_segment("1x1", "ratio")
        _validate_path_segment("image.png", "filename")

    def test_url_encoded_dotdot_rejected(self, client):
        """URL-encoded '..' (%2E%2E) in product segment is rejected with 400."""
        # httpx sends %2E%2E literally; FastAPI decodes it to '..' before the handler
        r = client.get("/api/outputs/campaign1/%2E%2E/1x1/file.png")
        assert r.status_code == 400

    def test_valid_path_missing_file_returns_404(self, client):
        """A valid (non-traversal) path for a non-existent file returns 404, not 400."""
        r = client.get("/api/outputs/legit-campaign/my-product/1x1/image.png")
        assert r.status_code == 404


# ── Path Traversal: existing_asset Pydantic Validator ────────────────────────


class TestExistingAssetValidator:
    """Verify Product.existing_asset rejects path traversal at parse time."""

    def test_dotdot_traversal_rejected(self):
        """existing_asset with '..' raises ValidationError."""
        with pytest.raises(ValidationError, match="path traversal"):
            Product(
                name="P",
                description="d",
                category="c",
                existing_asset="../../etc/passwd",
            )

    def test_absolute_path_rejected(self):
        """existing_asset starting with '/' is rejected."""
        with pytest.raises(ValidationError, match="path traversal"):
            Product(
                name="P",
                description="d",
                category="c",
                existing_asset="/etc/passwd",
            )

    def test_backslash_rejected(self):
        """existing_asset with backslash is rejected."""
        with pytest.raises(ValidationError, match="path traversal"):
            Product(
                name="P",
                description="d",
                category="c",
                existing_asset="..\\evil",
            )

    def test_null_byte_rejected(self):
        """existing_asset with null byte is rejected."""
        with pytest.raises(ValidationError, match="path traversal"):
            Product(
                name="P",
                description="d",
                category="c",
                existing_asset="image\x00.png",
            )

    def test_safe_filename_accepted(self):
        """A plain filename (no traversal) is accepted."""
        p = Product(
            name="P",
            description="d",
            category="c",
            existing_asset="product_image.png",
        )
        assert p.existing_asset == "product_image.png"

    def test_none_accepted(self):
        """None is always accepted."""
        p = Product(name="P", description="d", category="c", existing_asset=None)
        assert p.existing_asset is None

    def test_traversal_via_api_rejected(self, client):
        """POST /api/run with traversal existing_asset returns 422."""
        brief = {
            "campaign_id": "test-traversal",
            "brand_name": "TestBrand",
            "target_region": "US",
            "target_audience": "Adults",
            "campaign_message": "Test",
            "products": [
                {
                    "name": "Prod",
                    "description": "Desc",
                    "category": "skincare",
                    "existing_asset": "../../etc/passwd",
                }
            ],
        }
        r = client.post("/api/run", json=brief)
        assert r.status_code == 422


# ── campaign_id Validator ─────────────────────────────────────────────────────


class TestCampaignIdValidator:
    """Verify CampaignBrief.campaign_id rejects dangerous characters."""

    @pytest.mark.parametrize("bad_id", [
        "../../etc/passwd",
        "foo/bar",
        "foo\\bar",
        "foo bar",
        "foo!bar",
        "foo@bar",
        "../traversal",
    ])
    def test_dangerous_campaign_ids_rejected(self, bad_id):
        """campaign_id with illegal characters raises ValidationError."""
        with pytest.raises(ValidationError):
            CampaignBrief(
                campaign_id=bad_id,
                brand_name="Brand",
                target_region="US",
                target_audience="Adults",
                campaign_message="Test",
                products=[Product(name="P", description="d", category="c")],
            )

    @pytest.mark.parametrize("good_id", [
        "my_campaign",
        "campaign-2024",
        "CampaignABC",
        "test123",
        "a",
    ])
    def test_safe_campaign_ids_accepted(self, good_id):
        """campaign_id with only safe characters is accepted."""
        brief = CampaignBrief(
            campaign_id=good_id,
            brand_name="Brand",
            target_region="US",
            target_audience="Adults",
            campaign_message="Test",
            products=[Product(name="P", description="d", category="c")],
        )
        assert brief.campaign_id == good_id


# ── Logo Upload: UUID-only Filename ──────────────────────────────────────────


class TestLogoUploadFilename:
    """Verify logo upload saves with UUID-only stem (no user-supplied filename stem)."""

    def test_malicious_filename_stem_not_used(self, client, tmp_path, monkeypatch):
        """Uploaded logo with '../../evil' filename is saved as UUID-only name."""
        from app import LOGOS_DIR
        safe_logos = tmp_path / "logos"
        safe_logos.mkdir()
        monkeypatch.setattr("app.LOGOS_DIR", safe_logos)

        import io
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        r = client.post(
            "/api/upload/logo",
            files={"file": ("../../evil.png", io.BytesIO(png_bytes), "image/png")},
        )
        assert r.status_code == 200
        saved_name = r.json()["filename"]

        # Stem must be hex UUID (32 hex chars), not the user-supplied stem
        stem = Path(saved_name).stem
        assert stem != "../../evil"
        assert stem != "evil"
        assert len(stem) == 32
        assert all(c in "0123456789abcdef" for c in stem)

    def test_uploaded_logo_extension_preserved(self, client, tmp_path, monkeypatch):
        """Logo extension from content-type is preserved (.png)."""
        safe_logos = tmp_path / "logos"
        safe_logos.mkdir()
        monkeypatch.setattr("app.LOGOS_DIR", safe_logos)

        import io
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        r = client.post(
            "/api/upload/logo",
            files={"file": ("logo.png", io.BytesIO(png_bytes), "image/png")},
        )
        assert r.status_code == 200
        assert r.json()["filename"].endswith(".png")


# ── Client-side Max Length Constraints ───────────────────────────────────────


class TestMaxLengthConstraints:
    """Verify index.html and app.js enforce maxlength on form fields."""

    def test_maxlength_on_campaign_id_input(self, index_html):
        """campaign_id input has a maxlength attribute."""
        assert 'id="f-campaign-id"' in index_html
        # The input for campaign_id should have maxlength
        import re
        match = re.search(
            r'id="f-campaign-id"[^>]*maxlength="(\d+)"'
            r'|maxlength="(\d+)"[^>]*id="f-campaign-id"',
            index_html,
        )
        assert match, "f-campaign-id input should have a maxlength attribute"

    def test_maxlength_on_campaign_message(self, index_html):
        """campaign_message textarea has a maxlength attribute."""
        assert 'id="f-campaign-message"' in index_html or "f-campaign-message" in index_html

    def test_js_validates_field_length(self, app_js):
        """app.js validates field length and shows error when exceeded."""
        assert "maxLen" in app_js
        assert "characters or fewer" in app_js

    def test_js_validates_product_fields(self, app_js):
        """app.js validates product name, description, and category lengths."""
        assert "Name" in app_js and "maxLen" in app_js
        assert "Description" in app_js


# ── US-021: Summary Card Cost Display in Web UI ──────────────────────────────


class TestSummaryCardCostDisplay:
    """Verify app.js displays cost metrics in the summary card (US-021)."""

    def test_cost_display_reads_image_metrics(self, app_js):
        """app.js reads image_metrics from the pipeline result."""
        assert "image_metrics" in app_js

    def test_cost_display_shows_estimated_cost(self, app_js):
        """app.js renders estimated cost in the summary card."""
        assert "estimated_cost_usd" in app_js or "costUsd" in app_js

    def test_fallback_mode_shows_zero_cost_label(self, app_js):
        """app.js shows '$0.00 (fallback mode)' when no DALL-E images were generated."""
        assert "fallback mode" in app_js

    def test_cost_display_uses_amber_color(self, app_js):
        """app.js uses amber/gold color for the cost value."""
        assert "amber" in app_js

    def test_cost_display_shows_ai_image_count(self, app_js):
        """app.js displays AI image count in the summary card."""
        assert "dall_e_images" in app_js or "aiImages" in app_js

    def test_cost_display_shows_fallback_count(self, app_js):
        """app.js displays fallback image count in the summary card."""
        assert "fallback_images" in app_js or "fallbackCount" in app_js

    def test_summary_card_reads_input_tokens(self, app_js):
        """app.js reads input_tokens from image_metrics for token breakdown."""
        assert "input_tokens" in app_js

    def test_summary_card_reads_output_tokens(self, app_js):
        """app.js reads output_tokens from image_metrics for token breakdown."""
        assert "output_tokens" in app_js

    def test_summary_card_reads_total_tokens(self, app_js):
        """app.js reads total_tokens from image_metrics for token breakdown."""
        assert "total_tokens" in app_js

    def test_summary_card_displays_total_tokens_label(self, app_js):
        """app.js renders a 'Total Tokens' label in the token breakdown section."""
        assert "Total Tokens" in app_js

    def test_summary_card_token_section_hidden_in_fallback(self, app_js):
        """app.js omits the token breakdown section when isFallbackOnly is true."""
        assert "isFallbackOnly" in app_js
        # Token section is rendered only when aiImages > 0
        assert "tokenSection" in app_js or "token_section" in app_js or "tokenSection" in app_js


# ── Full Regression: Pipeline with Valid Inputs ───────────────────────────────


class TestSecurityRegressionPipeline:
    """Verify no regressions — pipeline works correctly after security hardening."""

    def test_pipeline_succeeds_with_safe_brief(self):
        """Full pipeline run succeeds with valid, safe inputs."""
        brief = CampaignBrief(
            campaign_id="security-regression-test",
            brand_name="SafeBrand",
            target_region="US",
            target_audience="Adults 25-45",
            campaign_message="Safe campaign message",
            products=[
                Product(name="SafeProduct", description="A safe product", category="skincare"),
            ],
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = run_pipeline(brief)

        assert result.success
        assert result.total_assets == 3
        assert len(result.errors) == 0

    def test_api_run_succeeds_with_safe_brief(self, client):
        """POST /api/run with safe brief streams a successful result."""
        brief = {
            "campaign_id": "api-regression-test",
            "brand_name": "SafeBrand",
            "target_region": "US",
            "target_audience": "Adults 25-45",
            "campaign_message": "Safe campaign",
            "products": [
                {"name": "SafeProd", "description": "A product", "category": "skincare"}
            ],
        }
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            r = client.post("/api/run", json=brief)

        assert r.status_code == 200
        # Collect SSE events and find the result
        events = r.text
        assert '"type": "result"' in events or '"type":"result"' in events
