"""
Centralized logging configuration for the Creative Automation Pipeline.

Call `setup_logging()` once at application startup (in app.py or run_pipeline.py).
All modules use `logging.getLogger(__name__)` — the configuration here controls
format, level, and handlers globally.

Log level guidance:
  DEBUG    — Detailed diagnostic (file paths, pixel values, intermediate state)
  INFO     — Stage starts/completions, config loaded, server started
  WARNING  — Fallback triggered (no API key), non-fatal issues
  ERROR    — Stage failure that is caught and recovered from
  CRITICAL — Application cannot start (missing required config)
"""
from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from typing import Generator


def setup_logging(level: str = "INFO") -> None:
    """Configure application-wide logging.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               Defaults to INFO. Controlled by LOG_LEVEL env var.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Clear any existing handlers (prevents duplicate output on reload)
    root = logging.getLogger()
    root.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)

    root.setLevel(log_level)
    root.addHandler(console_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


@contextmanager
def log_timing(operation: str, logger: logging.Logger | None = None) -> Generator[None, None, None]:
    """Context manager that logs elapsed time for an operation.

    Args:
        operation: Human-readable name for the timed operation.
        logger: Logger to use. Defaults to the module logger.
    """
    _logger = logger or logging.getLogger(__name__)
    _logger.debug("Starting: %s", operation)
    start = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start
        _logger.info("%s completed in %.2fs", operation, elapsed)
