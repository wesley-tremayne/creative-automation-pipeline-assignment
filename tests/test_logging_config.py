"""Tests for centralized logging configuration (src/logging_config.py)."""
from __future__ import annotations

import logging
import os
from unittest.mock import patch

from src.logging_config import setup_logging, log_timing


class TestSetupLogging:
    """Unit tests for setup_logging()."""

    def test_setup_logging_sets_info_level_by_default(self):
        """setup_logging() defaults to INFO level."""
        setup_logging("INFO")
        assert logging.getLogger().level == logging.INFO

    def test_setup_logging_sets_debug_level_when_requested(self):
        """setup_logging('DEBUG') sets root logger to DEBUG."""
        setup_logging("DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_setup_logging_case_insensitive(self):
        """setup_logging() accepts lowercase level strings."""
        setup_logging("warning")
        assert logging.getLogger().level == logging.WARNING

    def test_setup_logging_quietens_noisy_libs(self):
        """Third-party loggers are set to WARNING after setup."""
        setup_logging("DEBUG")
        for lib in ("urllib3", "httpcore", "httpx", "openai", "PIL"):
            assert logging.getLogger(lib).level == logging.WARNING, (
                f"{lib} logger should be at WARNING"
            )

    def test_setup_logging_adds_handler(self):
        """setup_logging() installs at least one handler on the root logger."""
        setup_logging("INFO")
        assert len(logging.getLogger().handlers) >= 1

    def test_setup_logging_is_idempotent(self):
        """Calling setup_logging() twice resets handlers, not accumulates them."""
        setup_logging("INFO")
        count_first = len(logging.getLogger().handlers)
        setup_logging("INFO")
        assert len(logging.getLogger().handlers) == count_first


class TestLogTiming:
    """Unit tests for log_timing() context manager."""

    def test_log_timing_yields_without_error(self, caplog):
        """log_timing does not raise on normal completion."""
        with caplog.at_level(logging.INFO):
            with log_timing("test_operation"):
                pass  # no exception

    def test_log_timing_logs_completion(self, caplog):
        """log_timing emits an INFO message containing the operation name."""
        with caplog.at_level(logging.INFO):
            with log_timing("my_operation"):
                pass
        assert any("my_operation" in r.message for r in caplog.records)

    def test_log_timing_uses_provided_logger(self, caplog):
        """log_timing uses the logger provided, not the default."""
        custom_logger = logging.getLogger("custom.test.logger")
        with caplog.at_level(logging.INFO, logger="custom.test.logger"):
            with log_timing("custom_op", logger=custom_logger):
                pass
        assert any("custom_op" in r.message for r in caplog.records)


class TestNoSecretsInLogs:
    """Verify that API keys do not appear in plain-text log output at DEBUG level."""

    def test_pipeline_does_not_log_api_key(self, caplog):
        """API key value must not appear verbatim in any log record."""
        fake_key = "sk-test-secret-key-should-not-appear-in-logs"

        setup_logging("DEBUG")

        from src.pipeline import run_pipeline
        from src.models import CampaignBrief, Product

        brief = CampaignBrief(
            campaign_id="secret_check",
            brand_name="Test",
            target_region="US",
            target_audience="All",
            campaign_message="Test",
            products=[Product(name="P", description="D", category="test")],
        )

        with patch.dict(os.environ, {"OPENAI_API_KEY": fake_key}):
            with caplog.at_level(logging.DEBUG):
                run_pipeline(brief)

        # The raw key value must not appear in any log message
        for record in caplog.records:
            assert fake_key not in record.getMessage(), (
                f"API key leaked in log record: {record.getMessage()}"
            )
