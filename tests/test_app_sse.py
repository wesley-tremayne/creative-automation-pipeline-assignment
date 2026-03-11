"""Tests for app.py SSE stream error handling (run_in_thread try/except)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _minimal_brief() -> dict:
    return {
        "campaign_id": "test_sse",
        "brand_name": "TestBrand",
        "target_region": "US",
        "target_audience": "Adults 25-45",
        "campaign_message": "Test message",
        "products": [
            {"name": "Prod A", "description": "Desc A", "category": "skincare"}
        ],
    }


class TestRunInThreadErrorHandling:
    """Verify that pipeline exceptions are surfaced as error SSE events."""

    def test_pipeline_exception_emits_error_event(self, client):
        """When run_pipeline raises, an error SSE event is emitted and stream closes."""
        error_msg = "Azure connection string is malformed."
        with patch("app.run_pipeline", side_effect=ValueError(error_msg)):
            response = client.post("/api/run", json=_minimal_brief())

        assert response.status_code == 200

        # Parse SSE lines
        events = []
        for line in response.text.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))

        error_events = [e for e in events if e.get("type") == "error"]
        assert error_events, "Expected at least one error SSE event"
        assert error_msg in error_events[0]["message"]

    def test_pipeline_exception_stream_closes_cleanly(self, client):
        """When run_pipeline raises, the SSE stream terminates (sentinel is sent)."""
        with patch("app.run_pipeline", side_effect=RuntimeError("Storage failure")):
            response = client.post("/api/run", json=_minimal_brief())

        # If the stream hangs, TestClient would time out. Reaching here means it closed.
        assert response.status_code == 200
        assert "data:" in response.text

    def test_pipeline_success_emits_result_not_error(self, client):
        """When run_pipeline succeeds, a result event is emitted without an error event."""
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {
            "success": True,
            "total_assets": 3,
            "report_path": None,
            "assets": [],
            "compliance_issues": [],
        }

        with patch("app.run_pipeline", return_value=mock_result):
            response = client.post("/api/run", json=_minimal_brief())

        assert response.status_code == 200

        events = []
        for line in response.text.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))

        result_events = [e for e in events if e.get("type") == "result"]
        error_events = [e for e in events if e.get("type") == "error"]
        assert result_events, "Expected a result event on success"
        assert not error_events, "No error event expected on success"
