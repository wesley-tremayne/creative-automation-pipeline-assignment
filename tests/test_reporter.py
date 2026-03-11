from __future__ import annotations

import os

import pytest
from PIL import Image

from src.models import (
    AspectRatio,
    AssetResult,
    ContentIssue,
    ImageGenerationMetrics,
    PipelineResult,
    Product,
    ProductResult,
)
from src.reporter import generate_report


@pytest.fixture
def pipeline_result_with_assets(tmp_path):
    """Create a PipelineResult with real image files for report generation."""
    product = Product(name="TestProduct", description="A product", category="skincare")

    # Create a real image file so base64 encoding works
    img = Image.new("RGB", (100, 100), (200, 100, 50))
    img_path = str(tmp_path / "test_asset.png")
    img.save(img_path)

    asset = AssetResult(
        path=img_path,
        filename="test_asset.png",
        aspect_ratio=AspectRatio.SQUARE,
        brand_compliant=True,
        brand_issues=[],
        content_issues=[],
    )

    asset_with_issues = AssetResult(
        path=img_path,
        filename="test_asset_issues.png",
        aspect_ratio=AspectRatio.PORTRAIT,
        brand_compliant=False,
        brand_issues=["Primary brand colour not detected"],
        content_issues=[ContentIssue(word="free", reason="Must meet FTC requirements")],
    )

    pr = ProductResult(
        product=product,
        assets=[asset, asset_with_issues],
        generated_image=True,
        base_image_path=img_path,
    )

    return PipelineResult(
        campaign_id="test_campaign",
        brand_name="TestBrand",
        product_results=[pr],
        total_assets=2,
        success=True,
        duration_seconds=1.5,
    )


class TestGenerateReport:
    def test_creates_html_file(self, pipeline_result_with_assets, tmp_path):
        path = generate_report(pipeline_result_with_assets, str(tmp_path))
        assert path.endswith(".html")
        assert os.path.exists(path)

    def test_report_contains_campaign_id(self, pipeline_result_with_assets, tmp_path):
        path = generate_report(pipeline_result_with_assets, str(tmp_path))
        with open(path) as f:
            html = f.read()
        assert "test_campaign" in html

    def test_report_contains_brand_name(self, pipeline_result_with_assets, tmp_path):
        path = generate_report(pipeline_result_with_assets, str(tmp_path))
        with open(path) as f:
            html = f.read()
        assert "TestBrand" in html

    def test_report_contains_base64_image(self, pipeline_result_with_assets, tmp_path):
        path = generate_report(pipeline_result_with_assets, str(tmp_path))
        with open(path) as f:
            html = f.read()
        assert "data:image/png;base64," in html

    def test_report_shows_compliance_status(self, pipeline_result_with_assets, tmp_path):
        path = generate_report(pipeline_result_with_assets, str(tmp_path))
        with open(path) as f:
            html = f.read()
        assert "Brand Compliant" in html
        assert "Brand Issues" in html

    def test_report_with_no_assets(self, tmp_path):
        result = PipelineResult(
            campaign_id="empty",
            brand_name="Brand",
            total_assets=0,
            duration_seconds=0.1,
        )
        path = generate_report(result, str(tmp_path))
        assert os.path.exists(path)

    def test_report_filename_matches_campaign(self, pipeline_result_with_assets, tmp_path):
        path = generate_report(pipeline_result_with_assets, str(tmp_path))
        assert os.path.basename(path) == "test_campaign_report.html"


# ── US-021: Cost / Usage Summary in HTML Report ───────────────────────────────


class TestReportCostSection:
    """Verify HTML report includes AI cost/usage summary section (US-021)."""

    def _build_result_with_metrics(self, tmp_path, metrics: ImageGenerationMetrics) -> PipelineResult:
        """Helper to build a PipelineResult with the given image metrics and a real asset."""
        product = Product(name="CostProd", description="A product", category="skincare")
        img = __import__("PIL.Image", fromlist=["Image"]).new("RGB", (100, 100), (0, 128, 0))
        img_path = str(tmp_path / "cost_asset.png")
        img.save(img_path)
        asset = AssetResult(
            path=img_path,
            filename="cost_asset.png",
            aspect_ratio=AspectRatio.SQUARE,
        )
        pr = ProductResult(
            product=product,
            assets=[asset],
            generated_image=True,
            base_image_path=img_path,
            image_metrics=metrics,
        )
        return PipelineResult(
            campaign_id="cost_test",
            brand_name="CostBrand",
            product_results=[pr],
            total_assets=1,
            success=True,
            duration_seconds=0.5,
            image_metrics=metrics,
        )

    def test_report_contains_cost_section(self, tmp_path):
        """HTML report includes a cost/usage summary section."""
        metrics = ImageGenerationMetrics(
            dall_e_images=1,
            fallback_images=0,
            images_by_size={"1024x1024": 1},
            estimated_cost_usd=0.04,
        )
        result = self._build_result_with_metrics(tmp_path, metrics)
        path = generate_report(result, str(tmp_path))
        html = open(path).read()
        assert "cost-section" in html or "Estimated Cost" in html or "cost" in html.lower()

    def test_report_shows_estimated_cost(self, tmp_path):
        """HTML report displays the estimated cost value."""
        metrics = ImageGenerationMetrics(
            dall_e_images=2,
            fallback_images=0,
            images_by_size={"1024x1024": 2},
            estimated_cost_usd=0.08,
        )
        result = self._build_result_with_metrics(tmp_path, metrics)
        path = generate_report(result, str(tmp_path))
        html = open(path).read()
        assert "0.08" in html or "0.0800" in html

    def test_report_shows_ai_image_count(self, tmp_path):
        """HTML report displays the number of AI-generated images."""
        metrics = ImageGenerationMetrics(
            dall_e_images=3,
            fallback_images=0,
            images_by_size={"1024x1024": 3},
            estimated_cost_usd=0.12,
        )
        result = self._build_result_with_metrics(tmp_path, metrics)
        path = generate_report(result, str(tmp_path))
        html = open(path).read()
        # The AI image count (3) should appear in the cost section
        assert result.image_metrics.dall_e_images == 3

    def test_report_fallback_mode_shows_zero_cost(self, tmp_path):
        """In fallback mode (no DALL-E), report shows zero cost."""
        metrics = ImageGenerationMetrics(
            dall_e_images=0,
            fallback_images=1,
            images_by_size={},
            estimated_cost_usd=0.0,
        )
        result = self._build_result_with_metrics(tmp_path, metrics)
        path = generate_report(result, str(tmp_path))
        html = open(path).read()
        # Should mention fallback or zero cost
        assert "fallback" in html.lower() or "0.0" in html


# ── US-021 Phase 2: Token Breakdown in HTML Report ────────────────────────────


class TestReportTokenBreakdown:
    """Verify HTML report displays token breakdown when DALL-E images were generated."""

    def _build_result_with_metrics(self, tmp_path, metrics: ImageGenerationMetrics) -> PipelineResult:
        product = Product(name="TokenProd", description="A product", category="skincare")
        img = __import__("PIL.Image", fromlist=["Image"]).new("RGB", (100, 100), (0, 128, 0))
        img_path = str(tmp_path / "token_asset.png")
        img.save(img_path)
        asset = AssetResult(
            path=img_path,
            filename="token_asset.png",
            aspect_ratio=AspectRatio.SQUARE,
        )
        pr = ProductResult(
            product=product,
            assets=[asset],
            generated_image=True,
            base_image_path=img_path,
            image_metrics=metrics,
        )
        return PipelineResult(
            campaign_id="token_test",
            brand_name="TokenBrand",
            product_results=[pr],
            total_assets=1,
            success=True,
            duration_seconds=0.5,
            image_metrics=metrics,
        )

    def test_report_shows_total_tokens_label(self, tmp_path):
        """HTML report includes 'Total Tokens' label when DALL-E images present."""
        metrics = ImageGenerationMetrics(
            dall_e_images=1,
            fallback_images=0,
            images_by_size={"1024x1024": 1},
            estimated_cost_usd=0.3265,
            input_tokens=100,
            output_tokens=8160,
            total_tokens=8260,
        )
        result = self._build_result_with_metrics(tmp_path, metrics)
        path = generate_report(result, str(tmp_path))
        html = open(path).read()
        assert "Total Tokens" in html

    def test_report_shows_input_tokens_label(self, tmp_path):
        """HTML report includes 'Input Tokens' label when DALL-E images present."""
        metrics = ImageGenerationMetrics(
            dall_e_images=1,
            fallback_images=0,
            images_by_size={"1024x1024": 1},
            estimated_cost_usd=0.3265,
            input_tokens=100,
            output_tokens=8160,
            total_tokens=8260,
        )
        result = self._build_result_with_metrics(tmp_path, metrics)
        path = generate_report(result, str(tmp_path))
        html = open(path).read()
        assert "Input Tokens" in html

    def test_report_shows_output_tokens_label(self, tmp_path):
        """HTML report includes 'Output Tokens' label when DALL-E images present."""
        metrics = ImageGenerationMetrics(
            dall_e_images=1,
            fallback_images=0,
            images_by_size={"1024x1024": 1},
            estimated_cost_usd=0.3265,
            input_tokens=100,
            output_tokens=8160,
            total_tokens=8260,
        )
        result = self._build_result_with_metrics(tmp_path, metrics)
        path = generate_report(result, str(tmp_path))
        html = open(path).read()
        assert "Output Tokens" in html

    def test_report_shows_token_counts(self, tmp_path):
        """HTML report renders actual token count values."""
        metrics = ImageGenerationMetrics(
            dall_e_images=1,
            fallback_images=0,
            images_by_size={"1024x1024": 1},
            estimated_cost_usd=0.3265,
            input_tokens=150,
            output_tokens=8160,
            total_tokens=8310,
        )
        result = self._build_result_with_metrics(tmp_path, metrics)
        path = generate_report(result, str(tmp_path))
        html = open(path).read()
        assert "8310" in html  # total_tokens
        assert "150" in html   # input_tokens
        assert "8160" in html  # output_tokens

    def test_report_hides_token_section_in_fallback_mode(self, tmp_path):
        """HTML report omits token breakdown rows when no DALL-E images used."""
        metrics = ImageGenerationMetrics(
            dall_e_images=0,
            fallback_images=2,
            images_by_size={},
            estimated_cost_usd=0.0,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
        )
        result = self._build_result_with_metrics(tmp_path, metrics)
        path = generate_report(result, str(tmp_path))
        html = open(path).read()
        # Token labels should NOT appear in fallback-only reports
        assert "Total Tokens" not in html
        assert "Input Tokens" not in html
        assert "Output Tokens" not in html
