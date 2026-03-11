from __future__ import annotations

import ast
import json
import os
from unittest.mock import patch, MagicMock

import pytest

from src.pipeline import load_brief, run_pipeline
from src.models import AspectRatio, CampaignBrief, Product


class TestFutureAnnotations:
    """Regression tests for US-005: all source files must have future annotations."""

    SOURCE_FILES = [
        "run_pipeline.py",
        "app.py",
        "src/pipeline.py",
        "src/models.py",
        "src/image_generator.py",
        "src/image_composer.py",
        "src/brand_checker.py",
        "src/content_checker.py",
        "src/reporter.py",
    ]

    @pytest.mark.parametrize("filepath", SOURCE_FILES)
    def test_file_has_future_annotations(self, filepath):
        """Every source file using modern type syntax must import future annotations."""
        from pathlib import Path

        root = Path(__file__).parent.parent
        full = root / filepath
        if not full.exists():
            pytest.skip(f"{filepath} does not exist")
        source = full.read_text()
        tree = ast.parse(source)
        future_imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "__future__"
        ]
        has_annotations = any(
            alias.name == "annotations"
            for imp in future_imports
            for alias in imp.names
        )
        assert has_annotations, f"{filepath} is missing 'from __future__ import annotations'"

    @pytest.mark.parametrize("filepath", SOURCE_FILES)
    def test_file_parses_on_python39(self, filepath):
        """All source files must parse as valid Python."""
        from pathlib import Path

        root = Path(__file__).parent.parent
        full = root / filepath
        if not full.exists():
            pytest.skip(f"{filepath} does not exist")
        source = full.read_text()
        # This will raise SyntaxError on genuinely invalid syntax
        ast.parse(source)


class TestLoadBrief:
    def test_load_yaml(self, brief_yaml_file):
        brief = load_brief(brief_yaml_file)
        assert brief.campaign_id == "test_campaign"
        assert brief.brand_name == "TestBrand"
        assert len(brief.products) == 2

    def test_load_json(self, brief_json_file):
        brief = load_brief(brief_json_file)
        assert brief.campaign_id == "json_campaign"
        assert len(brief.products) == 1

    def test_load_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_brief("/nonexistent/brief.yaml")


class TestPipelineIntegration:
    """End-to-end pipeline smoke tests using gradient fallback (no API key)."""

    @pytest.fixture
    def integration_brief(self):
        return CampaignBrief(
            campaign_id="integration_test",
            brand_name="TestBrand",
            target_region="US",
            target_audience="Adults 25-45",
            campaign_message="Test campaign message",
            offer="10% OFF",
            cta="Buy Now",
            products=[
                Product(name="TestProduct", description="A test product", category="skincare"),
            ],
        )

    def test_pipeline_end_to_end(self, integration_brief):
        """Full pipeline produces expected outputs with gradient fallback."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = run_pipeline(integration_brief)

        assert result.success
        assert result.campaign_id == "integration_test"
        assert result.total_assets == 3  # 1 product × 3 ratios
        assert len(result.product_results) == 1
        assert result.duration_seconds > 0

        pr = result.product_results[0]
        assert pr.generated_image is True
        assert len(pr.assets) == 3

        # Verify all 3 aspect ratios are present
        ratios = {a.aspect_ratio for a in pr.assets}
        assert ratios == {AspectRatio.SQUARE, AspectRatio.PORTRAIT, AspectRatio.LANDSCAPE}

        # Verify output files exist
        for asset in pr.assets:
            assert os.path.exists(asset.path)

    def test_pipeline_generates_report(self, integration_brief):
        """Pipeline should generate an HTML report."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = run_pipeline(integration_brief)

        assert result.report_path
        assert os.path.exists(result.report_path)
        assert result.report_path.endswith(".html")

    def test_pipeline_with_multiple_products(self):
        """Pipeline handles multiple products correctly."""
        brief = CampaignBrief(
            campaign_id="multi_product_test",
            brand_name="TestBrand",
            target_region="US",
            target_audience="All",
            campaign_message="Multi product test",
            products=[
                Product(name="Product A", description="Desc A", category="skincare"),
                Product(name="Product B", description="Desc B", category="beverage"),
            ],
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = run_pipeline(brief)

        assert result.success
        assert result.total_assets == 6  # 2 products × 3 ratios
        assert len(result.product_results) == 2

    def test_pipeline_progress_callback(self, integration_brief):
        """Progress callback should be called during pipeline execution."""
        messages = []
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            run_pipeline(integration_brief, progress_cb=messages.append)
        assert len(messages) > 0
        assert any("Starting pipeline" in m for m in messages)


# ── US-021: Cost & Image Metrics Tests ───────────────────────────────────────


class TestImageGenerationMetricsPipeline:
    """Verify pipeline correctly tracks DALL-E usage and cost metrics (US-021)."""

    @pytest.fixture
    def single_product_brief(self):
        return CampaignBrief(
            campaign_id="metrics_test",
            brand_name="MetricsBrand",
            target_region="US",
            target_audience="Adults 25-45",
            campaign_message="Metrics test campaign",
            products=[
                Product(name="MetricsProd", description="A test product", category="skincare"),
            ],
        )

    @pytest.fixture
    def two_product_brief(self):
        return CampaignBrief(
            campaign_id="metrics_multi_test",
            brand_name="MetricsBrand",
            target_region="US",
            target_audience="Adults 25-45",
            campaign_message="Multi-product metrics test",
            products=[
                Product(name="ProdA", description="Desc A", category="skincare"),
                Product(name="ProdB", description="Desc B", category="beverage"),
            ],
        )

    def test_fallback_mode_zero_cost(self, single_product_brief):
        """Fallback mode (no API key) produces zero cost and correct fallback count."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = run_pipeline(single_product_brief)

        assert result.success
        assert result.image_metrics.dall_e_images == 0
        assert result.image_metrics.fallback_images == 1
        assert result.image_metrics.estimated_cost_usd == 0.0
        assert result.image_metrics.images_by_size == {}

    def test_fallback_mode_per_product_metrics(self, two_product_brief):
        """Each product has its own fallback metrics; campaign total sums correctly."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = run_pipeline(two_product_brief)

        assert result.success
        assert result.image_metrics.dall_e_images == 0
        assert result.image_metrics.fallback_images == 2
        assert result.image_metrics.estimated_cost_usd == 0.0

        for pr in result.product_results:
            assert pr.image_metrics.fallback_images == 1
            assert pr.image_metrics.dall_e_images == 0

    def _make_mock_openai(self, input_tokens: int = 150, output_tokens: int = 8160):
        """Return a started patcher that mocks with_raw_response.generate() with usage data."""
        import base64
        from io import BytesIO
        from PIL import Image as PILImage

        fake_img = PILImage.new("RGB", (100, 100), (0, 128, 255))
        buf = BytesIO()
        fake_img.save(buf, format="PNG")
        fake_b64 = base64.b64encode(buf.getvalue()).decode()

        # Parsed response returned by raw_response.parse()
        parsed_resp = MagicMock()
        parsed_resp.data = [MagicMock(b64_json=fake_b64)]

        # Raw response with usage in the JSON body
        raw_resp = MagicMock()
        raw_resp.parse.return_value = parsed_resp
        raw_resp.text = json.dumps({
            "created": 1234567890,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        })

        patcher = patch("openai.OpenAI")
        mock_cls = patcher.start()
        mock_cls.return_value.images.with_raw_response.generate.return_value = raw_resp
        return patcher

    def test_mocked_dalle_metrics_accurate(self, single_product_brief):
        """Mocked DALL-E success populates dall_e_images, tokens, and cost correctly."""
        input_tok, output_tok = 150, 8160
        patcher = self._make_mock_openai(input_tok, output_tok)
        try:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
                result = run_pipeline(single_product_brief)
        finally:
            patcher.stop()

        assert result.success
        assert result.image_metrics.dall_e_images == 1
        assert result.image_metrics.fallback_images == 0
        assert result.image_metrics.input_tokens == input_tok
        assert result.image_metrics.output_tokens == output_tok
        assert result.image_metrics.total_tokens == input_tok + output_tok
        # Token-based cost: (150×5 + 8160×40) / 1_000_000
        expected_cost = (input_tok * 5 + output_tok * 40) / 1_000_000
        assert abs(result.image_metrics.estimated_cost_usd - expected_cost) < 1e-6
        assert len(result.image_metrics.images_by_size) > 0

    def test_circuit_breaker_mixed_mode_metrics(self, two_product_brief):
        """After API failure, second product uses fallback; per-product metrics are accurate."""
        mock_client = patch("openai.OpenAI").start()
        mock_client.return_value.images.with_raw_response.generate.side_effect = Exception("billing error")

        try:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
                result = run_pipeline(two_product_brief)
        finally:
            patch.stopall()

        assert result.success
        # API failed for both (circuit breaker trips after first failure)
        assert result.image_metrics.dall_e_images == 0
        assert result.image_metrics.fallback_images == 2
        assert result.image_metrics.estimated_cost_usd == 0.0

    def test_manifest_includes_image_metrics(self, single_product_brief, outputs_root):
        """Campaign manifest JSON includes image_metrics for audit trail."""
        import json

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = run_pipeline(single_product_brief)

        assert result.success
        # Find the manifest JSON in outputs
        manifests = list(outputs_root.glob("**/*manifest.json"))
        assert len(manifests) == 1, "Expected exactly one manifest.json"

        data = json.loads(manifests[0].read_text())
        assert "image_metrics" in data
        assert "dall_e_images" in data["image_metrics"]
        assert "fallback_images" in data["image_metrics"]
        assert "estimated_cost_usd" in data["image_metrics"]
        assert data["image_metrics"]["fallback_images"] == 1
        assert data["image_metrics"]["estimated_cost_usd"] == 0.0

    def test_fallback_cost_message_not_emitted(self, single_product_brief):
        """In fallback mode, no per-image cost message is emitted (cost is $0)."""
        messages = []
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            run_pipeline(single_product_brief, progress_cb=messages.append)

        cost_messages = [m for m in messages if "💰" in m]
        assert len(cost_messages) == 0, "No cost messages expected in fallback mode"

    def test_fallback_mode_zero_tokens(self, single_product_brief):
        """Fallback mode produces zero token counts in all metrics fields."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = run_pipeline(single_product_brief)

        assert result.image_metrics.input_tokens == 0
        assert result.image_metrics.output_tokens == 0
        assert result.image_metrics.total_tokens == 0
        assert result.image_metrics.estimated_cost_usd == 0.0

    def test_token_accumulation_multi_product(self, two_product_brief):
        """Campaign-level tokens are the sum of per-product tokens."""
        in_tok, out_tok = 200, 8160
        patcher = self._make_mock_openai(in_tok, out_tok)
        try:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
                result = run_pipeline(two_product_brief)
        finally:
            patcher.stop()

        assert result.success
        # Both products used DALL-E with same token counts
        assert result.image_metrics.dall_e_images == 2
        assert result.image_metrics.input_tokens == in_tok * 2
        assert result.image_metrics.output_tokens == out_tok * 2
        assert result.image_metrics.total_tokens == (in_tok + out_tok) * 2
        expected_cost = ((in_tok * 5 + out_tok * 40) / 1_000_000) * 2
        assert abs(result.image_metrics.estimated_cost_usd - expected_cost) < 1e-6

    def test_progress_message_includes_token_count(self, single_product_brief):
        """Progress callback includes token count in the cost message for DALL-E images."""
        patcher = self._make_mock_openai(input_tokens=120, output_tokens=8160)
        messages = []
        try:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
                run_pipeline(single_product_brief, progress_cb=messages.append)
        finally:
            patcher.stop()

        cost_messages = [m for m in messages if "💰" in m]
        assert len(cost_messages) > 0
        # Message should reference tokens
        assert any("token" in m.lower() for m in cost_messages)

    def test_manifest_includes_token_counts(self, single_product_brief, outputs_root):
        """Campaign manifest JSON contains input_tokens, output_tokens, total_tokens."""
        import json

        in_tok, out_tok = 100, 4160
        patcher = self._make_mock_openai(in_tok, out_tok)
        try:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
                result = run_pipeline(single_product_brief)
        finally:
            patcher.stop()

        assert result.success
        manifests = list(outputs_root.glob("**/*manifest.json"))
        assert len(manifests) == 1
        data = json.loads(manifests[0].read_text())

        metrics = data["image_metrics"]
        assert "input_tokens" in metrics
        assert "output_tokens" in metrics
        assert "total_tokens" in metrics
        assert metrics["input_tokens"] == in_tok
        assert metrics["output_tokens"] == out_tok
        assert metrics["total_tokens"] == in_tok + out_tok
        expected_cost = (in_tok * 5 + out_tok * 40) / 1_000_000
        assert abs(metrics["estimated_cost_usd"] - expected_cost) < 1e-6
