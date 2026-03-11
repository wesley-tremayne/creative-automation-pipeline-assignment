from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models import (
    AspectRatio,
    AssetResult,
    CampaignBrief,
    ContentIssue,
    ImageGenerationMetrics,
    PipelineResult,
    Product,
    ProductResult,
    RATIO_DIMENSIONS,
)


class TestProduct:
    def test_create_minimal(self):
        p = Product(name="Serum", description="A serum", category="skincare")
        assert p.name == "Serum"
        assert p.tagline is None
        assert p.existing_asset is None

    def test_create_full(self):
        p = Product(
            name="Serum",
            description="A serum",
            category="skincare",
            tagline="Glow up",
            existing_asset="serum.png",
        )
        assert p.tagline == "Glow up"
        assert p.existing_asset == "serum.png"


class TestCampaignBrief:
    def test_valid_brief(self, sample_brief):
        assert sample_brief.campaign_id == "test_campaign"
        assert len(sample_brief.products) == 2

    def test_defaults(self):
        brief = CampaignBrief(
            campaign_id="x",
            target_region="US",
            target_audience="all",
            campaign_message="msg",
            products=[Product(name="P", description="d", category="c")],
        )
        assert brief.cta == "Shop Now"
        assert brief.language == "en"
        assert brief.brand_name == "Brand"

    def test_empty_products_rejected(self):
        with pytest.raises(ValidationError):
            CampaignBrief(
                campaign_id="x",
                target_region="US",
                target_audience="all",
                campaign_message="msg",
                products=[],
            )


class TestAspectRatio:
    def test_all_ratios_have_dimensions(self):
        for ratio in AspectRatio:
            assert ratio in RATIO_DIMENSIONS

    def test_values(self):
        assert AspectRatio.SQUARE.value == "1x1"
        assert AspectRatio.PORTRAIT.value == "9x16"
        assert AspectRatio.LANDSCAPE.value == "16x9"


class TestPipelineResult:
    def test_defaults(self):
        r = PipelineResult(campaign_id="c", brand_name="b")
        assert r.success is True
        assert r.total_assets == 0
        assert r.errors == []

    def test_has_image_metrics(self):
        """PipelineResult includes image_metrics with default zeroed values."""
        r = PipelineResult(campaign_id="c", brand_name="b")
        assert r.image_metrics.dall_e_images == 0
        assert r.image_metrics.fallback_images == 0
        assert r.image_metrics.estimated_cost_usd == 0.0
        assert r.image_metrics.images_by_size == {}


# ── US-021: ImageGenerationMetrics model tests ────────────────────────────────


class TestImageGenerationMetrics:
    """Verify ImageGenerationMetrics Pydantic model serializes correctly."""

    def test_defaults(self):
        m = ImageGenerationMetrics()
        assert m.dall_e_images == 0
        assert m.fallback_images == 0
        assert m.estimated_cost_usd == 0.0
        assert m.images_by_size == {}
        # Phase 2: token fields default to zero
        assert m.input_tokens == 0
        assert m.output_tokens == 0
        assert m.total_tokens == 0

    def test_serialization(self):
        """Model serializes to dict correctly for JSON manifest output."""
        m = ImageGenerationMetrics(
            dall_e_images=2,
            fallback_images=1,
            images_by_size={"1024x1024": 2},
            estimated_cost_usd=0.08,
            input_tokens=300,
            output_tokens=16320,
            total_tokens=16620,
        )
        d = m.model_dump()
        assert d["dall_e_images"] == 2
        assert d["fallback_images"] == 1
        assert d["estimated_cost_usd"] == 0.08
        assert d["images_by_size"] == {"1024x1024": 2}
        assert d["input_tokens"] == 300
        assert d["output_tokens"] == 16320
        assert d["total_tokens"] == 16620

    def test_product_result_has_image_metrics(self):
        """ProductResult includes per-product image_metrics."""
        pr = ProductResult(product=Product(name="P", description="d", category="c"))
        assert pr.image_metrics.dall_e_images == 0
        assert pr.image_metrics.fallback_images == 0

    def test_pipeline_result_serializes_image_metrics(self):
        """PipelineResult.model_dump() includes image_metrics for manifest JSON."""
        r = PipelineResult(
            campaign_id="c",
            brand_name="b",
            image_metrics=ImageGenerationMetrics(
                dall_e_images=1,
                fallback_images=2,
                estimated_cost_usd=0.04,
                images_by_size={"1024x1024": 1},
            ),
        )
        d = r.model_dump()
        assert "image_metrics" in d
        assert d["image_metrics"]["dall_e_images"] == 1
        assert d["image_metrics"]["fallback_images"] == 2
        assert d["image_metrics"]["estimated_cost_usd"] == 0.04
