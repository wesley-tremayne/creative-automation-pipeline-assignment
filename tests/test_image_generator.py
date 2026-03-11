from __future__ import annotations

import json
import os
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

from src.image_generator import (
    build_dalle_prompt,
    generate_base_image,
    _generate_placeholder_image,
    _calculate_token_cost,
    _estimate_tokens,
    _get_palette,
    reset_api_status,
    PALETTE,
)
from src.models import AspectRatio, CampaignBrief, Product, RATIO_DIMENSIONS


@pytest.fixture
def product():
    return Product(name="TestSerum", description="A hydrating serum", category="skincare")


@pytest.fixture
def brief():
    return CampaignBrief(
        campaign_id="test",
        brand_name="TestBrand",
        target_region="US",
        target_audience="Adults 25-45",
        campaign_message="Glow every day",
        products=[Product(name="TestSerum", description="A hydrating serum", category="skincare")],
    )


class TestBuildDallePrompt:
    def test_contains_product_info(self, product, brief):
        prompt = build_dalle_prompt(product, brief)
        assert "TestSerum" in prompt
        assert "skincare" in prompt
        assert "hydrating serum" in prompt

    def test_contains_audience_and_region(self, product, brief):
        prompt = build_dalle_prompt(product, brief)
        assert "Adults 25-45" in prompt
        assert "US" in prompt


class TestGetPalette:
    def test_known_category(self):
        assert _get_palette("skincare") == PALETTE["skincare"]
        assert _get_palette("beverage") == PALETTE["beverage"]

    def test_unknown_category_returns_default(self):
        assert _get_palette("unknown_xyz") == PALETTE["default"]

    def test_case_insensitive(self):
        assert _get_palette("SKINCARE") == PALETTE["skincare"]


class TestPlaceholderImage:
    def test_generates_correct_dimensions(self, product, brief, tmp_path):
        for ratio in AspectRatio:
            out = str(tmp_path / f"test_{ratio.value}.png")
            _generate_placeholder_image(product, brief, ratio, out)
            img = Image.open(out)
            assert img.size == RATIO_DIMENSIONS[ratio]

    def test_output_file_created(self, product, brief, tmp_path):
        out = str(tmp_path / "placeholder.png")
        path, meta = _generate_placeholder_image(product, brief, AspectRatio.SQUARE, out)
        assert os.path.exists(path)
        assert path == out


class TestGenerateBaseImage:
    def test_fallback_without_api_key(self, product, brief, tmp_path):
        """Without OPENAI_API_KEY, should generate a placeholder."""
        out = str(tmp_path / "fallback.png")
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            path, meta = generate_base_image(product, brief, AspectRatio.SQUARE, out)
        assert os.path.exists(path)
        img = Image.open(path)
        assert img.size == RATIO_DIMENSIONS[AspectRatio.SQUARE]
        assert meta["method"] == "fallback"
        assert meta["cost_usd"] == 0.0

    def test_fallback_with_placeholder_key(self, product, brief, tmp_path):
        """The sentinel placeholder key should trigger fallback."""
        out = str(tmp_path / "fallback2.png")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-...your-key-here..."}, clear=False):
            path, meta = generate_base_image(product, brief, AspectRatio.SQUARE, out)
        assert os.path.exists(path)
        assert meta["method"] == "fallback"

    def test_progress_callback_called(self, product, brief, tmp_path):
        out = str(tmp_path / "cb.png")
        cb = MagicMock()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            generate_base_image(product, brief, AspectRatio.SQUARE, out, progress_cb=cb)
        cb.assert_called()


# ── US-015: Circuit Breaker & Fallback Tests ─────────────────────────────────

class TestCircuitBreaker:
    """Verify API failure circuit breaker skips subsequent calls."""

    @pytest.fixture(autouse=True)
    def _reset_api(self):
        """Reset circuit breaker state before and after each test."""
        reset_api_status()
        yield
        reset_api_status()

    def test_first_failure_trips_breaker(self, product, brief, tmp_path):
        """After a failed API call, _api_available is set to False."""
        import src.image_generator as ig

        out = str(tmp_path / "trip.png")
        mock_client = MagicMock()
        mock_client.images.with_raw_response.generate.side_effect = Exception("billing_hard_limit_reached")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
            with patch("openai.OpenAI", return_value=mock_client):
                generate_base_image(product, brief, AspectRatio.SQUARE, out)

        assert ig._api_available is False

    def test_second_call_skips_api(self, product, brief, tmp_path):
        """After breaker trips, subsequent calls skip the API entirely."""
        import src.image_generator as ig

        mock_client = MagicMock()
        mock_client.images.with_raw_response.generate.side_effect = Exception("billing_hard_limit_reached")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
            with patch("openai.OpenAI", return_value=mock_client):
                # First call — hits API, fails, trips breaker
                out1 = str(tmp_path / "first.png")
                generate_base_image(product, brief, AspectRatio.SQUARE, out1)
                assert ig._api_available is False
                assert mock_client.images.with_raw_response.generate.call_count == 1

                # Second call — skips API entirely
                out2 = str(tmp_path / "second.png")
                generate_base_image(product, brief, AspectRatio.SQUARE, out2)
                # API should NOT have been called again
                assert mock_client.images.with_raw_response.generate.call_count == 1

        # Both files should still exist (placeholders)
        assert os.path.exists(out1)
        assert os.path.exists(out2)

    def test_breaker_emits_single_message(self, product, brief, tmp_path):
        """Only the first failure emits the unavailability message, not the second."""
        mock_client = MagicMock()
        mock_client.images.with_raw_response.generate.side_effect = Exception("billing error")
        cb = MagicMock()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
            with patch("openai.OpenAI", return_value=mock_client):
                out1 = str(tmp_path / "msg1.png")
                generate_base_image(product, brief, AspectRatio.SQUARE, out1, progress_cb=cb)

                # First call emits the unavailability message
                calls_after_first = cb.call_count

                out2 = str(tmp_path / "msg2.png")
                generate_base_image(product, brief, AspectRatio.SQUARE, out2, progress_cb=cb)

                # Second call should NOT emit any progress message (no cb call)
                assert cb.call_count == calls_after_first

    def test_successful_api_sets_available(self, product, brief, tmp_path):
        """A successful API call sets _api_available to True and returns token metadata."""
        import src.image_generator as ig
        import base64
        from io import BytesIO

        # Create a fake image response
        fake_img = Image.new("RGB", (100, 100), (0, 0, 255))
        buf = BytesIO()
        fake_img.save(buf, format="PNG")
        fake_b64 = base64.b64encode(buf.getvalue()).decode()

        # Parsed response (returned by raw_response.parse())
        parsed_response = MagicMock()
        parsed_response.data = [MagicMock(b64_json=fake_b64)]

        # Raw response (returned by with_raw_response.generate())
        # LegacyAPIResponse exposes .text (not .json()), so we set the raw JSON string.
        raw_response = MagicMock()
        raw_response.parse.return_value = parsed_response
        raw_response.text = json.dumps({
            "created": 1234567890,
            "usage": {"input_tokens": 100, "output_tokens": 1000, "total_tokens": 1100},
        })

        mock_client = MagicMock()
        mock_client.images.with_raw_response.generate.return_value = raw_response

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
            with patch("openai.OpenAI", return_value=mock_client):
                out = str(tmp_path / "success.png")
                path, meta = generate_base_image(product, brief, AspectRatio.SQUARE, out)

        assert ig._api_available is True
        assert os.path.exists(path)
        img = Image.open(path)
        assert img.size[0] > 0
        assert meta["method"] == "dall-e"
        assert meta["input_tokens"] == 100
        assert meta["output_tokens"] == 1000
        assert meta["total_tokens"] == 1100
        assert meta["token_source"] == "actual"
        # Cost: (100 * 5 + 1000 * 40) / 1_000_000 = 0.0405
        assert abs(meta["cost_usd"] - 0.0405) < 1e-6


class TestResetApiStatus:
    """Verify reset_api_status() clears the circuit breaker."""

    def test_reset_clears_false(self):
        """reset_api_status() resets _api_available from False to None."""
        import src.image_generator as ig

        ig._api_available = False
        reset_api_status()
        assert ig._api_available is None

    def test_reset_clears_true(self):
        """reset_api_status() resets _api_available from True to None."""
        import src.image_generator as ig

        ig._api_available = True
        reset_api_status()
        assert ig._api_available is None


class TestPlaceholderFallbackSuccess:
    """Verify pipeline result.success is true when using placeholders."""

    @pytest.fixture(autouse=True)
    def _reset_api(self):
        reset_api_status()
        yield
        reset_api_status()

    def test_pipeline_succeeds_with_no_api_key(self):
        """Pipeline completes successfully with no API key (placeholders used)."""
        from src.pipeline import run_pipeline

        brief = CampaignBrief(
            campaign_id="fallback_success_test",
            brand_name="FallbackBrand",
            target_region="US",
            target_audience="Adults 25-45",
            campaign_message="Fallback test",
            products=[
                Product(name="FallbackProd", description="Desc", category="skincare"),
            ],
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = run_pipeline(brief)

        assert result.success
        assert result.total_assets == 3
        assert len(result.errors) == 0

    def test_pipeline_succeeds_with_failed_api(self):
        """Pipeline completes successfully when API fails (circuit breaker)."""
        from src.pipeline import run_pipeline

        brief = CampaignBrief(
            campaign_id="breaker_success_test",
            brand_name="BreakerBrand",
            target_region="US",
            target_audience="Adults 25-45",
            campaign_message="Breaker test",
            products=[
                Product(name="BreakerProd1", description="Desc", category="skincare"),
                Product(name="BreakerProd2", description="Desc", category="beverage"),
            ],
        )
        mock_client = MagicMock()
        mock_client.images.generate.side_effect = Exception("billing_hard_limit_reached")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
            with patch("openai.OpenAI", return_value=mock_client):
                result = run_pipeline(brief)

        assert result.success
        assert result.total_assets == 6  # 2 products × 3 ratios
        assert len(result.errors) == 0

    def test_no_warnings_with_empty_key(self, product, brief, tmp_path):
        """No API key produces an info message, not a warning."""
        cb = MagicMock()
        out = str(tmp_path / "nokey.png")
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            generate_base_image(product, brief, AspectRatio.SQUARE, out, progress_cb=cb)

        # The callback message should be informational (ℹ️), not a warning (⚠️)
        msg = cb.call_args[0][0]
        assert "ℹ" in msg
        assert "warning" not in msg.lower()
        assert "failed" not in msg.lower()


# ── US-021 Phase 2: Token-Based Cost Calculation Tests ────────────────────────


class TestCalculateTokenCost:
    """Unit tests for _calculate_token_cost() — token-based pricing formula."""

    def test_zero_tokens_zero_cost(self):
        """Zero tokens produces zero cost."""
        assert _calculate_token_cost(0, 0) == 0.0

    def test_output_tokens_only(self):
        """Cost formula: output_tokens * $40/1M."""
        # 1000 output tokens × $40/1M = $0.04
        cost = _calculate_token_cost(0, 1000)
        assert abs(cost - 0.04) < 1e-9

    def test_input_tokens_only(self):
        """Cost formula: input_tokens * $5/1M."""
        # 1000 input tokens × $5/1M = $0.005
        cost = _calculate_token_cost(1000, 0)
        assert abs(cost - 0.005) < 1e-9

    def test_combined_token_cost(self):
        """Cost formula: (input * 5 + output * 40) / 1_000_000."""
        # 100 input, 1000 output: (100×5 + 1000×40) / 1M = 40500 / 1M = 0.0405
        cost = _calculate_token_cost(100, 1000)
        assert abs(cost - 0.0405) < 1e-9

    def test_realistic_medium_quality(self):
        """Medium quality 1024x1024 approximation (~8160 output tokens)."""
        # ~100 input, ~8160 output: (100×5 + 8160×40) / 1M = 0.3265
        cost = _calculate_token_cost(100, 8160)
        expected = (100 * 5 + 8160 * 40) / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_fallback_mode_metadata_has_zero_tokens(self, product, brief, tmp_path):
        """Placeholder (fallback) image metadata includes zero token counts."""
        out = str(tmp_path / "fallback.png")
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            path, meta = generate_base_image(product, brief, AspectRatio.SQUARE, out)

        assert meta["method"] == "fallback"
        assert meta["input_tokens"] == 0
        assert meta["output_tokens"] == 0
        assert meta["total_tokens"] == 0
        assert meta["cost_usd"] == 0.0

    def test_api_response_without_usage_gracefully_defaults(self, product, brief, tmp_path):
        """If raw JSON lacks a 'usage' key, tokens are estimated from size/quality table."""
        import base64
        from io import BytesIO
        from src.image_generator import _estimate_tokens

        fake_img = Image.new("RGB", (100, 100), (0, 255, 0))
        buf = BytesIO()
        fake_img.save(buf, format="PNG")
        fake_b64 = base64.b64encode(buf.getvalue()).decode()

        # Parsed response — no usage on the SDK model (always the case)
        parsed_response = MagicMock()
        parsed_response.data = [MagicMock(b64_json=fake_b64)]

        # Raw response — raw JSON has NO 'usage' key (API version mismatch)
        raw_response = MagicMock()
        raw_response.parse.return_value = parsed_response
        raw_response.text = json.dumps({"created": 1234567890})  # no 'usage' key

        mock_client = MagicMock()
        mock_client.images.with_raw_response.generate.return_value = raw_response

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
            with patch("openai.OpenAI", return_value=mock_client):
                out = str(tmp_path / "no_usage.png")
                path, meta = generate_base_image(product, brief, AspectRatio.SQUARE, out)

        # Tokens should be estimated (non-zero), not zero
        est_in, est_out, est_total = _estimate_tokens("1024x1024", "auto")
        assert os.path.exists(path)
        assert meta["method"] == "dall-e"
        assert meta["input_tokens"] == est_in
        assert meta["output_tokens"] == est_out
        assert meta["total_tokens"] == est_total
        assert meta["token_source"] == "estimated"
        # Cost should match estimated tokens
        from src.image_generator import _calculate_token_cost
        expected_cost = _calculate_token_cost(est_in, est_out)
        assert abs(meta["cost_usd"] - expected_cost) < 1e-9


# ── US-021 Phase 3: Raw Response Parsing & Token Estimation ───────────────────


class TestEstimateTokens:
    """Unit tests for the _estimate_tokens() fallback table (US-021 Phase 3)."""

    def test_square_auto_quality(self):
        """1024x1024 auto quality matches reference table (8160 output tokens)."""
        inp, out, total = _estimate_tokens("1024x1024", "auto")
        assert out == 8_160
        assert inp == 100
        assert total == inp + out

    def test_square_medium_quality(self):
        """1024x1024 medium quality matches reference table (8160 output tokens)."""
        inp, out, total = _estimate_tokens("1024x1024", "medium")
        assert out == 8_160

    def test_square_low_quality(self):
        """1024x1024 low quality returns lower token count (4160)."""
        inp, out, total = _estimate_tokens("1024x1024", "low")
        assert out == 4_160

    def test_portrait_size(self):
        """1024x1792 auto quality returns higher token count than square."""
        _, square_out, _ = _estimate_tokens("1024x1024", "auto")
        _, portrait_out, _ = _estimate_tokens("1024x1792", "auto")
        assert portrait_out > square_out

    def test_unknown_size_defaults_to_square(self):
        """Unknown size defaults to 1024x1024 estimates."""
        inp, out, total = _estimate_tokens("unknown_size", "auto")
        exp_inp, exp_out, exp_total = _estimate_tokens("1024x1024", "auto")
        assert out == exp_out

    def test_unknown_quality_defaults_to_auto(self):
        """Unknown quality falls back to 'auto' estimate."""
        inp, out, total = _estimate_tokens("1024x1024", "unknown_quality")
        exp_inp, exp_out, _ = _estimate_tokens("1024x1024", "auto")
        assert out == exp_out


class TestRawResponseParsing:
    """Verify _generate_dalle_image reads usage from raw HTTP JSON (US-021 Phase 3)."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_api_status()
        yield
        reset_api_status()

    def _make_raw_mock(self, fake_b64: str, usage_dict: dict | None):
        """Build a mock that simulates with_raw_response.generate() output."""
        parsed = MagicMock()
        parsed.data = [MagicMock(b64_json=fake_b64)]

        raw = MagicMock()
        raw.parse.return_value = parsed
        raw_json: dict = {"created": 1234567890}
        if usage_dict is not None:
            raw_json["usage"] = usage_dict
        raw.text = json.dumps(raw_json)

        mock_client = MagicMock()
        mock_client.images.with_raw_response.generate.return_value = raw
        return mock_client

    @pytest.fixture
    def fake_b64(self):
        import base64
        from io import BytesIO
        img = Image.new("RGB", (100, 100), (0, 128, 0))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def test_actual_usage_extracted_from_raw_json(self, product, brief, tmp_path, fake_b64):
        """When raw JSON contains 'usage', tokens are read exactly (token_source='actual')."""
        mock_client = self._make_raw_mock(fake_b64, {
            "input_tokens": 80, "output_tokens": 4160, "total_tokens": 4240
        })
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
            with patch("openai.OpenAI", return_value=mock_client):
                path, meta = generate_base_image(product, brief, AspectRatio.SQUARE,
                                                 str(tmp_path / "actual.png"))

        assert meta["token_source"] == "actual"
        assert meta["input_tokens"] == 80
        assert meta["output_tokens"] == 4160
        assert meta["total_tokens"] == 4240

    def test_missing_usage_triggers_estimation(self, product, brief, tmp_path, fake_b64):
        """When raw JSON has no 'usage' key, tokens are estimated (token_source='estimated')."""
        mock_client = self._make_raw_mock(fake_b64, None)  # no usage key
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
            with patch("openai.OpenAI", return_value=mock_client):
                path, meta = generate_base_image(product, brief, AspectRatio.SQUARE,
                                                 str(tmp_path / "estimated.png"))

        assert meta["token_source"] == "estimated"
        assert meta["input_tokens"] > 0
        assert meta["output_tokens"] > 0

    def test_actual_usage_cost_matches_formula(self, product, brief, tmp_path, fake_b64):
        """Cost from actual tokens is calculated correctly with the token formula."""
        in_tok, out_tok = 120, 8160
        mock_client = self._make_raw_mock(fake_b64, {
            "input_tokens": in_tok, "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
        })
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
            with patch("openai.OpenAI", return_value=mock_client):
                _, meta = generate_base_image(product, brief, AspectRatio.SQUARE,
                                              str(tmp_path / "cost.png"))

        expected = _calculate_token_cost(in_tok, out_tok)
        assert abs(meta["cost_usd"] - expected) < 1e-9

    def test_with_raw_response_is_called_not_images_generate(self, product, brief, tmp_path, fake_b64):
        """with_raw_response.generate() is called, NOT images.generate() directly."""
        mock_client = self._make_raw_mock(fake_b64, {"input_tokens": 100, "output_tokens": 8160, "total_tokens": 8260})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=False):
            with patch("openai.OpenAI", return_value=mock_client):
                generate_base_image(product, brief, AspectRatio.SQUARE, str(tmp_path / "api.png"))

        assert mock_client.images.with_raw_response.generate.call_count == 1
        assert mock_client.images.generate.call_count == 0
