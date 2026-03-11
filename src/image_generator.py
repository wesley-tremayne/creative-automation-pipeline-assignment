"""
Image Generator
---------------
Generates hero images for campaign products using OpenAI gpt-image-1.
Falls back to a branded gradient placeholder if no API key is configured.
"""

from __future__ import annotations

import json
import logging
import os
import random
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .models import AspectRatio, CampaignBrief, DALLE_SIZES, RATIO_DIMENSIONS, Product

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent.parent / "config"

# Circuit breaker: tracks whether the OpenAI API is available for this run.
# None = untested, True = working, False = failed (skip further attempts).
_api_available: bool | None = None


def _load_pricing() -> dict:
    """Load DALL-E pricing table from config/dalle_pricing.json."""
    pricing_path = _CONFIG_DIR / "dalle_pricing.json"
    try:
        with open(pricing_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("Could not load dalle_pricing.json: %s — using defaults", exc)
        return {"gpt-image-1": {"text_input_per_1m": 5.00, "image_input_per_1m": 10.00, "image_output_per_1m": 40.00}}


def _calculate_token_cost(input_tokens: int, output_tokens: int, model: str = "gpt-image-1") -> float:
    """Calculate cost in USD from actual token counts.

    Formula: (input_tokens * text_input_rate + output_tokens * image_output_rate) / 1_000_000
    """
    pricing = _load_pricing()
    try:
        rates = pricing[model]
        text_rate = float(rates["text_input_per_1m"])
        output_rate = float(rates["image_output_per_1m"])
    except (KeyError, TypeError, ValueError):
        logger.warning("No token pricing found for model=%s — using defaults", model)
        text_rate = 5.00
        output_rate = 40.00
    return (input_tokens * text_rate + output_tokens * output_rate) / 1_000_000


# Token estimation table for fallback when raw API response lacks `usage`.
# Values are approximate output tokens by size and quality for gpt-image-1.
_TOKEN_ESTIMATES: dict[str, dict[str, int]] = {
    "1024x1024":  {"low": 4_160,  "medium": 8_160,  "high": 16_160, "auto": 8_160},
    "1024x1792":  {"low": 7_168,  "medium": 14_336, "high": 28_672, "auto": 14_336},
    "1792x1024":  {"low": 7_168,  "medium": 14_336, "high": 28_672, "auto": 14_336},
}
# Rough estimate for input tokens (prompt text is typically short)
_ESTIMATED_INPUT_TOKENS = 100


def _estimate_tokens(size: str, quality: str) -> tuple[int, int, int]:
    """Return (input_tokens, output_tokens, total_tokens) from size/quality table."""
    size_table = _TOKEN_ESTIMATES.get(size, _TOKEN_ESTIMATES["1024x1024"])
    output_tokens = size_table.get(quality, size_table["auto"])
    input_tokens = _ESTIMATED_INPUT_TOKENS
    return input_tokens, output_tokens, input_tokens + output_tokens


def reset_api_status() -> None:
    """Reset the API availability flag. Call between pipeline runs or in tests."""
    global _api_available
    _api_available = None


def get_system_font(size: int = 48) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try common system font locations; fall back to PIL default."""
    font_candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for path in font_candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def build_dalle_prompt(product: Product, brief: CampaignBrief) -> str:
    return (
        f"Professional advertising photography for a {product.category} product called '{product.name}'. "
        f"{product.description}. "
        f"Target audience: {brief.target_audience} in {brief.target_region}. "
        f"Visual tone: {brief.tone}. "
        f"Modern, clean composition designed for a social media ad campaign. "
        f"Vibrant yet sophisticated color palette. Cinematic lighting. "
        f"No text, no labels, no watermarks in the image. "
        f"High-end commercial photography style."
    )


def generate_base_image(
    product: Product,
    brief: CampaignBrief,
    aspect_ratio: AspectRatio,
    output_path: str,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[str, dict]:
    """Generate a base hero image for the product.

    Uses OpenAI gpt-image-1 when OPENAI_API_KEY is configured, otherwise
    falls back to a branded gradient placeholder (no external dependencies).
    The API key is never logged — only its presence is checked.

    Args:
        product: Product data for prompt construction.
        brief: Campaign brief (region, audience, tone etc.).
        aspect_ratio: Target aspect ratio, used to select the DALL-E size.
        output_path: Local path where the image should be saved.
        progress_cb: Optional callback for progress messages.

    Returns:
        Tuple of (path, metadata) where metadata contains:
            method: "dall-e" or "fallback"
            model: model name used
            size: image size string (e.g. "1024x1024")
            cost_usd: estimated cost in USD
    """
    global _api_available

    # Check API key presence without logging the value
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    key_configured = bool(api_key) and api_key != "sk-...your-key-here..."

    if not key_configured:
        logger.info("OpenAI API key: not configured — using gradient placeholder")
        if progress_cb:
            progress_cb(
                f"ℹ️  No API key configured — creating styled placeholder for '{product.name}'"
            )
        return _generate_placeholder_image(product, brief, aspect_ratio, output_path)

    # Circuit breaker: skip API if a previous call already failed this run
    if _api_available is False:
        logger.info("Skipping API call for '%s' — API unavailable (circuit breaker)", product.name)
        return _generate_placeholder_image(product, brief, aspect_ratio, output_path)

    if progress_cb:
        progress_cb(f"🎨 Generating image for '{product.name}' via gpt-image-1...")
    return _generate_dalle_image(product, brief, aspect_ratio, output_path, api_key, progress_cb)


def _generate_dalle_image(
    product: Product,
    brief: CampaignBrief,
    aspect_ratio: AspectRatio,
    output_path: str,
    api_key: str,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[str, dict]:
    """Generate an image via OpenAI gpt-image-1, with graceful fallback."""
    global _api_available
    model = "gpt-image-1"
    size = DALLE_SIZES[aspect_ratio]
    quality = "auto"

    try:
        from openai import OpenAI
    except ImportError:
        logger.error("openai package not installed")
        return _generate_placeholder_image(product, brief, aspect_ratio, output_path)

    try:
        import base64

        client = OpenAI(api_key=api_key)
        prompt = build_dalle_prompt(product, brief)
        logger.info("gpt-image-1 prompt: %s", prompt)

        # Use with_raw_response to access the raw HTTP JSON body.
        # The OpenAI SDK v1.51.0 ImagesResponse model strips `usage` during
        # parsing, so we must read it from the raw response before it is lost.
        raw_response = client.images.with_raw_response.generate(
            model=model,
            prompt=prompt,
            size=size,  # type: ignore[arg-type]
            quality=quality,
            n=1,
        )
        response = raw_response.parse()

        image_data = base64.b64decode(response.data[0].b64_json)
        img = Image.open(BytesIO(image_data)).convert("RGB")
        img.save(output_path, "PNG")
        _api_available = True

        # Extract token counts from raw JSON body (SDK strips this field).
        # LegacyAPIResponse has .text (not .json()), so we parse manually.
        try:
            raw_json = json.loads(raw_response.text)
        except (json.JSONDecodeError, AttributeError):
            raw_json = {}
        usage_dict = raw_json.get("usage") if isinstance(raw_json, dict) else None
        token_source: str
        if usage_dict and isinstance(usage_dict, dict):
            input_tokens = int(usage_dict.get("input_tokens", 0))
            output_tokens = int(usage_dict.get("output_tokens", 0))
            total_tokens = int(usage_dict.get("total_tokens", input_tokens + output_tokens))
            token_source = "actual"
        else:
            logger.warning(
                "gpt-image-1 response lacks usage data — estimating tokens from size/quality table "
                "(size=%s, quality=%s)", size, quality,
            )
            input_tokens, output_tokens, total_tokens = _estimate_tokens(size, quality)
            token_source = "estimated"

        cost = _calculate_token_cost(input_tokens, output_tokens, model)
        logger.info(
            "Saved gpt-image-1 image → %s (tokens [%s]: %d in / %d out, cost: $%.4f)",
            output_path, token_source, input_tokens, output_tokens, cost,
        )
        return output_path, {
            "method": "dall-e",
            "model": model,
            "size": size,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost,
            "token_source": token_source,
        }
    except Exception as exc:
        _api_available = False
        logger.warning("gpt-image-1 API failed (circuit breaker tripped): %s", exc)
        if progress_cb:
            progress_cb(
                "ℹ️  AI image generation is unavailable — using styled placeholders for all products"
            )
        return _generate_placeholder_image(product, brief, aspect_ratio, output_path)


# ── Colour palettes per category ───────────────────────────────────────────────
PALETTE: dict[str, list[tuple[int, int, int]]] = {
    "skincare":  [(255, 200, 180), (220, 140, 120)],
    "beverage":  [(30,  90, 180),  (10,  40,  90)],
    "food":      [(250, 180,  60), (200, 100,  20)],
    "fitness":   [(40,  180,  80), (10,   80,  30)],
    "tech":      [(40,   40, 120), (10,   10,  60)],
    "default":   [(80,   60, 200), (30,   20, 100)],
}


def _get_palette(category: str) -> list[tuple[int, int, int]]:
    key = category.lower()
    for k in PALETTE:
        if k in key:
            return PALETTE[k]
    return PALETTE["default"]


def _generate_placeholder_image(
    product: Product,
    brief: CampaignBrief,
    aspect_ratio: AspectRatio,
    output_path: str,
) -> tuple[str, dict]:
    """Generate a stylised gradient placeholder with product name."""
    w, h = RATIO_DIMENSIONS[aspect_ratio]
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)

    colors = _get_palette(product.category)
    c1, c2 = colors[0], colors[1]

    # Vertical gradient
    for y in range(h):
        t = y / h
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # Decorative circles
    random.seed(hash(product.name))
    for _ in range(6):
        cx = random.randint(0, w)
        cy = random.randint(0, h)
        r_size = random.randint(w // 6, w // 2)
        draw.ellipse(
            [(cx - r_size, cy - r_size), (cx + r_size, cy + r_size)],
            fill=(*c1, 40),
        )

    # Apply slight blur for depth
    img = img.filter(ImageFilter.GaussianBlur(radius=w // 80))
    draw = ImageDraw.Draw(img)

    # Product name watermark in centre
    font_size = max(w // 14, 36)
    font = get_system_font(font_size)
    text = product.name.upper()
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        tw, th = draw.textsize(text, font=font)  # type: ignore[attr-defined]

    draw.text(
        ((w - tw) // 2, (h - th) // 2),
        text,
        fill=(255, 255, 255, 160),
        font=font,
    )

    img.save(output_path, "PNG")
    logger.info("Saved placeholder image → %s", output_path)
    size = DALLE_SIZES[aspect_ratio]
    return output_path, {
        "method": "fallback",
        "model": "fallback",
        "size": size,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }
