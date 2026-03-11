"""
Content Checker
---------------
Scans campaign text (brief messages, offers, CTAs) for:
  • Prohibited / legally risky words
  • Superlative claims that may require substantiation
  • Missing legal disclaimers for regulated categories
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from .models import CampaignBrief, ContentIssue

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"
CONFIG_PATH = CONFIG_DIR / "prohibited_words.json"


def _load_prohibited_words(config_name: Optional[str] = None) -> dict:
    """Load prohibited words config.

    If config_name is given, loads config/prohibited_words_{config_name}.json.
    Otherwise loads the default config/prohibited_words.json.
    """
    if config_name:
        path = CONFIG_DIR / f"prohibited_words_{config_name}.json"
    else:
        path = CONFIG_PATH
    if path.exists():
        with open(path) as f:
            return json.load(f)
    logger.warning("%s not found, using empty list", path.name)
    return {"prohibited": [], "requires_disclaimer": [], "superlatives": []}


def check_content(brief: CampaignBrief, config_name: Optional[str] = None) -> list[ContentIssue]:
    """
    Scan all text fields in the brief for content issues.
    Returns a list of ContentIssue objects.
    """
    config = _load_prohibited_words(config_name)
    issues: list[ContentIssue] = []

    texts_to_check = [
        brief.campaign_message,
        brief.offer or "",
        brief.cta,
    ]
    # Also check all product descriptions
    for product in brief.products:
        texts_to_check.extend([product.name, product.description, product.tagline or ""])

    combined_text = " ".join(texts_to_check).lower()

    # 1. Hard-prohibited words
    for entry in config.get("prohibited", []):
        word = entry["word"].lower()
        if re.search(rf"\b{re.escape(word)}\b", combined_text):
            issues.append(ContentIssue(word=entry["word"], reason=entry["reason"]))

    # 2. Words requiring disclaimers
    for entry in config.get("requires_disclaimer", []):
        word = entry["word"].lower()
        if re.search(rf"\b{re.escape(word)}\b", combined_text):
            issues.append(
                ContentIssue(
                    word=entry["word"],
                    reason=f"⚠ Requires legal disclaimer: {entry['reason']}",
                )
            )

    # 3. Unsubstantiated superlatives
    for word in config.get("superlatives", []):
        if re.search(rf"\b{re.escape(word.lower())}\b", combined_text):
            issues.append(
                ContentIssue(
                    word=word,
                    reason="Unsubstantiated superlative — may require claim support or footnote",
                )
            )

    if issues:
        for issue in issues:
            logger.warning("Content issue — '%s': %s", issue.word, issue.reason)
    else:
        logger.info("Content check PASSED — no prohibited words found")

    return issues
