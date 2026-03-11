# 🎨 Creative Automation Pipeline

A proof-of-concept that automates the generation of localised social ad creatives using GenAI and branded image composition. Built for global consumer goods companies running hundreds of campaigns monthly.

---

## 📺 Demo

> See the pipeline generate 6 branded ad creatives across 3 aspect ratios for 2 products in under 30 seconds — without an API key using the built-in placeholder mode.

---

## ✨ Features

| Feature | Details |
|---|---|
| **Campaign Briefs** | YAML or JSON input — products, region, audience, message, offer, CTA |
| **Multi-product** | Process ≥ 2 products per campaign in a single run |
| **Aspect Ratios** | 1:1 (1080×1080), 9:16 (1080×1920), 16:9 (1920×1080) |
| **AI Image Gen** | DALL-E 3 via OpenAI API (auto-falls back to gradient placeholder) |
| **Asset Reuse** | Detects existing images in `assets/source_images/` — skips generation |
| **Image Composition** | Brand name, campaign message, product name, tagline, offer badge, CTA button, logo |
| **Brand Compliance** | Checks primary colour presence, logo placement, image brightness |
| **Content Check** | Flags prohibited words, claims requiring disclaimers, and unsubstantiated superlatives |
| **HTML Report** | Full campaign report with embedded asset previews and compliance badges |
| **CLI + Web UI** | Run from terminal or browser — both interfaces stream live progress |
| **Organised Output** | `outputs/{campaign_id}/{product}/{ratio}/filename.png` |

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/your-username/creative-automation-pipeline.git
cd creative-automation-pipeline

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure (optional)

```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
# If you skip this step, the pipeline uses gradient placeholders instead of DALL-E
```

### 3a. Run via CLI

```bash
# Run a single campaign brief
python run_pipeline.py --brief briefs/hydraboost_us.yaml

# Run with verbose logging and auto-open the HTML report
python run_pipeline.py --brief briefs/vitacharge_eu.yaml --verbose --open-report

# Use a custom output directory
python run_pipeline.py --brief briefs/hydraboost_us.yaml --output-dir /tmp/my_outputs
```

### 3b. Run via Web UI

```bash
python app.py
# Open http://localhost:8000 in your browser
```

### 3c. Run via Docker

```bash
# Build and start the web UI (reads secrets from .env via env_file)
docker compose up --build

# Or build/run manually
docker build -t creative-pipeline .
docker run -p 8000:8000 --env-file .env creative-pipeline

# Open http://localhost:8000
```

The container runs as a non-root user (`appuser`) for security. Secrets are never baked into the image.
The pipeline works without any API key — gradient placeholder fallback is always available.

---

## 📁 Project Structure

```
creative-automation-pipeline/
├── run_pipeline.py          # CLI entry point (Click)
├── app.py                   # FastAPI web server
├── requirements.txt
├── .env.example
│
├── src/
│   ├── pipeline.py          # Main orchestrator — runs the full workflow
│   ├── models.py            # Pydantic data models (Brief, Product, Result…)
│   ├── image_generator.py   # DALL-E 3 generation + gradient placeholder fallback
│   ├── image_composer.py    # Pillow composition — text, logo, overlays, CTA
│   ├── brand_checker.py     # Brand compliance checks (colour, logo, brightness)
│   ├── content_checker.py   # Prohibited words / legal content scanner
│   ├── reporter.py          # Jinja2 HTML report generator
│   ├── config.py            # Centralised Settings dataclass + load_settings()
│   ├── logging_config.py    # Centralised setup_logging() + log_timing()
│   └── storage/
│       ├── base.py          # StorageBackend ABC
│       ├── local_storage.py # LocalStorageBackend (default — writes to outputs/)
│       └── azure_blob_storage.py  # AzureBlobStorageBackend (STORAGE_BACKEND=azure_blob)
│
├── config/
│   ├── brand_guidelines.json   # Primary/secondary colours, logo placement rules
│   └── prohibited_words.json   # Prohibited words, disclaimer triggers, superlatives
│
├── briefs/
│   ├── hydraboost_us.yaml      # Sample 1 — skincare, US market, 2 products
│   └── vitacharge_eu.yaml      # Sample 2 — beverage + food, EU market, 2 products
│
├── assets/
│   ├── logos/
│   │   └── brand_logo.png      # Brand logo applied to all creatives
│   └── source_images/          # Drop pre-existing product images here for reuse
│
├── static/
│   └── index.html              # Single-page web UI (Tailwind + Vanilla JS)
│
└── outputs/                    # Generated assets (gitignored)
    └── {campaign_id}/
        └── {product_slug}/
            ├── 1x1/
            ├── 9x16/
            └── 16x9/
```

---

## 📋 Example Input

### Campaign Brief (`briefs/hydraboost_us.yaml`)

```yaml
campaign_id: hydraboost_us_summer_2025
brand_name: LuminaCo
target_region: "United States"
target_audience: "Women & men aged 25–45 interested in skincare and wellness"
campaign_message: "Glow from within. Every single day."
offer: "30% OFF"
cta: "Shop Now"
language: en
tone: "aspirational, warm, empowering"

products:
  - name: "HydraBoost Moisturizer"
    description: "Advanced daily moisturizer with hyaluronic acid and SPF 30"
    category: skincare
    tagline: "Hydrate. Protect. Glow."

  - name: "VitaGlow Serum"
    description: "Brightening vitamin C serum that fades dark spots"
    category: skincare
    tagline: "Fade. Brighten. Radiate."
```

### Pre-existing asset reuse

Drop a file named `hydraboost_moisturizer.png` into `assets/source_images/` and the pipeline will detect and reuse it automatically — skipping DALL-E generation for that product.

---

## 📤 Example Output

Running `python run_pipeline.py --brief briefs/hydraboost_us.yaml` produces:

```
outputs/
└── hydraboost_us_summer_2025/
    ├── hydraboost_moisturizer/
    │   ├── 1x1/   hydraboost_moisturizer_1x1.png    (1080×1080 — Instagram Feed)
    │   ├── 9x16/  hydraboost_moisturizer_9x16.png   (1080×1920 — Stories/Reels)
    │   └── 16x9/  hydraboost_moisturizer_16x9.png   (1920×1080 — YouTube/Banner)
    ├── vitaglow_serum/
    │   ├── 1x1/   vitaglow_serum_1x1.png
    │   ├── 9x16/  vitaglow_serum_9x16.png
    │   └── 16x9/  vitaglow_serum_16x9.png
    └── hydraboost_us_summer_2025_report.html        ← Full HTML report
```

Each creative includes:
- Brand name & logo
- Campaign message (large hero text)
- Product name + tagline
- Offer badge (e.g. "30% OFF")
- CTA button (e.g. "SHOP NOW")
- Gold accent strip (brand colour)

---

## 🔧 Key Design Decisions

### 1. Graceful API fallback
The pipeline checks for `OPENAI_API_KEY` at runtime. If absent, `image_generator.py` generates a category-aware gradient placeholder using only Pillow — no external dependencies or API calls required. This enables demos and CI runs with zero cost.

### 2. Asset reuse before generation
`pipeline.py` checks `assets/source_images/` for a filename containing the product name slug before calling DALL-E. This respects existing creative work and reduces API costs — a key requirement for production systems running hundreds of campaigns.

### 3. Aspect-ratio-aware composition
Rather than generating a single image and cropping naively, DALL-E is called with the optimal size per ratio (`1024×1024`, `1024×1792`, `1792×1024`). Pillow then performs a cover-crop resize to reach exact pixel targets. This avoids black bars and maintains focal point integrity.

### 4. Declarative brand guidelines
`config/brand_guidelines.json` and `config/prohibited_words.json` are external config files, not hardcoded values. A brand manager can update them without touching source code — reflecting how these systems work in production.

### 5. SSE-based real-time progress
The FastAPI web endpoint streams pipeline events via Server-Sent Events rather than polling. This gives the user live feedback (which product is being processed, which ratio is being composed) without requiring WebSocket complexity.

### 6. Separation of pipeline stages
Each stage (generation, composition, brand check, content check, reporting) lives in its own module with a clear interface. This makes it easy to swap implementations — e.g. replacing DALL-E with Stable Diffusion, or adding a vector DB for style consistency.

---

## ⚠️ Assumptions & Limitations

| Item | Notes |
|---|---|
| **Image quality** | DALL-E 3 generates excellent hero images but is not product-photography accurate. Real campaigns would use product shots as source assets. |
| **Localisation** | The brief supports `language` and `target_region` fields; currently the text overlay renders in English only. Localized copy would be passed in the brief per-market. |
| **Font rendering** | Uses system Liberation/DejaVu fonts. Production use would bundle a licensed brand font (e.g. via Google Fonts at setup time). |
| **Storage** | Defaults to local filesystem (`outputs/`). Azure Blob Storage is supported out of the box via `STORAGE_BACKEND=azure_blob` + `AZURE_STORAGE_CONNECTION_STRING`. Other providers can be added by implementing `StorageBackend` in `src/storage/`. |
| **Brand colours** | The compliance checker uses a pixel-sampling heuristic. Production-grade checks would use LAB colour space comparison for perceptual accuracy. |
| **DALL-E rate limits** | OpenAI allows ~5 image generations/min on standard tier. Large batch runs should implement a retry/backoff queue (structure is in place). |
| **Cost** | Each DALL-E 3 Standard 1024×1024 image costs ~$0.04. A campaign with 2 products × 3 ratios = 6 API calls (~$0.24). |

---

## 🧩 Extending the Pipeline

**Add a new aspect ratio:**
```python
# src/models.py
class AspectRatio(str, Enum):
    SQUARE    = "1x1"
    PORTRAIT  = "9x16"
    LANDSCAPE = "16x9"
    WIDE      = "4x5"   # ← add here

RATIO_DIMENSIONS[AspectRatio.WIDE] = (864, 1080)
DALLE_SIZES[AspectRatio.WIDE]      = "1024x1024"  # closest supported
```

**Swap the image generator:**
```python
# src/image_generator.py — replace _generate_dalle_image() with:
def _generate_stability_image(product, brief, aspect_ratio, output_path, api_key):
    # Call Stability AI / Imagen / Flux API here
    ...
```

**Switch to Azure Blob Storage:**
```bash
# .env
STORAGE_BACKEND=azure_blob
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
AZURE_STORAGE_CONTAINER=creatives
```

**Add a custom storage backend:**
```python
# src/storage/s3_storage.py
from src.storage.base import StorageBackend

class S3StorageBackend(StorageBackend):
    # Implement save_file, file_exists, get_file, list_files, get_url
    ...
```

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `fastapi` + `uvicorn` | Web server & SSE streaming |
| `openai` | DALL-E 3 image generation |
| `pillow` | Image composition, text overlay, resizing |
| `pyyaml` | Campaign brief parsing |
| `pydantic` | Data validation & models |
| `jinja2` | HTML report templating |
| `click` | CLI interface |
| `python-dotenv` | `.env` configuration |
| `requests` | Downloading DALL-E image URLs |

---

## 📄 License

MIT — feel free to use and extend.
