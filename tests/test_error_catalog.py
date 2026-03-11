"""
Tests for US-011: User-Friendly Pipeline Log Messages.

Validates that:
- Normal pipeline runs emit friendly user_message strings
- Error scenarios include reference codes and friendly messages
- Technical details (tracebacks, file paths) don't leak to SSE payloads
- The error catalog covers all failure modes used in the codebase
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.error_catalog import ERROR_CATALOG, get_user_error
from src.models import CampaignBrief, Product
from src.pipeline import run_pipeline


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """Create a FastAPI TestClient."""
    from app import app
    return TestClient(app)


@pytest.fixture
def simple_brief():
    """A minimal brief for testing pipeline messages."""
    return CampaignBrief(
        campaign_id="msg_test",
        brand_name="MsgBrand",
        target_region="US",
        target_audience="Adults 25-45",
        campaign_message="Test message",
        products=[
            Product(name="MsgProduct", description="Desc", category="skincare"),
        ],
    )


# ── Error Catalog Unit Tests ─────────────────────────────────────────────────

class TestErrorCatalog:
    """Verify error catalog structure and lookup function."""

    def test_all_entries_have_required_fields(self):
        """Every catalog entry must have user_message and admin_context."""
        for code, entry in ERROR_CATALOG.items():
            assert "user_message" in entry, f"{code} missing user_message"
            assert "admin_context" in entry, f"{code} missing admin_context"

    def test_user_messages_are_non_technical(self):
        """User messages should not contain technical jargon."""
        technical_terms = [
            "traceback", "stacktrace", "exception", "Pydantic",
            "Jinja2", "Pillow", ".py", "TypeError", "ValueError",
        ]
        for code, entry in ERROR_CATALOG.items():
            msg = entry["user_message"]
            for term in technical_terms:
                assert term.lower() not in msg.lower(), (
                    f"{code} user_message contains technical term '{term}': {msg}"
                )

    def test_get_user_error_known_code(self):
        """get_user_error returns the friendly message with reference code."""
        result = get_user_error("ERR-BRIEF-001")
        assert "Reference: ERR-BRIEF-001" in result
        assert "missing required information" in result

    def test_get_user_error_unknown_code(self):
        """get_user_error returns fallback for unknown codes."""
        result = get_user_error("ERR-UNKNOWN-999")
        assert result == "An unexpected error occurred."

    def test_get_user_error_custom_fallback(self):
        """get_user_error uses custom fallback when provided."""
        result = get_user_error("ERR-UNKNOWN-999", fallback="Custom fallback")
        assert result == "Custom fallback"

    def test_all_error_codes_follow_naming_convention(self):
        """Error codes follow ERR-CATEGORY-NNN pattern."""
        pattern = re.compile(r"^ERR-[A-Z]+-\d{3}$")
        for code in ERROR_CATALOG:
            assert pattern.match(code), f"Error code '{code}' doesn't match ERR-CATEGORY-NNN pattern"


# ── Friendly Messages in Normal Pipeline Run ─────────────────────────────────

class TestFriendlyProgressMessages:
    """Verify pipeline emits user-friendly messages via progress callback."""

    def test_progress_callback_receives_user_messages(self, simple_brief):
        """Progress callback receives user_message for each event."""
        events = []

        def capture(**kwargs):
            events.append(kwargs)

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            run_pipeline(simple_brief, progress_cb=capture)

        assert len(events) > 0
        for event in events:
            assert "message" in event, "Event missing 'message' field"
            assert "user_message" in event, "Event missing 'user_message' field"

    def test_user_messages_are_friendly(self, simple_brief):
        """User messages use friendly language, not technical details."""
        events = []

        def capture(**kwargs):
            events.append(kwargs)

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            run_pipeline(simple_brief, progress_cb=capture)

        user_messages = [e["user_message"] for e in events]
        combined = " ".join(user_messages)

        # Should contain friendly language
        assert any("product" in m.lower() for m in user_messages)

        # Should NOT contain raw file paths
        assert "/Users/" not in combined
        assert "\\Users\\" not in combined

    def test_start_message_is_friendly(self, simple_brief):
        """First message uses friendly 'Starting your campaign' phrasing."""
        events = []

        def capture(**kwargs):
            events.append(kwargs)

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            run_pipeline(simple_brief, progress_cb=capture)

        first_user_msg = events[0]["user_message"]
        assert "Starting your campaign" in first_user_msg or "Starting pipeline" in first_user_msg

    def test_completion_message_is_friendly(self, simple_brief):
        """Final message uses friendly completion language."""
        events = []

        def capture(**kwargs):
            events.append(kwargs)

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            run_pipeline(simple_brief, progress_cb=capture)

        last_user_msg = events[-1]["user_message"]
        assert "done" in last_user_msg.lower() or "complete" in last_user_msg.lower()

    def test_backwards_compatible_with_old_callback(self, simple_brief):
        """Pipeline still works with old-style str-only progress callbacks."""
        messages = []

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            run_pipeline(simple_brief, progress_cb=messages.append)

        assert len(messages) > 0
        assert all(isinstance(m, str) for m in messages)


# ── Error Scenarios with Reference Codes ─────────────────────────────────────

class TestErrorReferenceCodesInSSE:
    """Verify error scenarios include reference codes in SSE payloads."""

    def test_invalid_brief_returns_friendly_error(self, client):
        """POST /api/run with invalid brief returns friendly error, not traceback."""
        r = client.post("/api/run", json={"campaign_id": "bad"})
        assert r.status_code == 422
        detail = r.json()["detail"]
        # Should contain friendly message, not raw Pydantic error
        assert "ERR-BRIEF-001" in detail or "required" in detail.lower()
        # Should NOT contain Pydantic technical details
        assert "validation error" not in detail.lower() or "field required" not in detail.lower()

    def test_error_events_include_error_code_field(self, simple_brief):
        """When errors occur, progress events include error_code field."""
        events = []

        def capture(**kwargs):
            events.append(kwargs)

        # Force a compose error by making compose_creative raise
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False), \
             patch("src.pipeline.compose_creative", side_effect=RuntimeError("test error")):
            result = run_pipeline(simple_brief, progress_cb=capture)

        # Should have some error events with error_code
        error_events = [e for e in events if e.get("error_code")]
        assert len(error_events) > 0
        assert any(e["error_code"] == "ERR-COMPOSE-001" for e in error_events)

    def test_error_user_message_is_friendly(self, simple_brief):
        """Error user_message comes from the catalog, not raw exception text."""
        events = []

        def capture(**kwargs):
            events.append(kwargs)

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False), \
             patch("src.pipeline.compose_creative", side_effect=RuntimeError("internal pillow segfault")):
            run_pipeline(simple_brief, progress_cb=capture)

        error_events = [e for e in events if e.get("error_code")]
        for event in error_events:
            # User message should be from catalog, not raw exception
            assert "internal pillow segfault" not in event["user_message"]
            assert "trouble creating" in event["user_message"] or "went wrong" in event["user_message"]


# ── No Technical Details Leaking to UI ───────────────────────────────────────

class TestNoTechnicalLeaks:
    """Verify technical details stay in server logs, not in SSE payloads."""

    def test_sse_payloads_no_tracebacks(self, client):
        """SSE progress payloads should never contain Python tracebacks."""
        brief_data = {
            "campaign_id": "leak_test",
            "brand_name": "LeakBrand",
            "target_region": "US",
            "target_audience": "Adults",
            "campaign_message": "Test",
            "products": [
                {"name": "LeakProd", "description": "Desc", "category": "skincare"}
            ],
        }
        r = client.post("/api/run", json=brief_data)
        assert r.status_code == 200

        # Parse all SSE events
        for line in r.text.strip().split("\n"):
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[6:])
            if payload["type"] == "progress":
                user_msg = payload.get("user_message", payload.get("message", ""))
                assert "Traceback" not in user_msg
                assert "File \"" not in user_msg
                assert "raise " not in user_msg

    def test_error_sse_no_exception_details(self, client):
        """When pipeline errors occur, SSE user_message hides exception details."""
        brief_data = {
            "campaign_id": "error_leak_test",
            "brand_name": "ErrorBrand",
            "target_region": "US",
            "target_audience": "Adults",
            "campaign_message": "Test",
            "products": [
                {"name": "ErrorProd", "description": "Desc", "category": "skincare"}
            ],
        }

        with patch("src.pipeline.compose_creative", side_effect=ValueError("secret internal detail xyz123")):
            r = client.post("/api/run", json=brief_data)

        assert r.status_code == 200

        for line in r.text.strip().split("\n"):
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[6:])
            if payload["type"] == "progress":
                user_msg = payload.get("user_message", "")
                # Raw exception text should NOT appear in user_message
                assert "secret internal detail xyz123" not in user_msg

    def test_sse_progress_includes_both_fields(self, client):
        """SSE progress events include both message and user_message fields."""
        brief_data = {
            "campaign_id": "fields_test",
            "brand_name": "FieldBrand",
            "target_region": "US",
            "target_audience": "Adults",
            "campaign_message": "Test",
            "products": [
                {"name": "FieldProd", "description": "Desc", "category": "skincare"}
            ],
        }
        r = client.post("/api/run", json=brief_data)

        progress_events = []
        for line in r.text.strip().split("\n"):
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[6:])
            if payload["type"] == "progress":
                progress_events.append(payload)

        assert len(progress_events) > 0
        for event in progress_events:
            assert "message" in event
            assert "user_message" in event


# ── Error Catalog Coverage ───────────────────────────────────────────────────

class TestErrorCatalogCoverage:
    """Verify the error catalog covers all error codes used in the codebase."""

    def test_all_pipeline_error_codes_in_catalog(self):
        """Every error code referenced in pipeline.py exists in ERROR_CATALOG."""
        pipeline_path = Path(__file__).parent.parent / "src" / "pipeline.py"
        source = pipeline_path.read_text()

        # Find all error code strings like ERR-SOMETHING-NNN
        codes_in_pipeline = set(re.findall(r'"(ERR-[A-Z]+-\d{3})"', source))

        for code in codes_in_pipeline:
            assert code in ERROR_CATALOG, (
                f"Error code {code} used in pipeline.py but not in ERROR_CATALOG"
            )

    def test_all_app_error_codes_in_catalog(self):
        """Every error code referenced in app.py exists in ERROR_CATALOG."""
        app_path = Path(__file__).parent.parent / "app.py"
        source = app_path.read_text()

        codes_in_app = set(re.findall(r'"(ERR-[A-Z]+-\d{3})"', source))

        for code in codes_in_app:
            assert code in ERROR_CATALOG, (
                f"Error code {code} used in app.py but not in ERROR_CATALOG"
            )

    def test_catalog_has_minimum_required_codes(self):
        """Catalog covers the minimum set of error scenarios from the story."""
        required_codes = [
            "ERR-BRIEF-001",
            "ERR-IMG-001",
            "ERR-COMPOSE-001",
            "ERR-REPORT-001",
            "ERR-CONFIG-001",
        ]
        for code in required_codes:
            assert code in ERROR_CATALOG, f"Required error code {code} missing from catalog"

    def test_ui_displays_user_message_field(self):
        """Static JS references user_message for display in the pipeline log."""
        static_dir = Path(__file__).parent.parent / "static"
        # Check app.js (JS extracted from inline index.html) then fall back to index.html
        app_js = static_dir / "js" / "app.js"
        source = app_js.read_text() if app_js.exists() else (static_dir / "index.html").read_text()
        assert "user_message" in source, "app.js should reference user_message for display"
        assert "error_code" in source, "app.js should reference error_code for badge display"
