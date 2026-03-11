"""
Image Composer
--------------
Takes a base image and applies branded overlays:
  • Bottom gradient bar with campaign message
  • Product name & tagline
  • Offer badge
  • CTA button area
  • Brand logo (if available)
  • Resizes to exact target dimensions for each aspect ratio
"""

from __future__ import annotations

import logging
import os
import textwrap
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageEnhance

from .models import AspectRatio, CampaignBrief, Product, RATIO_DIMENSIONS
from .image_generator import get_system_font

logger = logging.getLogger(__name__)

# Brand color from guidelines (can be overridden via config)
DEFAULT_ACCENT = (255, 195, 0)      # golden yellow
DEFAULT_TEXT   = (255, 255, 255)
DEFAULT_DARK   = (20,  20,  20)


def _load_brand_colors(brand_guidelines: dict) -> dict:
    return {
        "primary":  tuple(brand_guidelines.get("primary_color",  [255, 195, 0])),
        "secondary": tuple(brand_guidelines.get("secondary_color", [30, 30, 30])),
        "text":     tuple(brand_guidelines.get("text_color",     [255, 255, 255])),
    }


def compose_creative(
    base_image_path: str,
    product: Product,
    brief: CampaignBrief,
    aspect_ratio: AspectRatio,
    output_path: str,
    brand_guidelines: dict,
    logo_path: Optional[str] = None,
) -> str:
    """
    Compose a single ad creative and save it.
    Returns the output path.
    """
    target_w, target_h = RATIO_DIMENSIONS[aspect_ratio]
    colors = _load_brand_colors(brand_guidelines)

    # 1. Load & resize base image (cover crop)
    img = Image.open(base_image_path).convert("RGB")
    img = _cover_crop(img, target_w, target_h)

    # 2. Slightly darken image for text legibility
    img = ImageEnhance.Brightness(img).enhance(0.80)

    draw = ImageDraw.Draw(img, "RGBA")

    # 3. Bottom gradient overlay
    overlay_h = int(target_h * 0.42)
    overlay_top = target_h - overlay_h
    _draw_gradient_rect(
        draw,
        (0, overlay_top, target_w, target_h),
        start_alpha=0,
        end_alpha=210,
        color=colors["secondary"],
    )

    # 4. Accent strip at very bottom
    strip_h = max(8, target_h // 120)
    draw.rectangle(
        [(0, target_h - strip_h), (target_w, target_h)],
        fill=(*colors["primary"], 255),
    )

    # 5. Brand name (small, top-left)
    brand_font_size = max(int(target_w * 0.025), 18)
    brand_font = get_system_font(brand_font_size)
    brand_text = brief.brand_name.upper()
    draw.text(
        (int(target_w * 0.04), int(target_h * 0.04)),
        brand_text,
        font=brand_font,
        fill=(*colors["text"], 220),
    )

    # 6. Offer badge (top-right, if present)
    if brief.offer:
        _draw_offer_badge(draw, brief.offer, target_w, target_h, colors)

    # 7. Campaign message (large, lower third)
    # Scale font by min(width, height*aspect_correction) to avoid oversized text in landscape
    msg_font_size = max(int(min(target_w, target_h * 1.5) * 0.055), 28)
    msg_font = get_system_font(msg_font_size)
    max_chars = max(18, int(target_w / msg_font_size * 1.15))
    wrapped = textwrap.fill(brief.campaign_message, width=max_chars)
    msg_y = int(target_h * 0.55)

    # Calculate how much vertical space the message may consume.
    # Reserve room below for: product name, tagline, CTA, spacing, and the accent strip.
    _ref = min(target_w, target_h * 1.5)
    _prod_h_est  = max(int(_ref * 0.038), 20) * 2      # product name (generous)
    _tag_h_est   = (max(int(_ref * 0.026), 16) * 2) if product.tagline else 0
    _cta_h_est   = max(int(_ref * 0.030), 18) + 2 * int(target_h * 0.012)
    _reserved = (
        int(target_h * 0.015)   # gap: msg → product name
        + _prod_h_est
        + (int(target_h * 0.010) + _tag_h_est if product.tagline else 0)
        + int(target_h * 0.020) # gap: text → CTA
        + _cta_h_est
        + int(target_h * 0.030) # bottom margin
        + strip_h
    )
    max_msg_h = target_h - msg_y - _reserved
    wrapped = _truncate_to_fit(draw, wrapped, msg_font, max_msg_h)

    _draw_text_shadow(draw, wrapped, (int(target_w * 0.05), msg_y), msg_font, colors["text"])

    # 8. Product name
    prod_font_size = max(int(min(target_w, target_h * 1.5) * 0.038), 20)
    prod_font = get_system_font(prod_font_size)
    prod_y = msg_y + _text_height(draw, wrapped, msg_font) + int(target_h * 0.015)
    draw.text(
        (int(target_w * 0.05), prod_y),
        product.name,
        font=prod_font,
        fill=(*colors["primary"], 240),
    )

    # 9. Tagline / product description (small)
    text_bottom = prod_y + _text_height(draw, product.name, prod_font)
    if product.tagline:
        tag_font_size = max(int(min(target_w, target_h * 1.5) * 0.026), 16)
        tag_font = get_system_font(tag_font_size)
        tag_y = text_bottom + int(target_h * 0.010)
        draw.text(
            (int(target_w * 0.05), tag_y),
            product.tagline,
            font=tag_font,
            fill=(*colors["text"], 180),
        )
        text_bottom = tag_y + _text_height(draw, product.tagline, tag_font)

    # 10. CTA button area — positioned below text stack, clamped within canvas
    cta_font_size = max(int(min(target_w, target_h * 1.5) * 0.030), 18)
    cta_btn_h = cta_font_size + 2 * int(target_h * 0.012)
    max_cta_y = target_h - strip_h - cta_btn_h - int(target_h * 0.015)
    cta_y = min(text_bottom + int(target_h * 0.020), max_cta_y)
    _draw_cta(draw, brief.cta, target_w, target_h, colors, cta_y=cta_y)

    # 11. Logo overlay (bottom-right)
    if logo_path and os.path.exists(logo_path):
        _draw_logo(img, logo_path, target_w, target_h)

    img.save(output_path, "PNG", quality=95)
    logger.info("Composed %s → %s", aspect_ratio.value, output_path)
    return output_path


# ── Drawing helpers ────────────────────────────────────────────────────────────

def _cover_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize image to fill target dimensions, cropping from centre."""
    orig_w, orig_h = img.size
    scale = max(target_w / orig_w, target_h / orig_h)
    new_w = int(orig_w * scale)
    new_h = int(orig_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def _draw_gradient_rect(
    draw: ImageDraw.ImageDraw,
    bbox: tuple,
    start_alpha: int,
    end_alpha: int,
    color: tuple,
) -> None:
    x0, y0, x1, y1 = bbox
    height = y1 - y0
    for i in range(height):
        alpha = int(start_alpha + (end_alpha - start_alpha) * (i / height))
        draw.line([(x0, y0 + i), (x1, y0 + i)], fill=(*color, alpha))


def _draw_text_shadow(
    draw: ImageDraw.ImageDraw,
    text: str,
    pos: tuple,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    color: tuple,
    shadow_offset: int = 3,
) -> None:
    x, y = pos
    # Shadow
    draw.multiline_text(
        (x + shadow_offset, y + shadow_offset),
        text,
        font=font,
        fill=(0, 0, 0, 120),
    )
    # Main text
    draw.multiline_text((x, y), text, font=font, fill=(*color, 255))


def _text_height(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> int:
    try:
        bbox = draw.multiline_textbbox((0, 0), text, font=font)
        return bbox[3] - bbox[1]
    except AttributeError:
        _, h = draw.multiline_textsize(text, font=font)  # type: ignore[attr-defined]
        return h


def _truncate_to_fit(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_height: int,
) -> str:
    """Return text truncated (with '...') so it fits within max_height pixels.

    If the full text already fits, it is returned unchanged. Otherwise lines are
    dropped from the bottom until the remaining text fits, and '...' is appended
    to the last visible line.
    """
    if max_height <= 0 or _text_height(draw, text, font) <= max_height:
        return text

    lines = text.split("\n")
    kept: list[str] = []
    for line in lines:
        candidate = "\n".join(kept + [line + "..."])
        if _text_height(draw, candidate, font) <= max_height:
            kept.append(line)
        else:
            break

    if not kept:
        # Even a single line with ellipsis is too tall — truncate character by character
        for i in range(len(lines[0]), 0, -1):
            candidate = lines[0][:i].rstrip() + "..."
            if _text_height(draw, candidate, font) <= max_height:
                return candidate
        return "..."

    kept[-1] = kept[-1].rstrip() + "..."
    return "\n".join(kept)


def _draw_offer_badge(
    draw: ImageDraw.ImageDraw,
    offer: str,
    w: int,
    h: int,
    colors: dict,
) -> None:
    font_size = max(int(w * 0.030), 18)
    font = get_system_font(font_size)
    padding = int(w * 0.015)
    try:
        bbox = draw.textbbox((0, 0), offer, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        tw, th = draw.textsize(offer, font=font)  # type: ignore[attr-defined]

    rx0 = w - tw - padding * 3
    ry0 = int(h * 0.035)
    rx1 = w - int(w * 0.03)
    ry1 = ry0 + th + padding * 2

    draw.rounded_rectangle([(rx0, ry0), (rx1, ry1)], radius=8, fill=(*colors["primary"], 230))
    draw.text(
        (rx0 + padding, ry0 + padding),
        offer,
        font=font,
        fill=(*colors["secondary"][:3], 255),
    )


def _draw_cta(
    draw: ImageDraw.ImageDraw,
    cta: str,
    w: int,
    h: int,
    colors: dict,
    cta_y: int | None = None,
) -> None:
    font_size = max(int(min(w, h * 1.5) * 0.030), 18)
    font = get_system_font(font_size)
    padding_x = int(w * 0.04)
    padding_y = int(h * 0.012)
    try:
        bbox = draw.textbbox((0, 0), cta.upper(), font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        tw, th = draw.textsize(cta.upper(), font=font)  # type: ignore[attr-defined]

    btn_w = tw + padding_x * 2
    btn_h = th + padding_y * 2
    btn_x = int(w * 0.05)
    btn_y = cta_y if cta_y is not None else h - int(h * 0.07) - btn_h

    draw.rounded_rectangle(
        [(btn_x, btn_y), (btn_x + btn_w, btn_y + btn_h)],
        radius=6,
        fill=(*colors["primary"], 230),
    )
    draw.text(
        (btn_x + padding_x, btn_y + padding_y),
        cta.upper(),
        font=font,
        fill=(*colors["secondary"][:3], 255),
    )


def _draw_logo(img: Image.Image, logo_path: str, w: int, h: int) -> None:
    try:
        logo = Image.open(logo_path).convert("RGBA")
        max_logo_w = int(w * 0.14)
        ratio = max_logo_w / logo.width
        logo = logo.resize(
            (max_logo_w, int(logo.height * ratio)),
            Image.LANCZOS,
        )
        margin = int(w * 0.03)
        lx = w - logo.width - margin
        ly = h - logo.height - margin - max(8, h // 120) - 10
        img.paste(logo, (lx, ly), logo)
    except Exception as exc:
        logger.warning("Could not apply logo: %s", exc)
