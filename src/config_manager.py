"""
Config Manager
--------------
Validates and loads brand guidelines and prohibited words configurations.
Pure validation logic — no HTTP dependencies.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"

VALID_LOGO_PLACEMENTS = ("bottom-right", "bottom-left", "top-right", "top-left")

_BRAND_GUIDELINES_REQUIRED_STRINGS = ("brand_name", "font_family", "logo_placement")
_BRAND_GUIDELINES_COLOR_FIELDS = (
    "primary_color",
    "secondary_color",
    "text_color",
    "accent_color",
)


def validate_rgb_color(value: object, field_name: str) -> list[str]:
    """Validate that a value is an [R, G, B] array with values 0-255."""
    errors: list[str] = []
    if not isinstance(value, list) or len(value) != 3:
        errors.append(f"{field_name} must be an [R, G, B] array of 3 integers")
        return errors
    for i, v in enumerate(value):
        if not isinstance(v, int) or v < 0 or v > 255:
            errors.append(
                f"{field_name}[{i}] must be an integer between 0 and 255, got {v!r}"
            )
    return errors


def validate_brand_guidelines(data: dict) -> list[str]:
    """Validate brand guidelines structure. Returns a list of error messages (empty = valid)."""
    errors: list[str] = []

    for field in _BRAND_GUIDELINES_REQUIRED_STRINGS:
        if field not in data or not isinstance(data[field], str) or not data[field].strip():
            errors.append(f"Missing or invalid required string field: {field}")

    for color_field in _BRAND_GUIDELINES_COLOR_FIELDS:
        if color_field not in data:
            errors.append(f"Missing color field: {color_field}")
        else:
            errors.extend(validate_rgb_color(data[color_field], color_field))

    placement = data.get("logo_placement")
    if isinstance(placement, str) and placement not in VALID_LOGO_PLACEMENTS:
        errors.append(
            f"logo_placement must be one of {VALID_LOGO_PLACEMENTS}, got '{placement}'"
        )

    szp = data.get("safe_zone_percent")
    if szp is not None and (not isinstance(szp, (int, float)) or szp < 0 or szp > 50):
        errors.append("safe_zone_percent must be a number between 0 and 50")

    return errors


def validate_prohibited_words(data: dict) -> list[str]:
    """Validate prohibited words structure. Returns a list of error messages (empty = valid)."""
    errors: list[str] = []

    for key in ("prohibited", "requires_disclaimer"):
        items = data.get(key)
        if not isinstance(items, list):
            errors.append(f"'{key}' must be a list")
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"'{key}[{i}]' must be an object with 'word' and 'reason'")
            elif "word" not in item or "reason" not in item:
                errors.append(f"'{key}[{i}]' missing required 'word' or 'reason' field")

    sups = data.get("superlatives")
    if not isinstance(sups, list):
        errors.append("'superlatives' must be a list of strings")
    elif not all(isinstance(s, str) for s in sups):
        errors.append("All entries in 'superlatives' must be strings")

    return errors


def load_config(
    config_type: str,
    profile: Optional[str] = None,
    storage: Optional[object] = None,
) -> dict:
    """Load a config file by type and optional profile name.

    When a storage backend is provided and a profile is requested, checks the
    storage backend first (Azure), then falls back to the local filesystem.
    Default (unnamed) configs are always loaded from the local filesystem.

    Args:
        config_type: Config type key, e.g. 'brand_guidelines' or 'prohibited_words'.
        profile: Optional profile name. When None, loads the default config.
        storage: Optional StorageBackend instance. Used for Azure-first lookup of profiles.

    Returns:
        Parsed config dict.

    Raises:
        FileNotFoundError: If the config file is not found in storage or locally.
    """
    filename = f"{config_type}_{profile}.json" if profile else f"{config_type}.json"

    # For named profiles when a storage backend is provided, try storage first
    if profile and storage is not None:
        blob_path = f"config/{filename}"
        try:
            data = storage.get_file(blob_path)  # type: ignore[attr-defined]
            return json.loads(data)
        except FileNotFoundError:
            pass  # fall through to local filesystem

    # Default configs and local fallback
    path = CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {filename}")
    with open(path) as f:
        return json.load(f)
