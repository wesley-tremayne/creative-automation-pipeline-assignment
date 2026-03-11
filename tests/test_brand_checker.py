from __future__ import annotations

from PIL import Image

from src.brand_checker import check_brand_compliance


def _create_test_image(tmp_path, color=(255, 195, 0), size=(100, 100)):
    """Create a solid-color test image and return its path."""
    img = Image.new("RGB", size, color)
    path = str(tmp_path / "test.png")
    img.save(path)
    return path


class TestBrandChecker:
    def test_compliant_image(self, tmp_path):
        """Image with brand colour should pass colour check."""
        path = _create_test_image(tmp_path, color=(255, 195, 0))
        guidelines = {"primary_color": [255, 195, 0]}
        issues = check_brand_compliance(path, guidelines, has_logo=False)
        # Should not flag primary colour missing
        color_issues = [i for i in issues if "Primary brand colour" in i]
        assert len(color_issues) == 0

    def test_wrong_color_flagged(self, tmp_path):
        """Image without brand colour should be flagged."""
        path = _create_test_image(tmp_path, color=(0, 0, 255))
        guidelines = {"primary_color": [255, 195, 0]}
        issues = check_brand_compliance(path, guidelines, has_logo=False)
        assert any("Primary brand colour" in i for i in issues)

    def test_dark_image_flagged(self, tmp_path):
        """Very dark image should be flagged."""
        path = _create_test_image(tmp_path, color=(5, 5, 5))
        guidelines = {"primary_color": [5, 5, 5]}
        issues = check_brand_compliance(path, guidelines, has_logo=False)
        assert any("too dark" in i for i in issues)

    def test_missing_image_returns_issue(self, tmp_path):
        """Non-existent image should return an issue, not crash."""
        issues = check_brand_compliance("/nonexistent.png", {}, has_logo=False)
        assert len(issues) == 1
        assert "Could not open" in issues[0]
