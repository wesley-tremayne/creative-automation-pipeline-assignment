"""
app.py — FastAPI web server for the Creative Automation Pipeline.

Serves:
  • GET  /              → Web UI (static/index.html)
  • GET  /api/samples   → List sample briefs
  • POST /api/run       → Run pipeline, stream progress via SSE
  • GET  /api/outputs/{path} → Serve generated images
  • GET  /api/report/{campaign_id} → Serve HTML report
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from src.config import load_settings
from src.config_manager import validate_brand_guidelines, validate_prohibited_words
from src.error_catalog import get_user_error
from src.logging_config import setup_logging
from src.models import CampaignBrief
from src.pipeline import OUTPUTS_ROOT, run_pipeline
from src.storage import StorageBackend, get_storage_backend

settings = load_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

logger.info(
    "Creative Automation Pipeline starting — storage: %s, OpenAI: %s",
    settings.storage_backend,
    "configured" if settings.has_openai_key() else "not configured (gradient fallback)",
)

_storage_backend: StorageBackend | None = None


def _get_storage() -> StorageBackend:
    """Return the configured storage backend (lazy singleton)."""
    global _storage_backend
    if _storage_backend is None:
        _storage_backend = get_storage_backend()
    return _storage_backend


def _is_azure() -> bool:
    """Return True if Azure Blob Storage is the configured backend."""
    return settings.storage_backend == "azure_blob"

app = FastAPI(title="Creative Automation Pipeline", version="1.0.0")


@app.middleware("http")
async def log_requests(request: Request, call_next):  # type: ignore[type-arg]
    """Log each HTTP request with method, path, status code, and duration."""
    start = time.time()
    response = await call_next(request)
    duration = round(time.time() - start, 3)
    logger.info(
        "%s %s → %s (%.3fs)",
        request.method,
        request.url.path,
        response.status_code,
        duration,
    )
    return response


@app.middleware("http")
async def add_security_headers(request: Request, call_next):  # type: ignore[type-arg]
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "frame-ancestors 'none';"
    )
    return response


BASE_DIR    = Path(__file__).parent
STATIC_DIR  = BASE_DIR / "static"
LOGOS_DIR   = BASE_DIR / "assets" / "logos"
CONFIG_DIR  = BASE_DIR / "config"

# Mount static sub-directories so /static/js/ and /static/css/ are served correctly
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Static files & SPA root ────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text())


# ── API routes ─────────────────────────────────────────────────────────────────

ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg", "image/svg+xml"}
MAX_LOGO_SIZE = 5 * 1024 * 1024  # 5MB


@app.post("/api/upload/logo")
async def upload_logo(file: UploadFile) -> dict:
    """Upload a logo image. Returns the filename for use in the brief."""
    if file.content_type not in ALLOWED_LOGO_TYPES:
        raise HTTPException(400, f"Invalid file type: {file.content_type}. Allowed: PNG, JPG, SVG.")
    contents = await file.read()
    if len(contents) > MAX_LOGO_SIZE:
        raise HTTPException(400, "File too large. Maximum size is 5MB.")
    ext = Path(file.filename).suffix if file.filename else ".png"
    safe_name = f"{uuid.uuid4().hex}{ext}"
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    dest = LOGOS_DIR / safe_name
    dest.write_bytes(contents)
    logger.info("Logo uploaded: %s", safe_name)
    return {"filename": safe_name}


@app.post("/api/run")
async def run_campaign(request: Request) -> StreamingResponse:
    """
    Accept a campaign brief (JSON body) and stream pipeline progress via SSE.
    The final SSE event has type 'result' and contains the PipelineResult JSON.
    """
    body = await request.json()
    try:
        brief = CampaignBrief(**body)
    except Exception as exc:
        logger.error("Invalid brief: %s", exc)
        raise HTTPException(422, get_user_error("ERR-BRIEF-001"))

    async def event_stream() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        def progress_cb(
            *,
            message: str,
            user_message: str = "",
            error_code: str | None = None,
        ) -> None:
            payload: dict = {
                "type": "progress",
                "message": message,
                "user_message": user_message or message,
            }
            if error_code:
                payload["error_code"] = error_code
            queue.put_nowait(f"data: {json.dumps(payload)}\n\n")

        async def run_in_thread() -> None:
            loop = asyncio.get_event_loop()
            try:
                result = await loop.run_in_executor(None, run_pipeline, brief, progress_cb)
                queue.put_nowait(
                    f"data: {json.dumps({'type': 'result', 'data': result.model_dump()})}\n\n"
                )
            except Exception as exc:
                logger.error("Pipeline error: %s", exc, exc_info=True)
                queue.put_nowait(
                    f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
                )
            finally:
                queue.put_nowait(None)  # sentinel — always unblocks the stream

        task = asyncio.create_task(run_in_thread())

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

        await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/outputs/{campaign_id}/{product}/{ratio}/{filename}")
async def serve_output(
    campaign_id: str, product: str, ratio: str, filename: str
) -> FileResponse:
    _validate_path_segment(campaign_id, "campaign_id")
    _validate_path_segment(product, "product")
    _validate_path_segment(ratio, "ratio")
    _validate_path_segment(filename, "filename")
    path = OUTPUTS_ROOT / campaign_id / product / ratio / filename
    resolved = path.resolve()
    outputs_root = OUTPUTS_ROOT.resolve()
    if not str(resolved).startswith(str(outputs_root) + "/"):
        raise HTTPException(400, "Invalid file path")
    if not resolved.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(str(resolved))


@app.get("/api/report/{campaign_id}")
async def serve_report(campaign_id: str) -> HTMLResponse:
    _validate_campaign_id(campaign_id)
    report_path = OUTPUTS_ROOT / campaign_id / f"{campaign_id}_report.html"
    resolved = report_path.resolve()
    outputs_root = OUTPUTS_ROOT.resolve()
    if not str(resolved).startswith(str(outputs_root) + "/"):
        raise HTTPException(400, "Invalid report path")
    if not resolved.exists():
        raise HTTPException(404, "Report not found")
    return HTMLResponse(resolved.read_text())


def _validate_path_segment(segment: str, name: str = "segment") -> None:
    """Reject path traversal and injection characters in a single path segment.

    Rejects: '..', '/', '\\', null bytes. Raises HTTP 400 on violation.
    """
    if ".." in segment or "/" in segment or "\\" in segment or "\x00" in segment:
        raise HTTPException(400, f"Invalid {name}: contains illegal characters")


def _validate_campaign_id(campaign_id: str) -> None:
    """Reject path traversal attempts in campaign_id."""
    if "/" in campaign_id or "\\" in campaign_id or ".." in campaign_id:
        raise HTTPException(400, "Invalid campaign ID")


@app.get("/api/campaigns/{campaign_id}/brief")
async def get_campaign_brief(campaign_id: str) -> dict:
    """Return the original brief JSON for a campaign, if available."""
    _validate_campaign_id(campaign_id)
    if _is_azure():
        try:
            data = _get_storage().get_file(f"{campaign_id}/brief.json")
            return json.loads(data)
        except FileNotFoundError:
            raise HTTPException(404, "Brief not available for this campaign")
    brief_path = OUTPUTS_ROOT / campaign_id / "brief.json"
    if not brief_path.exists():
        raise HTTPException(404, "Brief not available for this campaign")
    return json.loads(brief_path.read_text())


@app.delete("/api/campaigns/{campaign_id}", status_code=204, response_model=None)
async def delete_campaign(campaign_id: str) -> None:
    """Delete a campaign and all its assets from the configured storage backend."""
    _validate_campaign_id(campaign_id)
    if _is_azure():
        storage = _get_storage()
        blobs = storage.list_files(f"{campaign_id}/")
        if not blobs:
            raise HTTPException(404, "Campaign not found")
        for blob in blobs:
            try:
                storage.delete_file(blob)
            except FileNotFoundError:
                pass
        logger.info("Deleted campaign from Azure: %s", campaign_id)
        return
    campaign_dir = OUTPUTS_ROOT / campaign_id
    if not campaign_dir.exists() or not campaign_dir.is_dir():
        raise HTTPException(404, "Campaign not found")
    shutil.rmtree(campaign_dir)
    logger.info("Deleted campaign: %s", campaign_id)


@app.get("/api/campaigns")
async def list_campaigns() -> dict:
    """List all previously run campaigns from the configured storage backend."""
    campaigns = []

    if _is_azure():
        storage = _get_storage()
        all_blobs = storage.list_files("")
        # Find campaign IDs by locating campaign_manifest.json blobs
        manifest_blobs = [b for b in all_blobs if b.endswith("/campaign_manifest.json")]
        for blob_name in sorted(manifest_blobs):
            campaign_id = blob_name.split("/")[0]
            if campaign_id.startswith("_"):
                continue
            report_blob = f"{campaign_id}/{campaign_id}_report.html"
            png_blobs = [b for b in all_blobs if b.startswith(f"{campaign_id}/") and b.endswith(".png")]
            entry: dict = {
                "campaign_id": campaign_id,
                "asset_count": len([b for b in png_blobs if "_base_" not in b]),
                "has_report": report_blob in all_blobs,
            }
            try:
                manifest = json.loads(storage.get_file(blob_name))
                entry["brand_name"] = manifest.get("brand_name")
                entry["product_count"] = len(manifest.get("products", []))
                entry["created_at"] = manifest.get("created_at")
            except Exception:
                pass
            campaigns.append(entry)
    else:
        if OUTPUTS_ROOT.exists():
            for d in sorted(OUTPUTS_ROOT.iterdir()):
                if d.is_dir() and not d.name.startswith("_"):
                    report = d / f"{d.name}_report.html"
                    manifest_path = d / "campaign_manifest.json"
                    assets = list(d.rglob("*.png"))
                    entry = {
                        "campaign_id": d.name,
                        "asset_count": len([a for a in assets if "_base_" not in a.name]),
                        "has_report": report.exists(),
                    }
                    if manifest_path.exists():
                        try:
                            manifest = json.loads(manifest_path.read_text())
                            entry["brand_name"] = manifest.get("brand_name")
                            entry["product_count"] = len(manifest.get("products", []))
                            entry["created_at"] = manifest.get("created_at")
                        except Exception:
                            pass
                    campaigns.append(entry)

    return {"campaigns": campaigns}


# ── Config management ─────────────────────────────────────────────────────────

_CONFIG_TYPES = {
    "brand-guidelines": "brand_guidelines",
    "prohibited-words": "prohibited_words",
}

_SAFE_PROFILE_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _validate_profile_name(name: str) -> None:
    """Reject unsafe profile names."""
    if not _SAFE_PROFILE_RE.match(name):
        raise HTTPException(400, "Profile name must be alphanumeric/underscores only")


def _config_path(config_type: str, name: str | None = None) -> Path:
    """Resolve config file path for a given type and optional profile name."""
    base = _CONFIG_TYPES.get(config_type)
    if not base:
        raise HTTPException(404, "Unknown config type")
    filename = f"{base}_{name}.json" if name else f"{base}.json"
    return CONFIG_DIR / filename


def _check_brand_guidelines(data: dict) -> None:
    """Validate brand guidelines, raising HTTPException on failure."""
    errors = validate_brand_guidelines(data)
    if errors:
        raise HTTPException(400, "; ".join(errors))


def _check_prohibited_words(data: dict) -> None:
    """Validate prohibited words, raising HTTPException on failure."""
    errors = validate_prohibited_words(data)
    if errors:
        raise HTTPException(400, "; ".join(errors))


@app.get("/api/config/profiles")
async def list_config_profiles() -> dict:
    """List all available config profile names (merges Azure + local; Azure takes precedence)."""
    profiles: dict[str, list[str]] = {}
    for config_type, base in _CONFIG_TYPES.items():
        name_set: dict[str, None] = {}  # ordered dedup

        # Azure profiles first (takes precedence on duplicates)
        if _is_azure():
            try:
                blobs = _get_storage().list_files("config/")
                for blob in sorted(blobs):
                    filename = blob.split("/")[-1]  # blob name = config/{filename}
                    stem = filename.removesuffix(".json")
                    prefix = f"{base}_"
                    if stem.startswith(prefix):
                        profile_name = stem.removeprefix(prefix)
                        if profile_name and _SAFE_PROFILE_RE.match(profile_name):
                            name_set[profile_name] = None
            except Exception:
                pass

        # Local filesystem profiles
        for f in sorted(CONFIG_DIR.glob(f"{base}_*.json")):
            profile_name = f.stem.removeprefix(f"{base}_")
            if profile_name and _SAFE_PROFILE_RE.match(profile_name):
                name_set.setdefault(profile_name, None)

        profiles[config_type] = list(name_set.keys())
    return {"profiles": profiles}


@app.get("/api/config/{config_type}")
async def get_config(config_type: str) -> dict:
    """Return default config for a given type."""
    path = _config_path(config_type)
    if not path.exists():
        raise HTTPException(404, "Config not found")
    return json.loads(path.read_text())


@app.get("/api/config/{config_type}/{name}")
async def get_config_profile(config_type: str, name: str) -> dict:
    """Return a named config profile (checks Azure first, then local filesystem)."""
    _validate_profile_name(name)
    base = _CONFIG_TYPES.get(config_type)
    if not base:
        raise HTTPException(404, "Unknown config type")
    filename = f"{base}_{name}.json"
    if _is_azure():
        try:
            data = _get_storage().get_file(f"config/{filename}")
            return json.loads(data)
        except FileNotFoundError:
            pass
    path = CONFIG_DIR / filename
    if not path.exists():
        raise HTTPException(404, f"Profile '{name}' not found")
    return json.loads(path.read_text())


@app.put("/api/config/{config_type}")
async def save_config(config_type: str, request: Request) -> dict:
    """Save default config for a given type (Azure: saves to storage; local: writes to config/ dir)."""
    data = await request.json()
    if config_type == "brand-guidelines":
        _check_brand_guidelines(data)
    elif config_type == "prohibited-words":
        _check_prohibited_words(data)
    base = _CONFIG_TYPES.get(config_type)
    if not base:
        raise HTTPException(404, "Unknown config type")
    filename = f"{base}.json"
    if _is_azure():
        _get_storage().save_file(json.dumps(data, indent=2).encode(), f"config/{filename}")
        logger.info("Config saved to Azure: config/%s", filename)
        return {"status": "saved", "path": f"config/{filename}"}
    path = CONFIG_DIR / filename
    path.write_text(json.dumps(data, indent=2))
    logger.info("Config saved: %s", path.name)
    return {"status": "saved", "path": path.name}


@app.put("/api/config/{config_type}/{name}")
async def save_config_profile(config_type: str, name: str, request: Request) -> dict:
    """Save a named config profile (Azure: saves to storage; local: writes to config/ dir)."""
    _validate_profile_name(name)
    data = await request.json()
    if config_type == "brand-guidelines":
        _check_brand_guidelines(data)
    elif config_type == "prohibited-words":
        _check_prohibited_words(data)
    base = _CONFIG_TYPES.get(config_type)
    if not base:
        raise HTTPException(404, "Unknown config type")
    filename = f"{base}_{name}.json"
    if _is_azure():
        _get_storage().save_file(json.dumps(data, indent=2).encode(), f"config/{filename}")
        logger.info("Config profile saved to Azure: config/%s", filename)
        return {"status": "saved", "profile": name, "path": f"config/{filename}"}
    path = CONFIG_DIR / filename
    path.write_text(json.dumps(data, indent=2))
    logger.info("Config profile saved: %s", path.name)
    return {"status": "saved", "profile": name, "path": path.name}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host=settings.host, port=settings.port, reload=True)
