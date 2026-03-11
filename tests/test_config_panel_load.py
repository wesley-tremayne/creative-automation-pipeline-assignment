"""
Tests for US-019: Config Panel Doesn't Load Default Values on Open.

Validates that the toggleConfig() bug fix correctly loads config on panel
open, errors are logged instead of swallowed, and profile switching works.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a FastAPI TestClient."""
    from app import app
    return TestClient(app)


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Redirect CONFIG_DIR with default + named profile configs."""
    cfg = tmp_path / "config"
    cfg.mkdir()

    brand = {
        "brand_name": "LuminaCo",
        "primary_color": [255, 195, 0],
        "secondary_color": [20, 20, 30],
        "text_color": [255, 255, 255],
        "accent_color": [167, 139, 250],
        "font_family": "Inter",
        "logo_placement": "bottom-right",
        "safe_zone_percent": 5,
        "notes": "Primary colour is gold",
    }
    (cfg / "brand_guidelines.json").write_text(json.dumps(brand))

    prohibited = {
        "prohibited": [
            {"word": "guaranteed", "reason": "Absolute guarantees prohibited"},
            {"word": "cure", "reason": "Disease cure claims require approval"},
            {"word": "free", "reason": "Must meet FTC 'free' claim requirements"},
            {"word": "clinically proven", "reason": "Requires cited clinical evidence"},
            {"word": "miracle", "reason": "Hyperbolic claim not permissible"},
        ],
        "requires_disclaimer": [
            {"word": "results may vary", "reason": "Disclaimer copy required"},
            {"word": "limited time", "reason": "Offer end date required"},
            {"word": "sale", "reason": "Must reference original price"},
            {"word": "natural", "reason": "USDA/FDA guidelines may apply"},
        ],
        "superlatives": ["#1", "best", "most", "only", "first", "ultimate", "unbeatable", "world-class"],
    }
    (cfg / "prohibited_words.json").write_text(json.dumps(prohibited))

    # Named profile for switching test
    alt_brand = {**brand, "brand_name": "AltBrand", "font_family": "Roboto"}
    (cfg / "brand_guidelines_alt.json").write_text(json.dumps(alt_brand))

    monkeypatch.setattr("app.CONFIG_DIR", cfg)
    return cfg


@pytest.fixture
def html(client):
    """Fetch combined static content: index.html + app.js (JS extracted to separate file)."""
    r = client.get("/")
    assert r.status_code == 200
    parts = [r.text]
    js_r = client.get("/static/js/app.js")
    if js_r.status_code == 200:
        parts.append(js_r.text)
    return "\n".join(parts)


# ── Fix 1: toggleConfig always calls loadConfig ──────────────────────────


class TestToggleConfigAlwaysLoads:
    """Verify toggleConfig() always calls loadConfig() when panel opens."""

    def test_no_conditional_guard_on_load(self, html):
        """toggleConfig() should not check cfg-brand-name before calling loadConfig().

        The bug was: if (!document.getElementById('cfg-brand-name').value) loadConfig();
        The fix is: unconditionally call loadConfig() when configOpen is true.
        """
        # Extract the toggleConfig function body
        match = re.search(
            r"function\s+toggleConfig\s*\(\)\s*\{(.*?)\n\}", html, re.DOTALL
        )
        assert match, "toggleConfig function not found"
        body = match.group(1)

        # Should NOT contain the old guard checking cfg-brand-name
        assert "cfg-brand-name" not in body, (
            "toggleConfig still has the cfg-brand-name guard — bug not fixed"
        )

        # Should call loadConfig when panel opens
        assert "loadConfig()" in body

    def test_load_config_called_on_open(self, html):
        """toggleConfig calls loadConfig inside the configOpen branch."""
        match = re.search(
            r"function\s+toggleConfig\s*\(\)\s*\{(.*?)\n\}", html, re.DOTALL
        )
        body = match.group(1)
        # The pattern: if (configOpen) { loadConfig(); }
        assert re.search(r"if\s*\(\s*configOpen\s*\)", body), (
            "toggleConfig should check configOpen before calling loadConfig"
        )


# ── Fix 2: Error logging instead of silent catch ─────────────────────────


class TestErrorLogging:
    """Verify loadConfig() logs errors instead of swallowing them."""

    def test_no_empty_catch_block(self, html):
        """loadConfig should not have an empty catch {} block."""
        # Find the loadConfig function
        match = re.search(
            r"async\s+function\s+loadConfig\s*\(\)\s*\{", html
        )
        assert match, "loadConfig function not found"

        # Look for empty catch blocks in the vicinity
        load_config_start = match.start()
        # Get a reasonable chunk of code after the function start
        chunk = html[load_config_start:load_config_start + 3000]

        # Should NOT have catch {} or catch { }
        assert not re.search(r"catch\s*\{\s*\}", chunk), (
            "loadConfig still has empty catch {} — errors are silently swallowed"
        )

    def test_catch_logs_to_console(self, html):
        """loadConfig catch block should call console.error."""
        match = re.search(
            r"async\s+function\s+loadConfig\s*\(\)\s*\{", html
        )
        load_config_start = match.start()
        chunk = html[load_config_start:load_config_start + 3000]

        # Should have a catch that logs
        assert re.search(r"catch\s*\(\s*\w+\s*\)\s*\{[^}]*console\.error", chunk), (
            "loadConfig catch block should log errors with console.error"
        )


# ── Default config available via API (panel data source) ──────────────────


class TestDefaultConfigApiAvailable:
    """Verify the API endpoints that loadConfig() calls return correct data."""

    def test_brand_guidelines_api_returns_data(self, client, config_dir):
        """GET /api/config/brand-guidelines returns LuminaCo defaults."""
        r = client.get("/api/config/brand-guidelines")
        assert r.status_code == 200
        data = r.json()
        assert data["brand_name"] == "LuminaCo"
        assert data["font_family"] == "Inter"
        assert data["primary_color"] == [255, 195, 0]

    def test_prohibited_words_api_returns_all_entries(self, client, config_dir):
        """GET /api/config/prohibited-words returns 5 prohibited, 4 disclaimer, 8 superlatives."""
        r = client.get("/api/config/prohibited-words")
        assert r.status_code == 200
        data = r.json()
        assert len(data["prohibited"]) == 5
        assert len(data["requires_disclaimer"]) == 4
        assert len(data["superlatives"]) == 8

    def test_prohibited_words_have_word_and_reason(self, client, config_dir):
        """Each prohibited/disclaimer entry has both word and reason fields."""
        r = client.get("/api/config/prohibited-words")
        data = r.json()
        for entry in data["prohibited"]:
            assert "word" in entry and "reason" in entry
        for entry in data["requires_disclaimer"]:
            assert "word" in entry and "reason" in entry


# ── Profile switching via API ─────────────────────────────────────────────


class TestProfileSwitching:
    """Verify profile switching works — Default → named → Default."""

    def test_named_profile_returns_different_data(self, client, config_dir):
        """Named profile 'alt' returns different brand data than default."""
        default = client.get("/api/config/brand-guidelines").json()
        named = client.get("/api/config/brand-guidelines/alt").json()
        assert default["brand_name"] != named["brand_name"]
        assert named["brand_name"] == "AltBrand"
        assert named["font_family"] == "Roboto"

    def test_switch_back_to_default_returns_original(self, client, config_dir):
        """After loading a named profile, loading default returns original data."""
        original = client.get("/api/config/brand-guidelines").json()
        _ = client.get("/api/config/brand-guidelines/alt").json()
        back_to_default = client.get("/api/config/brand-guidelines").json()
        assert original == back_to_default

    def test_profiles_list_includes_named_profiles(self, client, config_dir):
        """GET /api/config/profiles lists the 'alt' profile."""
        r = client.get("/api/config/profiles")
        assert r.status_code == 200
        profiles = r.json()["profiles"]
        assert "alt" in profiles["brand-guidelines"]

    def test_load_config_profile_function_calls_load_config(self, html):
        """loadConfigProfile() calls loadConfig() (profile dropdown handler)."""
        match = re.search(
            r"function\s+loadConfigProfile\s*\(\)\s*\{(.*?)\}", html, re.DOTALL
        )
        assert match, "loadConfigProfile function not found"
        assert "loadConfig()" in match.group(1)


# ── Panel close/reopen behavior (JS structure) ───────────────────────────


class TestPanelReopenBehavior:
    """Verify that closing and reopening loads data again."""

    def test_toggle_config_reloads_every_open(self, html):
        """toggleConfig always calls loadConfig on open, not just first time.

        The fix ensures there's no one-time guard — every open triggers a fresh load.
        """
        match = re.search(
            r"function\s+toggleConfig\s*\(\)\s*\{(.*?)\n\}", html, re.DOTALL
        )
        body = match.group(1)

        # Should NOT contain any localStorage, flag, or "loaded" check
        assert "loaded" not in body.lower(), (
            "toggleConfig should not track a 'loaded' flag"
        )
        # The only condition should be configOpen
        if_blocks = re.findall(r"if\s*\([^)]+\)", body)
        for block in if_blocks:
            assert "configOpen" in block, (
                f"Unexpected condition in toggleConfig: {block}"
            )
