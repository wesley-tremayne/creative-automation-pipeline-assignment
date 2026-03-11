"""
Error Catalog
--------------
Maps error reference codes to user-friendly messages and admin context.
UI displays the user_message; technical details stay in server logs.
"""

from __future__ import annotations

ERROR_CATALOG: dict[str, dict[str, str]] = {
    "ERR-BRIEF-001": {
        "user_message": (
            "Your campaign brief is missing required information. "
            "Please check all required fields are filled in."
        ),
        "admin_context": "CampaignBrief Pydantic validation failed",
    },
    "ERR-IMG-001": {
        "user_message": (
            "We couldn't generate an image for this product. "
            "The pipeline will continue with remaining products."
        ),
        "admin_context": "Image generation failed (DALL-E or gradient fallback)",
    },
    "ERR-COMPOSE-001": {
        "user_message": (
            "We had trouble creating one of the ad formats. "
            "Other formats may still be available."
        ),
        "admin_context": "Image composition (Pillow) failed for a specific aspect ratio",
    },
    "ERR-REPORT-001": {
        "user_message": (
            "The summary report couldn't be generated, but your ad images "
            "were created successfully."
        ),
        "admin_context": "Jinja2 report generation failed",
    },
    "ERR-CONFIG-001": {
        "user_message": (
            "There's a configuration issue. Please contact your system "
            "administrator. Reference: ERR-CONFIG-001"
        ),
        "admin_context": "brand_guidelines.json or prohibited_words.json parse failure",
    },
    "ERR-PRODUCT-001": {
        "user_message": (
            "Something went wrong while processing one of your products. "
            "The pipeline will continue with remaining products."
        ),
        "admin_context": "Unhandled exception during product processing",
    },
    "ERR-MANIFEST-001": {
        "user_message": (
            "Campaign data was saved, but the summary file couldn't be written."
        ),
        "admin_context": "Failed to write campaign_manifest.json",
    },
}


def get_user_error(code: str, fallback: str = "An unexpected error occurred.") -> str:
    """Look up a user-friendly message by error code, with fallback."""
    entry = ERROR_CATALOG.get(code)
    if entry:
        return f"{entry['user_message']} (Reference: {code})"
    return fallback
