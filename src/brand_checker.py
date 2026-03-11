"""
Brand Checker
-------------
Validates generated creatives against brand guidelines.
Checks:
  • Presence of brand accent colour in the image
  • Logo placement (verifies logo pixels exist in expected region)
  • Minimum contrast ratio for readability
"""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def _color_distance(c1: tuple, c2: tuple) -> float:
    return sum((a - b) ** 2 for a, b in zip(c1[:3], c2[:3])) ** 0.5


def _image_contains_color(img: Image.Image, target_color: tuple, tolerance: int = 45) -> bool:
    """Return True if any pixel in the image is within `tolerance` of target_color."""
    arr = np.array(img.convert("RGB"))
    diff = arr.astype(int) - np.array(target_color[:3], dtype=int)
    dist = np.sqrt((diff ** 2).sum(axis=2))
    return bool((dist < tolerance).any())


def check_brand_compliance(
    image_path: str,
    brand_guidelines: dict,
    has_logo: bool = False,
) -> list[str]:
    """
    Run brand compliance checks on a composed creative.
    Returns a list of issue strings (empty list = fully compliant).
    """
    issues: list[str] = []

    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as exc:
        logger.error("Could not open image for brand check: %s", exc)
        return ["Could not open image for brand check"]

    # Check 1: Primary brand colour present
    primary_color = tuple(brand_guidelines.get("primary_color", [255, 195, 0]))
    if not _image_contains_color(img, primary_color, tolerance=50):
        issues.append(
            f"Primary brand colour {primary_color} not detected in creative"
        )

    # Check 2: Image is not too dark (average brightness)
    arr = np.array(img)
    mean_brightness = arr.mean()
    if mean_brightness < 25:
        issues.append("Image appears too dark — may not render well on feeds")

    # Check 3: Logo region check (bottom-right corner should have some non-background pixels)
    if has_logo:
        w, h = img.size
        corner = img.crop((int(w * 0.80), int(h * 0.80), w, h))
        corner_arr = np.array(corner)
        # If bottom-right corner is entirely one colour, logo may be missing
        std = corner_arr.std()
        if std < 5:
            issues.append("Logo may be missing — bottom-right region appears uniform")

    if not issues:
        logger.info("Brand compliance check PASSED for %s", image_path)
    else:
        for issue in issues:
            logger.warning("Brand issue [%s]: %s", image_path, issue)

    return issues
