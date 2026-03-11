"""
Creative Automation Pipeline — public API.

Exports the main entry points used by CLI and web server callers.
"""
from .models import CampaignBrief, PipelineResult
from .pipeline import load_brief, run_pipeline

__all__ = ["CampaignBrief", "PipelineResult", "run_pipeline", "load_brief"]
