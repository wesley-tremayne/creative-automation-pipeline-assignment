"""
Tests for US-017: Brand Guidelines & Prohibited Words Config Editor.

Validates config API endpoints for GET/PUT, profile CRUD, validation,
persistence, and pipeline integration.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a FastAPI TestClient."""
    from app import app
    return TestClient(app)


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Redirect CONFIG_DIR to a temp directory with default config files."""
    cfg = tmp_path / "config"
    cfg.mkdir()

    brand = {
        "brand_name": "TestBrand",
        "primary_color": [255, 195, 0],
        "secondary_color": [20, 20, 30],
        "text_color": [255, 255, 255],
        "accent_color": [167, 139, 250],
        "font_family": "Inter",
        "logo_placement": "bottom-right",
        "safe_zone_percent": 5,
        "notes": "Test brand notes",
    }
    (cfg / "brand_guidelines.json").write_text(json.dumps(brand, indent=2))

    prohibited = {
        "prohibited": [{"word": "guaranteed", "reason": "No guarantees"}],
        "requires_disclaimer": [{"word": "sale", "reason": "Show original price"}],
        "superlatives": ["best", "most"],
    }
    (cfg / "prohibited_words.json").write_text(json.dumps(prohibited, indent=2))

    monkeypatch.setattr("app.CONFIG_DIR", cfg)
    return cfg


# ── Valid brand guidelines payload ─────────────────────────────────────────

VALID_BRAND = {
    "brand_name": "NewBrand",
    "primary_color": [100, 200, 50],
    "secondary_color": [10, 10, 10],
    "text_color": [255, 255, 255],
    "accent_color": [0, 128, 255],
    "font_family": "Helvetica",
    "logo_placement": "top-left",
    "safe_zone_percent": 10,
    "notes": "Updated notes",
}

VALID_PROHIBITED = {
    "prohibited": [{"word": "free", "reason": "FTC rules"}],
    "requires_disclaimer": [{"word": "limited time", "reason": "Show end date"}],
    "superlatives": ["ultimate", "greatest"],
}


# ── GET/PUT config endpoints ───────────────────────────────────────────────


class TestGetPutConfig:
    """Test reading and writing default configs."""

    def test_get_brand_guidelines(self, client, config_dir):
        """GET returns current brand guidelines."""
        r = client.get("/api/config/brand-guidelines")
        assert r.status_code == 200
        data = r.json()
        assert data["brand_name"] == "TestBrand"
        assert data["primary_color"] == [255, 195, 0]

    def test_get_prohibited_words(self, client, config_dir):
        """GET returns current prohibited words."""
        r = client.get("/api/config/prohibited-words")
        assert r.status_code == 200
        data = r.json()
        assert len(data["prohibited"]) == 1
        assert data["superlatives"] == ["best", "most"]

    def test_put_brand_guidelines(self, client, config_dir):
        """PUT saves and GET returns updated brand guidelines."""
        r = client.put("/api/config/brand-guidelines", json=VALID_BRAND)
        assert r.status_code == 200
        assert r.json()["status"] == "saved"

        r2 = client.get("/api/config/brand-guidelines")
        assert r2.json()["brand_name"] == "NewBrand"
        assert r2.json()["primary_color"] == [100, 200, 50]

    def test_put_prohibited_words(self, client, config_dir):
        """PUT saves and GET returns updated prohibited words."""
        r = client.put("/api/config/prohibited-words", json=VALID_PROHIBITED)
        assert r.status_code == 200

        r2 = client.get("/api/config/prohibited-words")
        assert r2.json()["prohibited"][0]["word"] == "free"
        assert r2.json()["superlatives"] == ["ultimate", "greatest"]

    def test_round_trip_brand(self, client, config_dir):
        """GET → PUT → GET round-trip preserves data exactly."""
        original = client.get("/api/config/brand-guidelines").json()
        client.put("/api/config/brand-guidelines", json=original)
        after = client.get("/api/config/brand-guidelines").json()
        assert original == after

    def test_get_unknown_config_type_404(self, client, config_dir):
        """Unknown config type returns 404."""
        r = client.get("/api/config/unknown-type")
        assert r.status_code == 404


# ── Profile CRUD ───────────────────────────────────────────────────────────


class TestProfileCRUD:
    """Test creating, listing, and loading named config profiles."""

    def test_create_and_load_brand_profile(self, client, config_dir):
        """Save a named brand profile, then load it back."""
        r = client.put("/api/config/brand-guidelines/luxury", json=VALID_BRAND)
        assert r.status_code == 200
        assert r.json()["profile"] == "luxury"

        r2 = client.get("/api/config/brand-guidelines/luxury")
        assert r2.status_code == 200
        assert r2.json()["brand_name"] == "NewBrand"

    def test_create_and_load_prohibited_profile(self, client, config_dir):
        """Save a named prohibited words profile, then load it back."""
        r = client.put("/api/config/prohibited-words/strict", json=VALID_PROHIBITED)
        assert r.status_code == 200

        r2 = client.get("/api/config/prohibited-words/strict")
        assert r2.json()["prohibited"][0]["word"] == "free"

    def test_list_profiles_empty(self, client, config_dir):
        """When no named profiles exist, lists are empty."""
        r = client.get("/api/config/profiles")
        assert r.status_code == 200
        profiles = r.json()["profiles"]
        assert profiles["brand-guidelines"] == []
        assert profiles["prohibited-words"] == []

    def test_list_profiles_after_create(self, client, config_dir):
        """Created profiles appear in the listing."""
        client.put("/api/config/brand-guidelines/acme", json=VALID_BRAND)
        client.put("/api/config/brand-guidelines/luxury", json=VALID_BRAND)
        client.put("/api/config/prohibited-words/strict", json=VALID_PROHIBITED)

        r = client.get("/api/config/profiles")
        profiles = r.json()["profiles"]
        assert "acme" in profiles["brand-guidelines"]
        assert "luxury" in profiles["brand-guidelines"]
        assert "strict" in profiles["prohibited-words"]

    def test_load_nonexistent_profile_404(self, client, config_dir):
        """Loading a profile that doesn't exist returns 404."""
        r = client.get("/api/config/brand-guidelines/nonexistent")
        assert r.status_code == 404

    def test_invalid_profile_name_rejected(self, client, config_dir):
        """Profile names with special chars are rejected."""
        r = client.put("/api/config/brand-guidelines/bad-name!", json=VALID_BRAND)
        assert r.status_code == 400

    def test_path_traversal_profile_name_rejected(self, client, config_dir):
        """Profile names with path traversal are rejected."""
        r = client.put("/api/config/brand-guidelines/../etc/passwd", json=VALID_BRAND)
        assert r.status_code in (400, 404, 422)


# ── Validation ─────────────────────────────────────────────────────────────


class TestValidation:
    """Test that invalid configs are rejected."""

    def test_missing_brand_name(self, client, config_dir):
        """Brand guidelines without brand_name is rejected."""
        data = {**VALID_BRAND}
        del data["brand_name"]
        r = client.put("/api/config/brand-guidelines", json=data)
        assert r.status_code == 400

    def test_invalid_color_not_list(self, client, config_dir):
        """Color field that isn't a list is rejected."""
        data = {**VALID_BRAND, "primary_color": "red"}
        r = client.put("/api/config/brand-guidelines", json=data)
        assert r.status_code == 400

    def test_invalid_color_wrong_length(self, client, config_dir):
        """Color with wrong number of elements is rejected."""
        data = {**VALID_BRAND, "primary_color": [255, 0]}
        r = client.put("/api/config/brand-guidelines", json=data)
        assert r.status_code == 400

    def test_invalid_color_out_of_range(self, client, config_dir):
        """Color value > 255 is rejected."""
        data = {**VALID_BRAND, "primary_color": [256, 0, 0]}
        r = client.put("/api/config/brand-guidelines", json=data)
        assert r.status_code == 400

    def test_invalid_color_negative(self, client, config_dir):
        """Negative color value is rejected."""
        data = {**VALID_BRAND, "accent_color": [-1, 0, 0]}
        r = client.put("/api/config/brand-guidelines", json=data)
        assert r.status_code == 400

    def test_invalid_logo_placement(self, client, config_dir):
        """Invalid logo placement is rejected."""
        data = {**VALID_BRAND, "logo_placement": "center"}
        r = client.put("/api/config/brand-guidelines", json=data)
        assert r.status_code == 400

    def test_prohibited_missing_word_field(self, client, config_dir):
        """Prohibited entry without 'word' field is rejected."""
        data = {
            "prohibited": [{"reason": "no word"}],
            "requires_disclaimer": [],
            "superlatives": [],
        }
        r = client.put("/api/config/prohibited-words", json=data)
        assert r.status_code == 400

    def test_prohibited_not_a_list(self, client, config_dir):
        """'prohibited' as non-list is rejected."""
        data = {
            "prohibited": "not a list",
            "requires_disclaimer": [],
            "superlatives": [],
        }
        r = client.put("/api/config/prohibited-words", json=data)
        assert r.status_code == 400

    def test_superlatives_must_be_strings(self, client, config_dir):
        """Superlatives with non-string entries is rejected."""
        data = {
            "prohibited": [],
            "requires_disclaimer": [],
            "superlatives": [123, True],
        }
        r = client.put("/api/config/prohibited-words", json=data)
        assert r.status_code == 400

    def test_valid_all_logo_placements(self, client, config_dir):
        """All four valid logo placements are accepted."""
        for placement in ("bottom-right", "bottom-left", "top-right", "top-left"):
            data = {**VALID_BRAND, "logo_placement": placement}
            r = client.put("/api/config/brand-guidelines", json=data)
            assert r.status_code == 200, f"Failed for {placement}"


# ── Color conversion (hex ↔ RGB) ──────────────────────────────────────────


class TestColorConversion:
    """Test that RGB arrays correctly round-trip through the API.

    The hex ↔ RGB conversion happens in the UI (JavaScript), but we verify
    that the API correctly stores and returns [R, G, B] arrays with integer
    values, which is the contract the UI depends on.
    """

    def test_rgb_boundary_values(self, client, config_dir):
        """Colors at boundary values (0, 255) are stored correctly."""
        data = {**VALID_BRAND, "primary_color": [0, 0, 0], "text_color": [255, 255, 255]}
        client.put("/api/config/brand-guidelines", json=data)
        result = client.get("/api/config/brand-guidelines").json()
        assert result["primary_color"] == [0, 0, 0]
        assert result["text_color"] == [255, 255, 255]

    def test_all_color_fields_round_trip(self, client, config_dir):
        """All four color fields are stored as [R,G,B] arrays."""
        data = {
            **VALID_BRAND,
            "primary_color": [10, 20, 30],
            "secondary_color": [40, 50, 60],
            "text_color": [70, 80, 90],
            "accent_color": [100, 110, 120],
        }
        client.put("/api/config/brand-guidelines", json=data)
        result = client.get("/api/config/brand-guidelines").json()
        assert result["primary_color"] == [10, 20, 30]
        assert result["secondary_color"] == [40, 50, 60]
        assert result["text_color"] == [70, 80, 90]
        assert result["accent_color"] == [100, 110, 120]

    def test_color_float_rejected(self, client, config_dir):
        """Float color values are rejected (must be int)."""
        data = {**VALID_BRAND, "primary_color": [255.5, 0, 0]}
        r = client.put("/api/config/brand-guidelines", json=data)
        assert r.status_code == 400


# ── Config persistence ─────────────────────────────────────────────────────


class TestConfigPersistence:
    """Test that saved configs persist on disk and survive reload."""

    def test_brand_saved_to_disk(self, client, config_dir):
        """PUT writes the config to the JSON file on disk."""
        client.put("/api/config/brand-guidelines", json=VALID_BRAND)
        on_disk = json.loads((config_dir / "brand_guidelines.json").read_text())
        assert on_disk["brand_name"] == "NewBrand"
        assert on_disk["primary_color"] == [100, 200, 50]

    def test_profile_saved_to_disk(self, client, config_dir):
        """Named profile is written to a separate file."""
        client.put("/api/config/brand-guidelines/testprofile", json=VALID_BRAND)
        profile_path = config_dir / "brand_guidelines_testprofile.json"
        assert profile_path.exists()
        on_disk = json.loads(profile_path.read_text())
        assert on_disk["brand_name"] == "NewBrand"

    def test_default_not_affected_by_profile_save(self, client, config_dir):
        """Saving a named profile doesn't change the default config."""
        original = client.get("/api/config/brand-guidelines").json()
        client.put("/api/config/brand-guidelines/other", json=VALID_BRAND)
        after = client.get("/api/config/brand-guidelines").json()
        assert original == after

    def test_prohibited_words_saved_to_disk(self, client, config_dir):
        """PUT writes prohibited words to the JSON file on disk."""
        client.put("/api/config/prohibited-words", json=VALID_PROHIBITED)
        on_disk = json.loads((config_dir / "prohibited_words.json").read_text())
        assert on_disk["prohibited"][0]["word"] == "free"
        assert on_disk["superlatives"] == ["ultimate", "greatest"]


# ── Pipeline integration ──────────────────────────────────────────────────


class TestPipelineUsesConfig:
    """Test that the pipeline reads the config from disk each run."""

    def test_pipeline_reads_brand_guidelines_from_config_dir(self, config_dir, monkeypatch):
        """load_brand_guidelines() reads from CONFIG_DIR, picking up changes."""
        monkeypatch.setattr("src.pipeline.CONFIG_DIR", config_dir)

        from src.pipeline import load_brand_guidelines

        # Read current defaults
        guidelines = load_brand_guidelines()
        assert guidelines["brand_name"] == "TestBrand"

        # Simulate a config change (as if saved through the API)
        updated = {**guidelines, "brand_name": "UpdatedBrand", "font_family": "Roboto"}
        (config_dir / "brand_guidelines.json").write_text(json.dumps(updated))

        # Next call picks up the change (no restart needed)
        guidelines2 = load_brand_guidelines()
        assert guidelines2["brand_name"] == "UpdatedBrand"
        assert guidelines2["font_family"] == "Roboto"

    def test_pipeline_fallback_when_config_missing(self, tmp_path, monkeypatch):
        """Pipeline gracefully falls back when brand_guidelines.json is missing."""
        empty_config = tmp_path / "empty_config"
        empty_config.mkdir()
        monkeypatch.setattr("src.pipeline.CONFIG_DIR", empty_config)

        from src.pipeline import load_brand_guidelines

        guidelines = load_brand_guidelines()
        # Should return fallback defaults without crashing
        assert isinstance(guidelines, dict)
        assert "primary_color" in guidelines
