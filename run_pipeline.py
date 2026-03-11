#!/usr/bin/env python3
"""
run_pipeline.py — CLI entry point for the Creative Automation Pipeline.

Usage:
  python run_pipeline.py --brief briefs/hydraboost_us.yaml
  python run_pipeline.py --brief briefs/vitacharge_eu.yaml --output-dir my_outputs
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

load_dotenv()

# Add project root to path so `src` is importable when run directly
sys.path.insert(0, str(Path(__file__).parent))

from src.config import load_settings
from src.logging_config import setup_logging


@click.command()
@click.option(
    "--brief",
    "-b",
    required=True,
    type=click.Path(exists=True),
    help="Path to campaign brief YAML or JSON file",
)
@click.option(
    "--output-dir",
    "-o",
    default=None,
    help="Override output root directory (default: outputs/)",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.option(
    "--open-report",
    is_flag=True,
    default=False,
    help="Open the HTML report in your browser when done",
)
def main(brief: str, output_dir: str | None, verbose: bool, open_report: bool) -> None:
    """
    \b
    Creative Automation Pipeline
    ─────────────────────────────
    Accepts a campaign brief and produces localised ad creatives
    for all configured aspect ratios (1:1 · 9:16 · 16:9).
    """
    settings = load_settings()
    # --verbose flag overrides the LOG_LEVEL env var for CLI runs
    log_level = "DEBUG" if verbose else settings.log_level
    setup_logging(log_level)

    # Optionally override outputs root
    if output_dir:
        import src.pipeline as _pipeline_module
        from pathlib import Path as _Path
        _pipeline_module.OUTPUTS_ROOT = _Path(output_dir)

    from src.pipeline import load_brief, run_pipeline

    click.echo(click.style("\n🎯 Creative Automation Pipeline", fg="cyan", bold=True))
    click.echo(click.style(f"   Brief: {brief}\n", fg="white"))

    try:
        campaign_brief = load_brief(brief)
    except Exception as exc:
        click.echo(click.style(f"❌ Failed to load brief: {exc}", fg="red"))
        sys.exit(1)

    def progress(*, message: str, user_message: str = "", **kwargs: object) -> None:
        display = user_message or message
        color = "green" if "✅" in display else ("red" if "❌" in display else "white")
        click.echo(click.style(display, fg=color))

    try:
        result = run_pipeline(campaign_brief, progress_cb=progress)
    except (ValueError, ImportError, RuntimeError) as exc:
        click.echo(click.style(f"\n❌ Storage error: {exc}", fg="red"), err=True)
        sys.exit(1)

    # ── Summary ────────────────────────────────────────────────────────────────
    click.echo("")
    click.echo(click.style("─" * 50, fg="cyan"))
    click.echo(click.style("  Pipeline Summary", fg="cyan", bold=True))
    click.echo(click.style("─" * 50, fg="cyan"))
    click.echo(f"  Campaign   : {result.campaign_id}")
    click.echo(f"  Products   : {len(result.product_results)}")
    click.echo(f"  Assets     : {result.total_assets}")
    click.echo(f"  Duration   : {result.duration_seconds}s")
    if result.errors:
        for err in result.errors:
            click.echo(click.style(f"  ⚠️  {err}", fg="yellow"))
    click.echo(click.style("─" * 50, fg="cyan"))

    if result.report_path:
        click.echo(f"\n  📄 Report  : {result.report_path}")

    # Show output paths per product
    for pr in result.product_results:
        click.echo(f"\n  📦 {pr.product.name}")
        for asset in pr.assets:
            status = "✅" if not asset.brand_issues else "⚠️ "
            click.echo(f"     {status} [{asset.aspect_ratio.value}] {asset.path}")

    click.echo("")

    if open_report and result.report_path:
        import webbrowser
        webbrowser.open(f"file://{os.path.abspath(result.report_path)}")

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
