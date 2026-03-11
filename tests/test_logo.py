"""
Tests for US-014: Per-Campaign Logo — Upload or Generate.

Validates that:
- Logo upload endpoint validates file type and size
- Pipeline works with uploaded logo, generated logo, and no logo
- Different campaigns can use different logos
- Existing briefs without logo field still work
- Logo field is preserved in brief.json for reuse
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from src.models import CampaignBrief, Product
from src.pipeline import run_pipeline


@pytest.fixture
def client():
    """Create a FastAPI TestClient."""
    from app import app
    return TestClient(app)


def _make_png_bytes(width: int = 100, height: int = 100) -> bytes:
    """Create a minimal PNG image in memory."""
    img = Image.new("RGBA", (width, height), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_brief(**overrides) -> CampaignBrief:
    """Create a test brief with optional overrides."""
    defaults = dict(
        campaign_id="logo_test",
        brand_name="LogoBrand",
        target_region="US",
        target_audience="Adults 25-45",
        campaign_message="Logo test message",
        products=[
            Product(name="LogoProd", description="Desc", category="skincare"),
        ],
    )
    defaults.update(overrides)
    return CampaignBrief(**defaults)


# ── Logo Upload Endpoint ─────────────────────────────────────────────────────

class TestLogoUpload:
    """Verify POST /api/upload/logo validates and saves files correctly."""

    def test_upload_valid_png(self, client):
        """Uploading a valid PNG returns a filename."""
        png_data = _make_png_bytes()
        r = client.post(
            "/api/upload/logo",
            files={"file": ("test_logo.png", png_data, "image/png")},
        )
        assert r.status_code == 200
        data = r.json()
        assert "filename" in data
        assert data["filename"].endswith(".png")
        # US-020: filename stem is UUID-only (no user-supplied stem) for security
        stem = Path(data["filename"]).stem
        assert len(stem) == 32
        assert all(c in "0123456789abcdef" for c in stem)

    def test_upload_valid_jpeg(self, client):
        """Uploading a valid JPEG is accepted."""
        img = Image.new("RGB", (100, 100), (0, 255, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        r = client.post(
            "/api/upload/logo",
            files={"file": ("logo.jpg", buf.getvalue(), "image/jpeg")},
        )
        assert r.status_code == 200
        assert r.json()["filename"].endswith(".jpg")

    def test_upload_rejects_invalid_type(self, client):
        """Uploading a non-image file is rejected."""
        r = client.post(
            "/api/upload/logo",
            files={"file": ("doc.pdf", b"fake pdf content", "application/pdf")},
        )
        assert r.status_code == 400
        assert "Invalid file type" in r.json()["detail"]

    def test_upload_rejects_text_file(self, client):
        """Uploading a text file is rejected."""
        r = client.post(
            "/api/upload/logo",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert r.status_code == 400

    def test_upload_rejects_oversized_file(self, client):
        """Files over 5MB are rejected."""
        # Create a file just over 5MB
        big_data = b"\x00" * (5 * 1024 * 1024 + 1)
        r = client.post(
            "/api/upload/logo",
            files={"file": ("big.png", big_data, "image/png")},
        )
        assert r.status_code == 400
        assert "too large" in r.json()["detail"].lower() or "5MB" in r.json()["detail"]

    def test_uploaded_file_saved_to_disk(self, client):
        """Uploaded logo file is actually saved to assets/logos/."""
        png_data = _make_png_bytes()
        r = client.post(
            "/api/upload/logo",
            files={"file": ("saved_logo.png", png_data, "image/png")},
        )
        filename = r.json()["filename"]
        from app import LOGOS_DIR
        assert (LOGOS_DIR / filename).exists()

    def test_uploaded_filename_is_unique(self, client):
        """Uploading the same file twice produces different filenames."""
        png_data = _make_png_bytes()
        r1 = client.post(
            "/api/upload/logo",
            files={"file": ("dup.png", png_data, "image/png")},
        )
        r2 = client.post(
            "/api/upload/logo",
            files={"file": ("dup.png", png_data, "image/png")},
        )
        assert r1.json()["filename"] != r2.json()["filename"]


# ── Pipeline with Uploaded Logo ──────────────────────────────────────────────

class TestPipelineWithUploadedLogo:
    """Verify pipeline uses an uploaded logo on creatives."""

    def test_pipeline_with_logo_file(self, client, outputs_root):
        """Pipeline runs successfully with an uploaded logo filename."""
        # Upload a logo first
        png_data = _make_png_bytes()
        upload_r = client.post(
            "/api/upload/logo",
            files={"file": ("pipeline_logo.png", png_data, "image/png")},
        )
        logo_filename = upload_r.json()["filename"]

        brief = _make_brief(campaign_id="logo_upload_test", logo=logo_filename)
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = run_pipeline(brief)

        assert result.success
        assert result.total_assets == 3

        # Logo should be copied to campaign output folder
        logo_out = outputs_root / "logo_upload_test" / "_logos" / logo_filename
        assert logo_out.exists()


# ── Pipeline with No Logo ────────────────────────────────────────────────────

class TestPipelineNoLogo:
    """Verify pipeline works when no logo is specified."""

    def test_pipeline_no_logo_field(self):
        """Pipeline runs successfully with logo=None (default)."""
        brief = _make_brief(campaign_id="no_logo_test")
        assert brief.logo is None

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = run_pipeline(brief)

        assert result.success
        assert result.total_assets == 3

    def test_no_logo_dir_created_when_none(self, outputs_root):
        """No _logos directory is created when logo is None."""
        brief = _make_brief(campaign_id="no_logo_dir_test")
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            run_pipeline(brief)

        logos_dir = outputs_root / "no_logo_dir_test" / "_logos"
        assert not logos_dir.exists()


# ── Pipeline with Generated Logo ─────────────────────────────────────────────

class TestPipelineGenerateLogo:
    """Verify pipeline generates a text-based logo when logo='generate'."""

    def test_generate_logo_creates_file(self, outputs_root):
        """Pipeline with logo='generate' creates a logo PNG."""
        brief = _make_brief(campaign_id="gen_logo_test", logo="generate")
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = run_pipeline(brief)

        assert result.success
        logo_path = outputs_root / "gen_logo_test" / "_logos" / "generated_logo.png"
        assert logo_path.exists()

    def test_generated_logo_is_valid_image(self, outputs_root):
        """Generated logo is a valid PNG image."""
        brief = _make_brief(campaign_id="gen_logo_valid_test", logo="generate")
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            run_pipeline(brief)

        logo_path = outputs_root / "gen_logo_valid_test" / "_logos" / "generated_logo.png"
        img = Image.open(logo_path)
        assert img.format == "PNG"
        assert img.width > 0
        assert img.height > 0


# ── Different Logos per Campaign ─────────────────────────────────────────────

class TestDifferentLogosPerCampaign:
    """Verify two campaigns can use different logos."""

    def test_two_campaigns_different_logos(self, client, outputs_root):
        """Two campaigns with different logos each have the correct logo."""
        # Campaign 1: generated logo
        brief1 = _make_brief(
            campaign_id="diff_logo_1",
            brand_name="Brand1",
            logo="generate",
        )
        # Campaign 2: no logo
        brief2 = _make_brief(
            campaign_id="diff_logo_2",
            brand_name="Brand2",
            logo=None,
        )

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            r1 = run_pipeline(brief1)
            r2 = run_pipeline(brief2)

        assert r1.success
        assert r2.success

        # Campaign 1 should have a generated logo
        assert (outputs_root / "diff_logo_1" / "_logos" / "generated_logo.png").exists()
        # Campaign 2 should NOT have a _logos dir
        assert not (outputs_root / "diff_logo_2" / "_logos").exists()


# ── Backward Compatibility ───────────────────────────────────────────────────

class TestBackwardCompatibility:
    """Verify existing briefs without logo field still work."""

    def test_brief_without_logo_field(self):
        """A brief dict without logo key creates a valid CampaignBrief with logo=None."""
        data = {
            "campaign_id": "old_brief",
            "target_region": "US",
            "target_audience": "All",
            "campaign_message": "Legacy brief",
            "products": [
                {"name": "OldProd", "description": "Desc", "category": "skincare"}
            ],
        }
        brief = CampaignBrief(**data)
        assert brief.logo is None

    def test_old_yaml_brief_loads(self):
        """Existing YAML brief files without logo still load and run."""
        from src.pipeline import load_brief

        briefs_dir = Path(__file__).parent.parent / "briefs"
        yaml_briefs = list(briefs_dir.glob("*.yaml"))
        assert len(yaml_briefs) > 0, "No YAML briefs found for backward compat test"

        for brief_file in yaml_briefs:
            brief = load_brief(str(brief_file))
            # logo should default to None
            assert brief.logo is None

    def test_pipeline_runs_with_old_brief(self):
        """Pipeline completes successfully with a brief that has no logo field."""
        brief = _make_brief(campaign_id="compat_test")
        # Explicitly verify no logo is set
        assert brief.logo is None

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = run_pipeline(brief)

        assert result.success
        assert result.total_assets == 3


# ── Logo Preserved in brief.json for Reuse ───────────────────────────────────

class TestLogoReusePersistence:
    """Verify logo field is saved to brief.json and can be reused."""

    def test_logo_field_saved_in_brief_json(self, outputs_root):
        """brief.json includes the logo field value."""
        brief = _make_brief(campaign_id="logo_persist_test", logo="generate")
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            run_pipeline(brief)

        brief_path = outputs_root / "logo_persist_test" / "brief.json"
        assert brief_path.exists()
        data = json.loads(brief_path.read_text())
        assert data["logo"] == "generate"

    def test_no_logo_saved_as_null(self, outputs_root):
        """brief.json saves logo as null when None."""
        brief = _make_brief(campaign_id="logo_null_test", logo=None)
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            run_pipeline(brief)

        brief_path = outputs_root / "logo_null_test" / "brief.json"
        data = json.loads(brief_path.read_text())
        assert data["logo"] is None

    def test_logo_roundtrip_via_api(self, client):
        """Logo field survives pipeline run → brief.json → GET brief endpoint."""
        brief = _make_brief(campaign_id="logo_roundtrip_test", logo="generate")
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            run_pipeline(brief)

        r = client.get("/api/campaigns/logo_roundtrip_test/brief")
        assert r.status_code == 200
        assert r.json()["logo"] == "generate"

    def test_reuse_brief_creates_valid_campaign_brief(self, outputs_root):
        """brief.json with logo can be loaded back as a CampaignBrief."""
        brief = _make_brief(campaign_id="logo_reload_test", logo="generate")
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            run_pipeline(brief)

        brief_path = outputs_root / "logo_reload_test" / "brief.json"
        data = json.loads(brief_path.read_text())
        reloaded = CampaignBrief(**data)
        assert reloaded.logo == "generate"
        assert reloaded.campaign_id == "logo_reload_test"
