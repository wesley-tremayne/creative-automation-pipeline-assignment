from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from src.models import CampaignBrief, Product


# ── Default configs for test isolation ────────────────────────────────────────
# These mirror the production config/ files so tests that rely on default
# config content (e.g. checking "guaranteed" is prohibited) work correctly
# without reading from the real filesystem.

_DEFAULT_BRAND = {
    "brand_name": "LuminaCo",
    "primary_color": [255, 195, 0],
    "secondary_color": [20, 20, 30],
    "text_color": [255, 255, 255],
    "accent_color": [167, 139, 250],
    "font_family": "Inter",
    "logo_placement": "bottom-right",
    "safe_zone_percent": 5,
    "notes": "Primary colour is gold.",
}

_DEFAULT_PROHIBITED = {
    "prohibited": [
        {"word": "guaranteed", "reason": "Absolute guarantees are prohibited without substantiation"},
        {"word": "cure", "reason": "Disease cure claims require regulatory approval"},
        {"word": "free", "reason": "Must meet FTC 'free' claim requirements; add T&Cs"},
        {"word": "clinically proven", "reason": "Requires cited clinical evidence"},
        {"word": "miracle", "reason": "Hyperbolic health/beauty claim — not permissible"},
    ],
    "requires_disclaimer": [
        {"word": "results may vary", "reason": "Disclaimer copy must appear in legal-size text"},
        {"word": "limited time", "reason": "Offer end date must be clearly stated"},
        {"word": "sale", "reason": "Sale price must reference original price per FTC"},
        {"word": "natural", "reason": "Definition per USDA/FDA guidelines may apply"},
    ],
    "superlatives": ["#1", "best", "most", "only", "first", "ultimate", "unbeatable", "world-class"],
}


@pytest.fixture(autouse=True)
def isolate_outputs(tmp_path, monkeypatch):
    """Redirect all pipeline outputs to a temp directory per test.

    Prevents tests from polluting the real outputs/ folder, which would
    show test artifacts in the web UI's Previous Campaigns section.
    """
    test_outputs = tmp_path / "outputs"
    test_outputs.mkdir()
    monkeypatch.setattr("src.pipeline.OUTPUTS_ROOT", test_outputs)
    # Patch the storage module's OUTPUTS_ROOT so get_storage_backend() also
    # uses the temp directory (introduced by the storage DI refactor).
    monkeypatch.setattr("src.storage.OUTPUTS_ROOT", test_outputs)
    # app.py imports OUTPUTS_ROOT from src.pipeline at module load time,
    # so we need to patch it there too if app has been imported.
    try:
        monkeypatch.setattr("app.OUTPUTS_ROOT", test_outputs)
    except AttributeError:
        pass
    # Also ensure OPENAI_API_KEY is empty so tests don't hit the real API
    monkeypatch.setenv("OPENAI_API_KEY", "")
    yield test_outputs


@pytest.fixture
def outputs_root(isolate_outputs):
    """Return the isolated outputs root path for tests that need to inspect output files."""
    return isolate_outputs


@pytest.fixture(autouse=True)
def isolate_logos(tmp_path, monkeypatch):
    """Redirect logo uploads and logo lookups to a temp directory per test.

    Patches app.LOGOS_DIR (where uploads are saved) and src.pipeline.LOGOS_DIR
    (where the pipeline resolves logo filenames) to the same temp directory,
    so tests that upload a logo then run the pipeline find the file correctly
    without touching the real assets/logos/ directory.
    """
    # Use "_logos" (not "logos") to avoid colliding with local fixtures in
    # tests that create their own tmp_path / "logos" directory.
    logos_dir = tmp_path / "_logos"
    logos_dir.mkdir()
    try:
        monkeypatch.setattr("app.LOGOS_DIR", logos_dir)
    except AttributeError:
        pass
    try:
        monkeypatch.setattr("src.pipeline.LOGOS_DIR", logos_dir)
    except AttributeError:
        pass
    yield logos_dir


@pytest.fixture
def mock_logo_file(tmp_path):
    """Create a minimal 1×1 PNG in the isolated logos dir and return the filename.

    Use in tests that require a logo file to exist on disk (e.g. logo upload or
    pipeline runs that reference a logo by filename). The file is placed in the
    same directory that isolate_logos patches into app.LOGOS_DIR and
    src.pipeline.LOGOS_DIR.
    """
    from PIL import Image

    img = Image.new("RGB", (1, 1), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    logos_dir = tmp_path / "_logos"
    logos_dir.mkdir(parents=True, exist_ok=True)
    filename = "test_logo.png"
    (logos_dir / filename).write_bytes(buf.getvalue())
    return filename


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Redirect CONFIG_DIR to a temp directory for all modules per test.

    Patches app.CONFIG_DIR, src.pipeline.CONFIG_DIR, src.content_checker.CONFIG_DIR
    and src.content_checker.CONFIG_PATH so tests never read from or write to the
    real config/ directory. Default brand guidelines and prohibited words are
    pre-populated so modules that call load_brand_guidelines() or check_content()
    without a profile work correctly.

    Tests that need specific config content (e.g. test_config_api.py) should
    declare their own config_dir fixture; its monkeypatch calls will take
    precedence over this autouse fixture for the attributes they patch.
    """
    cfg = tmp_path / "_config"
    cfg.mkdir()
    (cfg / "brand_guidelines.json").write_text(json.dumps(_DEFAULT_BRAND))
    (cfg / "prohibited_words.json").write_text(json.dumps(_DEFAULT_PROHIBITED))
    try:
        monkeypatch.setattr("app.CONFIG_DIR", cfg)
    except AttributeError:
        pass
    try:
        monkeypatch.setattr("src.pipeline.CONFIG_DIR", cfg)
    except AttributeError:
        pass
    try:
        monkeypatch.setattr("src.content_checker.CONFIG_DIR", cfg)
        monkeypatch.setattr("src.content_checker.CONFIG_PATH", cfg / "prohibited_words.json")
    except AttributeError:
        pass
    yield cfg


SAMPLE_BRIEF_YAML = """\
campaign_id: test_campaign
brand_name: TestBrand
target_region: US
target_audience: "Adults 25-45"
campaign_message: "Test message for campaign"
cta: "Shop Now"
language: en
tone: "professional"
products:
  - name: "Product A"
    description: "A great product for testing"
    category: skincare
    tagline: "Test Tagline"
  - name: "Product B"
    description: "Another product"
    category: beverage
"""

SAMPLE_BRIEF_JSON = """\
{
  "campaign_id": "json_campaign",
  "brand_name": "JsonBrand",
  "target_region": "EU",
  "target_audience": "All ages",
  "campaign_message": "JSON campaign message",
  "products": [
    {"name": "Widget", "description": "A widget", "category": "tech"}
  ]
}
"""


@pytest.fixture
def sample_brief():
    """A minimal CampaignBrief for unit tests."""
    return CampaignBrief(
        campaign_id="test_campaign",
        brand_name="TestBrand",
        target_region="US",
        target_audience="Adults 25-45",
        campaign_message="Test message for campaign",
        products=[
            Product(name="Product A", description="A great product", category="skincare"),
            Product(name="Product B", description="Another product", category="beverage"),
        ],
    )


@pytest.fixture
def brief_yaml_file(tmp_path):
    """Write a sample YAML brief to a temp file and return the path."""
    f = tmp_path / "test_brief.yaml"
    f.write_text(SAMPLE_BRIEF_YAML)
    return str(f)


@pytest.fixture
def brief_json_file(tmp_path):
    """Write a sample JSON brief to a temp file and return the path."""
    f = tmp_path / "test_brief.json"
    f.write_text(SAMPLE_BRIEF_JSON)
    return str(f)
