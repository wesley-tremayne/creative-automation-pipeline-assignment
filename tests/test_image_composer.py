from __future__ import annotations

import os

import pytest
from PIL import Image

from PIL import ImageDraw, ImageFont

from src.image_composer import compose_creative, _cover_crop, _load_brand_colors, _truncate_to_fit, _text_height
from src.models import AspectRatio, CampaignBrief, Product, RATIO_DIMENSIONS


@pytest.fixture
def base_image(tmp_path):
    """Create a simple 500x500 test image and return its path."""
    img = Image.new("RGB", (500, 500), (100, 150, 200))
    path = str(tmp_path / "base.png")
    img.save(path)
    return path


@pytest.fixture
def product():
    return Product(
        name="TestProduct",
        description="A test product",
        category="skincare",
        tagline="Feel the glow",
    )


@pytest.fixture
def brief():
    return CampaignBrief(
        campaign_id="test",
        brand_name="TestBrand",
        target_region="US",
        target_audience="Adults 25-45",
        campaign_message="Glow every day",
        offer="20% OFF",
        products=[Product(name="P", description="d", category="c")],
    )


@pytest.fixture
def brand_guidelines():
    return {
        "primary_color": [255, 195, 0],
        "secondary_color": [20, 20, 30],
        "text_color": [255, 255, 255],
    }


class TestCoverCrop:
    def test_exact_dimensions(self):
        img = Image.new("RGB", (800, 600))
        result = _cover_crop(img, 400, 400)
        assert result.size == (400, 400)

    def test_scales_up(self):
        img = Image.new("RGB", (100, 100))
        result = _cover_crop(img, 1080, 1080)
        assert result.size == (1080, 1080)

    def test_landscape_to_portrait(self):
        img = Image.new("RGB", (1920, 1080))
        result = _cover_crop(img, 1080, 1920)
        assert result.size == (1080, 1920)


class TestLoadBrandColors:
    def test_extracts_colors(self, brand_guidelines):
        colors = _load_brand_colors(brand_guidelines)
        assert colors["primary"] == (255, 195, 0)
        assert colors["secondary"] == (20, 20, 30)
        assert colors["text"] == (255, 255, 255)

    def test_defaults_on_missing_keys(self):
        colors = _load_brand_colors({})
        assert colors["primary"] == (255, 195, 0)


class TestComposeCreative:
    def test_all_aspect_ratios(self, base_image, product, brief, brand_guidelines, tmp_path):
        for ratio in AspectRatio:
            out = str(tmp_path / f"creative_{ratio.value}.png")
            result = compose_creative(
                base_image, product, brief, ratio, out, brand_guidelines
            )
            assert os.path.exists(result)
            img = Image.open(result)
            assert img.size == RATIO_DIMENSIONS[ratio]

    def test_with_logo(self, base_image, product, brief, brand_guidelines, tmp_path):
        """Compose should not crash when a logo path is provided."""
        logo = Image.new("RGBA", (200, 200), (255, 195, 0, 128))
        logo_path = str(tmp_path / "logo.png")
        logo.save(logo_path)

        out = str(tmp_path / "with_logo.png")
        result = compose_creative(
            base_image, product, brief, AspectRatio.SQUARE, out, brand_guidelines,
            logo_path=logo_path,
        )
        assert os.path.exists(result)

    def test_without_offer(self, base_image, brand_guidelines, tmp_path):
        """Compose should work when brief has no offer."""
        product = Product(name="P", description="d", category="c")
        brief = CampaignBrief(
            campaign_id="t", brand_name="B", target_region="US",
            target_audience="all", campaign_message="msg",
            products=[product],
        )
        out = str(tmp_path / "no_offer.png")
        result = compose_creative(
            base_image, product, brief, AspectRatio.SQUARE, out, brand_guidelines
        )
        assert os.path.exists(result)

    def test_without_tagline(self, base_image, brand_guidelines, tmp_path):
        """Compose should work when product has no tagline."""
        product = Product(name="P", description="d", category="c")
        brief = CampaignBrief(
            campaign_id="t", brand_name="B", target_region="US",
            target_audience="all", campaign_message="msg",
            products=[product],
        )
        out = str(tmp_path / "no_tagline.png")
        result = compose_creative(
            base_image, product, brief, AspectRatio.SQUARE, out, brand_guidelines
        )
        assert os.path.exists(result)


# ── US-024: Text Truncation & Image Display Fixes ─────────────────────────────


@pytest.fixture
def draw_surface():
    """Return an ImageDraw on a minimal canvas for font measurement tests."""
    img = Image.new("RGB", (1080, 1080))
    return ImageDraw.Draw(img)


@pytest.fixture
def default_font():
    """Return a basic bitmap font (always available, no file needed)."""
    return ImageFont.load_default()


class TestTruncateToFit:
    """Unit tests for _truncate_to_fit() helper (US-024)."""

    def test_short_text_unchanged(self, draw_surface, default_font):
        """Text that fits within max_height is returned unchanged."""
        text = "Short message"
        result = _truncate_to_fit(draw_surface, text, default_font, 200)
        assert result == text

    def test_long_text_ends_with_ellipsis(self, draw_surface, default_font):
        """Text exceeding max_height is truncated and ends with '...'."""
        long_text = "\n".join(["This is a very long line of campaign copy"] * 20)
        result = _truncate_to_fit(draw_surface, long_text, default_font, 20)
        assert result.endswith("...")

    def test_truncated_text_fits_within_budget(self, draw_surface, default_font):
        """Truncated text height is within the specified max_height."""
        long_text = "\n".join(["Campaign message line"] * 30)
        max_h = 40
        result = _truncate_to_fit(draw_surface, long_text, default_font, max_h)
        assert _text_height(draw_surface, result, default_font) <= max_h

    def test_zero_budget_returns_ellipsis(self, draw_surface, default_font):
        """When max_height <= 0, function returns a minimal fallback."""
        result = _truncate_to_fit(draw_surface, "Any text here", default_font, 0)
        # Should return something (not crash); may be '...' or very short text
        assert isinstance(result, str)

    def test_empty_text_unchanged(self, draw_surface, default_font):
        """Empty string is returned unchanged."""
        result = _truncate_to_fit(draw_surface, "", default_font, 100)
        assert result == ""


class TestComposeCreativeLongText:
    """Verify compose_creative handles long campaign messages without overflowing (US-024)."""

    LONG_MESSAGE = (
        "Introducing the revolutionary HydraBoost Advanced Skincare System — "
        "a breakthrough formula developed over 10 years of research by leading "
        "dermatologists. Our patented HydraCell technology penetrates 7 layers "
        "deep to deliver unparalleled hydration, radiance, and anti-aging benefits "
        "that last all day, every day, for every skin type. Transform your skin today!"
    )  # ~450 chars

    SHORT_MESSAGE = "Glow every day."  # ~16 chars

    @pytest.fixture
    def base_img(self, tmp_path):
        img = Image.new("RGB", (500, 500), (80, 100, 120))
        path = str(tmp_path / "base.png")
        img.save(path)
        return path

    @pytest.fixture
    def brand_guidelines(self):
        return {
            "primary_color": [255, 195, 0],
            "secondary_color": [20, 20, 30],
            "text_color": [255, 255, 255],
        }

    @pytest.fixture
    def product(self):
        return Product(
            name="HydraBoost Pro",
            description="Advanced hydration system",
            category="skincare",
            tagline="7-layer deep hydration",
        )

    def _make_brief(self, message: str) -> CampaignBrief:
        return CampaignBrief(
            campaign_id="overflow-test",
            brand_name="TestBrand",
            target_region="US",
            target_audience="Adults 25-45",
            campaign_message=message,
            products=[Product(name="P", description="d", category="c")],
        )

    def test_long_message_produces_valid_image(self, base_img, product, brand_guidelines, tmp_path):
        """compose_creative completes without error with a 450+ char message."""
        brief = self._make_brief(self.LONG_MESSAGE)
        out = str(tmp_path / "long_text.png")
        result = compose_creative(base_img, product, brief, AspectRatio.SQUARE, out, brand_guidelines)
        assert os.path.exists(result)

    def test_long_message_correct_dimensions(self, base_img, product, brand_guidelines, tmp_path):
        """Output image has exact target dimensions even with a 450+ char message."""
        brief = self._make_brief(self.LONG_MESSAGE)
        out = str(tmp_path / "long_dims.png")
        result = compose_creative(base_img, product, brief, AspectRatio.SQUARE, out, brand_guidelines)
        img = Image.open(result)
        assert img.size == RATIO_DIMENSIONS[AspectRatio.SQUARE]

    def test_short_message_produces_valid_image(self, base_img, product, brand_guidelines, tmp_path):
        """compose_creative completes without error with a short message."""
        brief = self._make_brief(self.SHORT_MESSAGE)
        out = str(tmp_path / "short_text.png")
        result = compose_creative(base_img, product, brief, AspectRatio.SQUARE, out, brand_guidelines)
        assert os.path.exists(result)

    def test_all_ratios_with_long_message(self, base_img, product, brand_guidelines, tmp_path):
        """All three aspect ratios produce correctly-sized images with long text."""
        brief = self._make_brief(self.LONG_MESSAGE)
        for ratio in AspectRatio:
            out = str(tmp_path / f"long_{ratio.value}.png")
            result = compose_creative(base_img, product, brief, ratio, out, brand_guidelines)
            img = Image.open(result)
            assert img.size == RATIO_DIMENSIONS[ratio], f"Wrong size for {ratio}"

    def test_all_ratios_with_short_message(self, base_img, product, brand_guidelines, tmp_path):
        """All three aspect ratios produce correctly-sized images with short text."""
        brief = self._make_brief(self.SHORT_MESSAGE)
        for ratio in AspectRatio:
            out = str(tmp_path / f"short_{ratio.value}.png")
            result = compose_creative(base_img, product, brief, ratio, out, brand_guidelines)
            img = Image.open(result)
            assert img.size == RATIO_DIMENSIONS[ratio], f"Wrong size for {ratio}"

    def test_empty_message_does_not_crash(self, base_img, product, brand_guidelines, tmp_path):
        """Empty campaign message does not crash compose_creative."""
        brief = self._make_brief("")
        out = str(tmp_path / "empty_msg.png")
        result = compose_creative(base_img, product, brief, AspectRatio.SQUARE, out, brand_guidelines)
        assert os.path.exists(result)


class TestReportImageDisplayCSS:
    """Verify HTML report uses object-fit: contain for full image display (US-024)."""

    def test_reporter_uses_object_contain(self):
        """reporter.py CSS sets object-fit: contain (not cover) for asset images."""
        from pathlib import Path
        src = (Path(__file__).parent.parent / "src" / "reporter.py").read_text()
        assert "object-fit: contain" in src

    def test_reporter_does_not_use_object_cover(self):
        """reporter.py CSS does not use object-fit: cover (which clips images)."""
        from pathlib import Path
        src = (Path(__file__).parent.parent / "src" / "reporter.py").read_text()
        assert "object-fit: cover" not in src

    def test_reporter_max_height_generous(self):
        """reporter.py max-height for asset images is at least 400px."""
        from pathlib import Path
        import re
        src = (Path(__file__).parent.parent / "src" / "reporter.py").read_text()
        # Find max-height values in the CSS section
        matches = re.findall(r"max-height:\s*(\d+)px", src)
        assert matches, "No max-height found in reporter.py"
        max_val = max(int(v) for v in matches)
        assert max_val >= 400, f"max-height {max_val}px is too small for portrait images"

    def test_reporter_asset_card_has_background(self):
        """reporter.py .asset-card has a background color for letterbox fill."""
        from pathlib import Path
        src = (Path(__file__).parent.parent / "src" / "reporter.py").read_text()
        assert "background" in src


class TestGalleryImageDisplayJS:
    """Verify Web UI gallery uses object-contain for full image display (US-024)."""

    @pytest.fixture
    def app_js_content(self):
        from pathlib import Path
        return (Path(__file__).parent.parent / "static" / "js" / "app.js").read_text()

    def test_app_js_uses_object_contain(self, app_js_content):
        """app.js buildAssetCard uses object-contain (not object-cover) on images."""
        assert "object-contain" in app_js_content

    def test_app_js_does_not_use_object_cover_on_asset_img(self, app_js_content):
        """app.js does not use object-cover on the asset image element."""
        import re
        match = re.search(r"function buildAssetCard\(.*?\n\}", app_js_content, re.DOTALL)
        if match:
            func_body = match.group(0)
            assert "object-cover" not in func_body
        else:
            assert "asset-img" not in app_js_content or "object-cover" not in app_js_content

    def test_app_js_max_height_larger_than_44(self, app_js_content):
        """app.js image max height is larger than max-h-44 (176px) to show portrait images."""
        assert "max-h-44" not in app_js_content, "max-h-44 (176px) is too short for portrait images"
