"""
Data models for the Creative Automation Pipeline.

Defines all Pydantic models used as inputs and outputs throughout the system:
  - CampaignBrief / Product  — pipeline inputs parsed from YAML/JSON briefs
  - AspectRatio              — supported ad format enum
  - AssetResult              — a single generated creative with compliance data
  - ProductResult            — all assets for one product in a campaign
  - PipelineResult           — full pipeline output returned to callers
"""
from __future__ import annotations

import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class AspectRatio(str, Enum):
    """Supported ad creative aspect ratios, matching social platform requirements."""

    SQUARE = "1x1"
    PORTRAIT = "9x16"
    LANDSCAPE = "16x9"


RATIO_DIMENSIONS: dict[AspectRatio, tuple[int, int]] = {
    AspectRatio.SQUARE: (1080, 1080),
    AspectRatio.PORTRAIT: (1080, 1920),
    AspectRatio.LANDSCAPE: (1920, 1080),
}

DALLE_SIZES: dict[AspectRatio, str] = {
    AspectRatio.SQUARE: "1024x1024",
    AspectRatio.PORTRAIT: "1024x1792",
    AspectRatio.LANDSCAPE: "1792x1024",
}

RATIO_LABELS: dict[AspectRatio, str] = {
    AspectRatio.SQUARE: "Square (1:1) — Instagram / Facebook Feed",
    AspectRatio.PORTRAIT: "Portrait (9:16) — Stories / Reels / TikTok",
    AspectRatio.LANDSCAPE: "Landscape (16:9) — YouTube / Twitter / Banner",
}


class Product(BaseModel):
    """A single product included in a campaign brief."""

    name: str
    description: str
    category: str
    tagline: Optional[str] = None
    existing_asset: Optional[str] = None  # relative path inside assets/source_images/

    @field_validator("existing_asset")
    @classmethod
    def reject_path_traversal(cls, v: Optional[str]) -> Optional[str]:
        """Reject path traversal characters in existing_asset."""
        if v is None:
            return v
        if ".." in v or v.startswith("/") or "\\" in v or "\x00" in v:
            raise ValueError(
                "existing_asset must not contain path traversal characters ('..', '/', '\\', null bytes)"
            )
        return v


_SAFE_CAMPAIGN_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


class CampaignBrief(BaseModel):
    """A campaign brief defining all parameters for creative generation."""

    campaign_id: str

    @field_validator("campaign_id")
    @classmethod
    def validate_campaign_id(cls, v: str) -> str:
        """Reject dangerous characters in campaign_id."""
        if not _SAFE_CAMPAIGN_ID_RE.match(v):
            raise ValueError(
                "campaign_id may only contain letters, numbers, underscores, and hyphens"
            )
        return v
    products: List[Product] = Field(min_length=1)
    target_region: str
    target_market: Optional[str] = None
    target_audience: str
    campaign_message: str
    offer: Optional[str] = None
    cta: str = "Shop Now"
    language: str = "en"
    tone: str = "professional, aspirational"
    brand_name: str = "Brand"
    website: Optional[str] = None
    logo: Optional[str] = None  # filename in assets/logos/, "generate", or None (no logo)
    brand_config: Optional[str] = None  # brand guidelines profile name, None = default
    content_config: Optional[str] = None  # prohibited words profile name, None = default


class ImageGenerationMetrics(BaseModel):
    """Tracks AI image generation usage, token consumption, and estimated cost."""

    dall_e_images: int = 0
    fallback_images: int = 0
    images_by_size: dict[str, int] = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class ContentIssue(BaseModel):
    """A single content compliance flag found during the content check."""

    word: str
    reason: str


class AssetResult(BaseModel):
    """A single generated ad creative with its compliance results."""

    path: str
    aspect_ratio: AspectRatio
    filename: str
    brand_compliant: bool = True
    brand_issues: List[str] = []
    content_issues: List[ContentIssue] = []


class ProductResult(BaseModel):
    """All generated assets for a single product within a campaign."""

    product: Product
    assets: List[AssetResult] = []
    generated_image: bool = False
    base_image_path: Optional[str] = None
    error: Optional[str] = None
    image_metrics: ImageGenerationMetrics = Field(default_factory=ImageGenerationMetrics)


class PipelineResult(BaseModel):
    """The complete result of a pipeline run, returned to CLI and web callers."""

    campaign_id: str
    brand_name: str
    product_results: List[ProductResult] = []
    report_path: Optional[str] = None
    total_assets: int = 0
    success: bool = True
    errors: List[str] = []
    duration_seconds: float = 0.0
    image_metrics: ImageGenerationMetrics = Field(default_factory=ImageGenerationMetrics)
