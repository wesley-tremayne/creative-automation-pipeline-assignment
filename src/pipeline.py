"""
Pipeline
--------
Orchestrates the full creative automation workflow:

  1. Load & validate campaign brief
  2. Run content/legal checks on all text
  3. For each product:
     a. Locate or generate a base hero image
     b. For each of the 3 aspect ratios:
        - Compose the ad creative (text, logo, overlays)
        - Run brand compliance check
        - Save to organised output folder via storage backend
  4. Generate an HTML campaign report

The storage backend is injected via the `storage` parameter of `run_pipeline()`.
By default it uses the backend configured by `STORAGE_BACKEND` env var (local filesystem).
Image composition and report generation still write to local temp paths; this module
saves the final outputs through the storage interface.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

import yaml

from .brand_checker import check_brand_compliance
from .config_manager import validate_brand_guidelines
from .content_checker import check_content
from .error_catalog import get_user_error
from .image_composer import compose_creative
from .image_generator import generate_base_image, reset_api_status
from .logging_config import log_timing
from .models import (
    AspectRatio,
    AssetResult,
    CampaignBrief,
    PipelineResult,
    Product,
    ProductResult,
)
from .reporter import generate_report
from .storage import StorageBackend, get_storage_backend

logger = logging.getLogger(__name__)

ASSETS_DIR   = Path(__file__).parent.parent / "assets"
LOGOS_DIR    = ASSETS_DIR / "logos"
CONFIG_DIR   = Path(__file__).parent.parent / "config"
OUTPUTS_ROOT = Path(__file__).parent.parent / "outputs"


def load_brief(path: str) -> CampaignBrief:
    """Parse a YAML or JSON campaign brief file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Brief file not found: {path}\n"
            f"  Hint: Check the path and ensure the file exists. "
            f"Briefs are typically in the briefs/ directory."
        )
    if p.suffix not in (".yaml", ".yml", ".json"):
        raise ValueError(
            f"Unsupported brief format: '{p.suffix}'\n"
            f"  Supported formats: .yaml, .yml, .json"
        )
    try:
        with open(p) as f:
            if p.suffix in (".yaml", ".yml"):
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Failed to parse brief '{p.name}': {exc}\n"
            f"  Hint: Check the file for syntax errors."
        ) from exc
    if not data:
        raise ValueError(
            f"Brief file is empty: {p.name}\n"
            f"  Hint: The file must contain a valid campaign brief."
        )
    try:
        return CampaignBrief(**data)
    except Exception as exc:
        raise ValueError(
            f"Invalid brief structure in '{p.name}': {exc}\n"
            f"  Required fields: campaign_id, products, target_region, "
            f"target_audience, campaign_message"
        ) from exc


def load_brand_guidelines(profile_name: Optional[str] = None) -> dict:
    """Load brand guidelines from config, falling back to sensible defaults.

    If profile_name is given, loads config/brand_guidelines_{profile_name}.json.
    Otherwise loads the default config/brand_guidelines.json.
    """
    if profile_name:
        config_path = CONFIG_DIR / f"brand_guidelines_{profile_name}.json"
    else:
        config_path = CONFIG_DIR / "brand_guidelines.json"
    if not config_path.exists():
        logger.warning(
            "brand_guidelines.json not found at %s — using default colours. "
            "Create config/brand_guidelines.json to customise.",
            config_path,
        )
        return {
            "primary_color":   [255, 195, 0],
            "secondary_color": [20,  20,  20],
            "text_color":      [255, 255, 255],
        }
    try:
        with open(config_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        logger.error(
            "Failed to parse brand_guidelines.json: %s — using defaults", exc
        )
        return {
            "primary_color":   [255, 195, 0],
            "secondary_color": [20,  20,  20],
            "text_color":      [255, 255, 255],
        }
    errors = validate_brand_guidelines(data)
    if errors:
        logger.warning(
            "Brand guidelines validation issues: %s — using file as-is",
            "; ".join(errors),
        )
    return data


def _find_existing_asset(product_name: str) -> Optional[str]:
    """Search assets/source_images for a file matching the product (case-insensitive)."""
    source_dir = ASSETS_DIR / "source_images"
    if not source_dir.exists():
        return None
    slug = product_name.lower().replace(" ", "_")
    for ext in ("png", "jpg", "jpeg", "webp"):
        for candidate in source_dir.glob(f"*.{ext}"):
            if slug in candidate.stem.lower() or candidate.stem.lower() in slug:
                return str(candidate)
    return None


def _make_output_dirs(campaign_id: str, product_name: str) -> dict[AspectRatio, str]:
    """Create output directories and return paths keyed by aspect ratio."""
    slug = product_name.lower().replace(" ", "_").replace("/", "-")
    dirs: dict[AspectRatio, str] = {}
    for ratio in AspectRatio:
        d = OUTPUTS_ROOT / campaign_id / slug / ratio.value
        d.mkdir(parents=True, exist_ok=True)
        dirs[ratio] = str(d)
    return dirs


def _generate_text_logo(brand_name: str, output_path: str) -> str:
    """Generate a simple text-based logo on a transparent background using Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    width, height = 400, 120
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Try to use a reasonable font size
    font_size = 48
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), brand_name, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) // 2
    y = (height - text_h) // 2

    draw.text((x, y), brand_name, fill=(255, 255, 255, 255), font=font)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    logger.info("Generated text logo → %s", output_path)
    return output_path


def _resolve_logo(brief: CampaignBrief, emit: Callable[..., None]) -> Optional[str]:
    """Resolve the logo path based on brief.logo field."""
    if brief.logo is None:
        logger.info("No logo specified — creatives will not include a logo")
        return None

    if brief.logo == "generate":
        logo_out = str(
            OUTPUTS_ROOT / brief.campaign_id / "_logos" / "generated_logo.png"
        )
        emit(
            f"🎨 Generating text logo for '{brief.brand_name}'...",
            user_message=f"🎨 Creating a logo for {brief.brand_name}...",
        )
        return _generate_text_logo(brief.brand_name, logo_out)

    # Treat as a filename in LOGOS_DIR (patchable for test isolation)
    logo_file = LOGOS_DIR / brief.logo
    if logo_file.exists():
        # Copy to campaign output folder for reproducibility
        logo_out = str(
            OUTPUTS_ROOT / brief.campaign_id / "_logos" / brief.logo
        )
        Path(logo_out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(logo_file), logo_out)
        logger.info("Copied logo to campaign folder → %s", logo_out)
        return logo_out

    logger.warning("Logo file not found: %s — running without logo", logo_file)
    emit(
        f"⚠️  Logo file not found: {brief.logo}",
        user_message="⚠️  The specified logo file wasn't found — continuing without a logo",
    )
    return None


def run_pipeline(
    brief: CampaignBrief,
    progress_cb: Optional[Callable[..., None]] = None,
    storage: Optional[StorageBackend] = None,
) -> PipelineResult:
    """
    Execute the full pipeline for every product in the brief.

    Args:
        brief: Validated campaign brief.
        progress_cb: Optional callback receiving keyword arguments:
            - message: technical log string (always present)
            - user_message: friendly UI string (present when different from message)
            - error_code: reference code (present on errors)
        storage: Storage backend for saving outputs. Defaults to the backend
            configured by STORAGE_BACKEND env var (local filesystem).

    Returns:
        PipelineResult with all generated asset paths and compliance results.
    """
    t_start = time.time()
    storage = storage or get_storage_backend()
    reset_api_status()

    def emit(
        msg: str,
        *,
        user_message: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> None:
        """Emit a progress event with both technical and user-friendly messages."""
        logger.info(msg)
        if progress_cb:
            try:
                progress_cb(
                    message=msg,
                    user_message=user_message or msg,
                    error_code=error_code,
                )
            except TypeError:
                # Backwards compatibility: caller using old str-only signature
                progress_cb(msg)

    emit(
        f"🚀 Starting pipeline for campaign '{brief.campaign_id}' ({len(brief.products)} products)",
        user_message=f"🚀 Starting your campaign with {len(brief.products)} product(s)...",
    )

    brand_guidelines = load_brand_guidelines(brief.brand_config)
    logo_path = _resolve_logo(brief, emit)

    result = PipelineResult(
        campaign_id=brief.campaign_id,
        brand_name=brief.brand_name,
    )

    # ── Content / legal check ──────────────────────────────────────────────────
    with log_timing("Content & legal checks", logger):
        emit(
            "📋 Running content & legal checks...",
            user_message="📋 Reviewing your content for compliance...",
        )
        content_issues = check_content(brief, config_name=brief.content_config)
        if content_issues:
            emit(
                f"  ⚠️  {len(content_issues)} content flag(s) found",
                user_message=f"  ⚠️  {len(content_issues)} item(s) flagged for review",
            )
        else:
            emit(
                "  ✅ Content checks passed",
                user_message="  ✅ Content looks good!",
            )

    # ── Per-product loop ───────────────────────────────────────────────────────
    for idx, product in enumerate(brief.products, 1):
        emit(
            f"\n📦 [{idx}/{len(brief.products)}] Processing product: {product.name}",
            user_message=f"\n📦 Working on product {idx} of {len(brief.products)}: {product.name}",
        )
        pr = ProductResult(product=product)

        try:
            _process_product(
                product=product,
                brief=brief,
                pr=pr,
                result=result,
                brand_guidelines=brand_guidelines,
                logo_path=logo_path,
                content_issues=content_issues,
                emit=emit,
            )
        except Exception as exc:
            err = f"Product '{product.name}' failed: {exc}"
            logger.exception(err)
            pr.error = err
            result.errors.append(err)
            emit(
                f"  ❌ {err} — continuing with remaining products",
                user_message=get_user_error("ERR-PRODUCT-001"),
                error_code="ERR-PRODUCT-001",
            )

        result.product_results.append(pr)

    # ── Aggregate campaign-level image metrics ────────────────────────────────
    for pr in result.product_results:
        m = pr.image_metrics
        result.image_metrics.dall_e_images += m.dall_e_images
        result.image_metrics.fallback_images += m.fallback_images
        result.image_metrics.input_tokens += m.input_tokens
        result.image_metrics.output_tokens += m.output_tokens
        result.image_metrics.total_tokens += m.total_tokens
        result.image_metrics.estimated_cost_usd += m.estimated_cost_usd
        for size, count in m.images_by_size.items():
            result.image_metrics.images_by_size[size] = (
                result.image_metrics.images_by_size.get(size, 0) + count
            )
    result.image_metrics.estimated_cost_usd = round(result.image_metrics.estimated_cost_usd, 6)

    # ── Generate report ────────────────────────────────────────────────────────
    with log_timing("Report generation", logger):
        emit(
            "\n📊 Generating HTML report...",
            user_message="\n📊 Building your campaign summary report...",
        )
        report_dir = str(OUTPUTS_ROOT / brief.campaign_id)
        try:
            report_path = generate_report(
                result,
                report_dir,
                brand_config=brief.brand_config,
                content_config=brief.content_config,
            )
            result.report_path = report_path
            emit(
                f"  📄 Report saved → {report_path}",
                user_message="  📄 Summary report is ready!",
            )
        except Exception as exc:
            logger.exception("Report generation failed: %s", exc)
            result.errors.append(f"Report generation failed: {exc}")
            emit(
                f"  ❌ Report generation failed: {exc}",
                user_message=get_user_error("ERR-REPORT-001"),
                error_code="ERR-REPORT-001",
            )

    # ── Write campaign manifest ──────────────────────────────────────────────
    manifest = {
        "campaign_id": brief.campaign_id,
        "brand_name": brief.brand_name,
        "products": [p.name for p in brief.products],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "asset_count": result.total_assets,
        "image_metrics": result.image_metrics.model_dump(),
    }
    manifest_dest = f"{brief.campaign_id}/campaign_manifest.json"
    try:
        manifest_bytes = json.dumps(manifest, indent=2).encode()
        saved_path = storage.save_file(manifest_bytes, manifest_dest)
        emit(
            f"  📋 Manifest saved → {saved_path}",
            user_message="  📋 Campaign data saved",
        )
    except Exception as exc:
        logger.exception("Failed to write campaign manifest: %s", exc)
        emit(
            f"  ⚠️  Failed to write manifest: {exc}",
            user_message=get_user_error("ERR-MANIFEST-001"),
            error_code="ERR-MANIFEST-001",
        )

    # ── Save original brief for reuse ───────────────────────────────────────
    brief_dest = f"{brief.campaign_id}/brief.json"
    try:
        brief_bytes = json.dumps(brief.model_dump(mode="json"), indent=2).encode()
        brief_saved = storage.save_file(brief_bytes, brief_dest)
        logger.info("Brief saved → %s", brief_saved)
    except Exception as exc:
        logger.exception("Failed to save brief.json: %s", exc)

    result.duration_seconds = round(time.time() - t_start, 2)
    result.success = not bool(result.errors)

    emit(
        f"\n✅ Pipeline complete — {result.total_assets} assets in "
        f"{result.duration_seconds}s",
        user_message=f"\n✅ All done! {result.total_assets} ad creative(s) generated in {result.duration_seconds}s",
    )
    return result


def _process_product(
    product: Product,
    brief: CampaignBrief,
    pr: ProductResult,
    result: PipelineResult,
    brand_guidelines: dict,
    logo_path: Optional[str],
    content_issues: list,
    emit: Callable[..., None],
) -> None:
    """Process a single product — extracted for per-product error isolation."""
    with log_timing(f"Product '{product.name}'", logger):
        # ── 1. Resolve base image ─────────────────────────────────────────────
        if product.existing_asset:
            asset = product.existing_asset
            source_dir = (ASSETS_DIR / "source_images").resolve()
            asset_full = Path(ASSETS_DIR / "source_images" / asset).resolve()
            # Verify resolved path stays within assets/source_images/ (traversal guard)
            if not str(asset_full).startswith(str(source_dir) + "/") and str(asset_full) != str(source_dir):
                emit(
                    f"  ⚠️  Rejected existing_asset path traversal attempt: {asset}",
                    user_message="  ⚠️  Invalid asset path — will create a new image",
                )
            elif asset_full.exists():
                pr.base_image_path = str(asset_full)
                emit(
                    f"  📁 Using existing asset: {asset}",
                    user_message=f"  📁 Found an existing image for {product.name}",
                )
            else:
                emit(
                    f"  ⚠️  Declared asset not found: {asset}",
                    user_message="  ⚠️  Existing image not found — will create a new one",
                )

        if not pr.base_image_path:
            pr.base_image_path = _find_existing_asset(product.name)
            if pr.base_image_path:
                emit(
                    f"  📁 Found matching asset: {Path(pr.base_image_path).name}",
                    user_message=f"  📁 Found an existing image for {product.name}",
                )

        # Generate base image for first ratio that needs it (reused for all ratios)
        if not pr.base_image_path:
            base_gen_path = str(
                OUTPUTS_ROOT / brief.campaign_id / "_base_images" /
                f"{product.name.lower().replace(' ','_')}_base.png"
            )
            Path(base_gen_path).parent.mkdir(parents=True, exist_ok=True)
            with log_timing(f"Image generation for '{product.name}'", logger):
                pr.base_image_path, img_meta = generate_base_image(
                    product, brief, AspectRatio.SQUARE, base_gen_path, emit
                )
            pr.generated_image = True

            # Populate per-product image metrics
            size = img_meta.get("size", "1024x1024")
            cost = img_meta.get("cost_usd", 0.0)
            in_tok = img_meta.get("input_tokens", 0)
            out_tok = img_meta.get("output_tokens", 0)
            tot_tok = img_meta.get("total_tokens", in_tok + out_tok)
            if img_meta.get("method") == "dall-e":
                pr.image_metrics.dall_e_images += 1
                pr.image_metrics.images_by_size[size] = pr.image_metrics.images_by_size.get(size, 0) + 1
                pr.image_metrics.input_tokens += in_tok
                pr.image_metrics.output_tokens += out_tok
                pr.image_metrics.total_tokens += tot_tok
                pr.image_metrics.estimated_cost_usd += cost
                token_source = img_meta.get("token_source", "actual")
                cost_label = f"${cost:.4f}" + (" (estimated)" if token_source == "estimated" else "")
                emit(
                    f"  💰 Generated image for {product.name} — {tot_tok} tokens [{token_source}], {cost_label}",
                    user_message=f"  💰 AI image generated for {product.name} — {tot_tok} tokens, {cost_label}",
                )
            else:
                pr.image_metrics.fallback_images += 1

        # ── 2. Compose each aspect ratio ──────────────────────────────────────
        output_dirs = _make_output_dirs(brief.campaign_id, product.name)

        ratio_labels = {
            AspectRatio.SQUARE: "square",
            AspectRatio.PORTRAIT: "portrait",
            AspectRatio.LANDSCAPE: "landscape",
        }

        for ratio in AspectRatio:
            label = ratio_labels.get(ratio, ratio.value)
            emit(
                f"  🖼  Composing {ratio.value}...",
                user_message=f"  🖼  Creating {label} ad image...",
            )
            filename = f"{product.name.lower().replace(' ','_')}_{ratio.value}.png"
            output_path = os.path.join(output_dirs[ratio], filename)

            try:
                with log_timing(f"Compose {product.name} {ratio.value}", logger):
                    compose_creative(
                        base_image_path=pr.base_image_path,
                        product=product,
                        brief=brief,
                        aspect_ratio=ratio,
                        output_path=output_path,
                        brand_guidelines=brand_guidelines,
                        logo_path=logo_path,
                    )
            except Exception as exc:
                err = f"Compose failed for {product.name} {ratio.value}: {exc}"
                logger.exception(err)
                result.errors.append(err)
                emit(
                    f"  ❌ {err}",
                    user_message=get_user_error("ERR-COMPOSE-001"),
                    error_code="ERR-COMPOSE-001",
                )
                continue

            # ── 3. Brand compliance check ─────────────────────────────────────
            brand_issues = check_brand_compliance(
                output_path, brand_guidelines, has_logo=bool(logo_path)
            )

            asset = AssetResult(
                path=output_path,
                filename=filename,
                aspect_ratio=ratio,
                brand_compliant=not brand_issues,
                brand_issues=brand_issues,
                content_issues=content_issues,
            )
            pr.assets.append(asset)
            result.total_assets += 1
