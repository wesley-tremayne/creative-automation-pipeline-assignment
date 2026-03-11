"""
Reporter
--------
Generates an HTML campaign report showing all produced assets,
compliance results, and pipeline metadata.
"""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime

from .models import PipelineResult, AspectRatio, RATIO_LABELS

logger = logging.getLogger(__name__)

REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Campaign Report — {{ result.campaign_id }}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, -apple-system, sans-serif; background: #0f0f13; color: #e2e8f0; min-height: 100vh; }
  header { background: linear-gradient(135deg, #1e1e2e 0%, #2d1b69 100%); padding: 2rem 3rem; border-bottom: 2px solid #7c3aed; }
  header h1 { font-size: 1.75rem; font-weight: 700; color: #a78bfa; }
  header p  { color: #94a3b8; margin-top: .4rem; font-size: .9rem; }
  .meta { display: flex; gap: 2rem; margin-top: 1rem; flex-wrap: wrap; }
  .meta span { background: #1e1b4b; border: 1px solid #4c1d95; border-radius: 6px; padding: .3rem .8rem; font-size: .82rem; color: #c4b5fd; }
  main { padding: 2rem 3rem; max-width: 1400px; margin: 0 auto; }
  h2 { font-size: 1.3rem; color: #7c3aed; margin: 2rem 0 1rem; border-left: 4px solid #7c3aed; padding-left: .75rem; }
  .product-block { background: #1a1a27; border: 1px solid #2d2d4a; border-radius: 12px; margin-bottom: 2rem; overflow: hidden; }
  .product-header { padding: 1.2rem 1.5rem; background: #16162a; border-bottom: 1px solid #2d2d4a; display: flex; align-items: center; gap: 1rem; }
  .product-header h3 { font-size: 1.1rem; color: #e2e8f0; }
  .product-header .cat { background: #312e81; border-radius: 4px; padding: .2rem .6rem; font-size: .75rem; color: #a78bfa; }
  .gen-badge { margin-left: auto; font-size: .75rem; padding: .2rem .6rem; border-radius: 4px; }
  .gen-badge.generated { background: #064e3b; color: #6ee7b7; }
  .gen-badge.existing  { background: #1e3a5f; color: #93c5fd; }
  .assets-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1.5rem; padding: 1.5rem; }
  .asset-card { background: #0a0a12; border: 1px solid #2d2d4a; border-radius: 10px; overflow: hidden; transition: transform .2s; }
  .asset-card:hover { transform: translateY(-3px); }
  .asset-card .img-wrap { background: #0a0a12; display: flex; align-items: center; justify-content: center; }
  .asset-card img { width: 100%; display: block; max-height: 480px; object-fit: contain; }
  .asset-info { padding: 1rem; }
  .ratio-label { font-size: .8rem; color: #7c3aed; font-weight: 600; margin-bottom: .4rem; }
  .filename { font-size: .75rem; color: #64748b; font-family: monospace; margin-bottom: .8rem; word-break: break-all; }
  .compliance { display: flex; flex-direction: column; gap: .4rem; }
  .badge { display: inline-flex; align-items: center; gap: .3rem; font-size: .75rem; padding: .25rem .6rem; border-radius: 4px; }
  .badge.pass   { background: #064e3b; color: #6ee7b7; }
  .badge.fail   { background: #7f1d1d; color: #fca5a5; }
  .badge.warn   { background: #78350f; color: #fcd34d; }
  .issue-list { margin-top: .5rem; padding-left: 1rem; }
  .issue-list li { font-size: .72rem; color: #f87171; margin-bottom: .2rem; }
  .warn-list li  { color: #fcd34d; }
  footer { text-align: center; padding: 2rem; color: #475569; font-size: .8rem; border-top: 1px solid #1e1e2e; margin-top: 3rem; }
  .summary-bar { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1rem; margin: 1.5rem 0; }
  .stat { background: #1a1a27; border: 1px solid #2d2d4a; border-radius: 10px; padding: 1.2rem; text-align: center; }
  .stat .value { font-size: 2rem; font-weight: 700; color: #a78bfa; }
  .stat .label { font-size: .8rem; color: #64748b; margin-top: .3rem; }
  .cost-section { background: #1a1a27; border: 1px solid #2d2d4a; border-radius: 10px; padding: 1.2rem; margin: 1rem 0 1.5rem; }
  .cost-section h3 { font-size: .85rem; color: #94a3b8; text-transform: uppercase; letter-spacing: .05em; margin-bottom: .8rem; }
  .cost-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: .75rem; }
  .cost-stat { text-align: center; }
  .cost-stat .value { font-size: 1.4rem; font-weight: 700; }
  .cost-stat .value.amber { color: #fbbf24; }
  .cost-stat .value.green { color: #4ade80; }
  .cost-stat .value.gray  { color: #94a3b8; }
  .cost-stat .label { font-size: .75rem; color: #64748b; margin-top: .2rem; }
  .fallback-note { font-size: .72rem; color: #64748b; margin-left: .3rem; }
</style>
</head>
<body>
<header>
  <h1>📊 Campaign Report — {{ result.campaign_id }}</h1>
  <p>Generated {{ generated_at }}</p>
  <div class="meta">
    <span>🏷 {{ result.brand_name }}</span>
    <span>⏱ {{ "%.1f"|format(result.duration_seconds) }}s</span>
    <span>🖼 {{ result.total_assets }} assets</span>
    <span>📦 {{ result.product_results|length }} products</span>
    {% if result.success %}<span style="color:#6ee7b7">✅ Pipeline Success</span>
    {% else %}<span style="color:#fca5a5">❌ Pipeline Errors</span>{% endif %}
    {% if brand_config %}<span>📐 Brand: {{ brand_config }}</span>{% endif %}
    {% if content_config %}<span>📝 Content: {{ content_config }}</span>{% endif %}
  </div>
</header>
<main>

  <div class="summary-bar">
    <div class="stat"><div class="value">{{ result.product_results|length }}</div><div class="label">Products</div></div>
    <div class="stat"><div class="value">{{ result.total_assets }}</div><div class="label">Total Assets</div></div>
    <div class="stat"><div class="value">{{ compliant_count }}</div><div class="label">Brand Compliant</div></div>
    <div class="stat"><div class="value">{{ "%.1f"|format(result.duration_seconds) }}s</div><div class="label">Pipeline Time</div></div>
  </div>

  <div class="cost-section">
    <h3>Image Generation</h3>
    <div class="cost-grid">
      <div class="cost-stat">
        <div class="value amber">
          ${{ "%.4f"|format(result.image_metrics.estimated_cost_usd) }}
          {% if result.image_metrics.dall_e_images == 0 %}<span class="fallback-note">(fallback)</span>{% endif %}
        </div>
        <div class="label">Estimated Cost</div>
      </div>
      <div class="cost-stat">
        <div class="value green">{{ result.image_metrics.dall_e_images }}</div>
        <div class="label">AI Images</div>
      </div>
      <div class="cost-stat">
        <div class="value gray">{{ result.image_metrics.fallback_images }}</div>
        <div class="label">Fallback Images</div>
      </div>
      {% if result.image_metrics.dall_e_images > 0 %}
      <div class="cost-stat">
        <div class="value" style="color:#e2e8f0">{{ result.image_metrics.total_tokens }}</div>
        <div class="label">Total Tokens</div>
      </div>
      <div class="cost-stat">
        <div class="value gray">{{ result.image_metrics.input_tokens }}</div>
        <div class="label">Input Tokens</div>
      </div>
      <div class="cost-stat">
        <div class="value gray">{{ result.image_metrics.output_tokens }}</div>
        <div class="label">Output Tokens</div>
      </div>
      {% endif %}
    </div>
  </div>

  {% for pr in result.product_results %}
  <h2>{{ pr.product.name }}</h2>
  <div class="product-block">
    <div class="product-header">
      <div>
        <h3>{{ pr.product.name }}</h3>
        <div style="font-size:.8rem;color:#94a3b8;margin-top:.25rem">{{ pr.product.description }}</div>
      </div>
      <span class="cat">{{ pr.product.category }}</span>
      {% if pr.generated_image %}
      <span class="gen-badge generated">🎨 AI Generated</span>
      {% else %}
      <span class="gen-badge existing">📁 Existing Asset</span>
      {% endif %}
    </div>
    <div class="assets-grid">
      {% for asset in pr.assets %}
      <div class="asset-card">
        <div class="img-wrap">
          {% if b64_map.get(asset.path) %}
          <img src="data:image/png;base64,{{ b64_map[asset.path] }}" alt="{{ asset.filename }}">
          {% else %}
          <div style="height:200px;width:100%;display:flex;align-items:center;justify-content:center;color:#475569">No preview</div>
          {% endif %}
        </div>
        <div class="asset-info">
          <div class="ratio-label">{{ ratio_labels[asset.aspect_ratio] }}</div>
          <div class="filename">{{ asset.filename }}</div>
          <div class="compliance">
            {% if not asset.brand_issues %}
            <span class="badge pass">✓ Brand Compliant</span>
            {% else %}
            <span class="badge fail">✗ Brand Issues</span>
            <ul class="issue-list">{% for i in asset.brand_issues %}<li>{{ i }}</li>{% endfor %}</ul>
            {% endif %}
            {% if not asset.content_issues %}
            <span class="badge pass">✓ Content Clear</span>
            {% else %}
            <span class="badge warn">⚠ Content Flags</span>
            <ul class="issue-list warn-list">{% for i in asset.content_issues %}<li>{{ i.word }}: {{ i.reason }}</li>{% endfor %}</ul>
            {% endif %}
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>
  {% endfor %}

  {% if result.errors %}
  <h2>Pipeline Errors</h2>
  <div style="background:#1f0000;border:1px solid #7f1d1d;border-radius:8px;padding:1rem;margin-bottom:1rem">
    {% for e in result.errors %}<p style="color:#fca5a5;font-size:.85rem;margin-bottom:.4rem">❌ {{ e }}</p>{% endfor %}
  </div>
  {% endif %}

</main>
<footer>Creative Automation Pipeline — {{ result.brand_name }} — {{ generated_at }}</footer>
</body>
</html>"""


def generate_report(
    result: PipelineResult,
    output_dir: str,
    brand_config: str | None = None,
    content_config: str | None = None,
) -> str:
    """Render an HTML report and save it. Returns the report path."""
    try:
        from jinja2 import Environment
    except ImportError:
        logger.warning("jinja2 not available, skipping report generation")
        return ""

    env = Environment(autoescape=True)
    template = env.from_string(REPORT_TEMPLATE)

    # Build base64 previews keyed by asset path (don't mutate Pydantic models)
    b64_map: dict[str, str] = {}
    for pr in result.product_results:
        for asset in pr.assets:
            try:
                with open(asset.path, "rb") as f:
                    b64_map[asset.path] = base64.b64encode(f.read()).decode()
            except Exception:
                pass

    compliant_count = sum(
        1
        for pr in result.product_results
        for a in pr.assets
        if not a.brand_issues
    )

    html = template.render(
        result=result,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ratio_labels={r: RATIO_LABELS[r] for r in AspectRatio},
        compliant_count=compliant_count,
        b64_map=b64_map,
        brand_config=brand_config,
        content_config=content_config,
    )

    report_path = os.path.join(output_dir, f"{result.campaign_id}_report.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("Report saved → %s", report_path)
    return report_path
