# backend/api/app.py
"""
Coaching config UI — FastAPI app.

Routes:
  GET  /              — SPA entry point
  POST /save          — update config (form)
  POST /workouts/upload — import a .zwo or .tcx workout file
  GET  /api/config    — raw JSON config
  POST /api/config    — update config via JSON
  GET  /api/workouts  — JSON list of all indexed workouts
  GET  /status        — CTL/ATL/TSB + HRV from InfluxDB

Security:
  All /api/* routes require the X-API-Key header matching CONFIG_API_KEY env.
  Frontend SPA routes (/, /workouts) are unauthenticated static assets.

Run:
  uvicorn backend.api.app:app --host 0.0.0.0 --port 8080
"""

import os
import logging
import secrets
import tempfile
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Form, Request, UploadFile, File, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from pydantic import BaseModel, Field

from backend.config_manager import ConfigManager, BLOCK_PHASES, RACE_FORMATS, RACE_PRIORITIES
from backend.library.workout_library import WorkoutLibrary

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Upload limits
# ---------------------------------------------------------------------------
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

# ---------------------------------------------------------------------------
# API key authentication
# ---------------------------------------------------------------------------
_API_KEY = os.environ.get("CONFIG_API_KEY", "")
if not _API_KEY:
    _API_KEY = secrets.token_urlsafe(32)
    logger.warning(
        "CONFIG_API_KEY not set — generated ephemeral key. "
        "Set CONFIG_API_KEY in .env for persistent auth. Key: %s",
        _API_KEY,
    )


def _require_api_key(request: Request) -> None:
    """Dependency that validates the X-API-Key header on protected routes."""
    key = request.headers.get("X-API-Key", "")
    if not secrets.compare_digest(key, _API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ---------------------------------------------------------------------------
# Config validation schema for POST /api/config
# ---------------------------------------------------------------------------
class AthleteConfig(BaseModel):
    ftp: Optional[int] = Field(None, ge=50, le=600)
    css: Optional[str] = None
    lthr_run: Optional[int] = Field(None, ge=80, le=220)

class BlockConfig(BaseModel):
    phase: Optional[str] = None
    week_in_block: Optional[int] = Field(None, ge=1, le=52)

class RaceConfig(BaseModel):
    date: Optional[str] = None
    format: Optional[str] = None
    priority: Optional[str] = None

class SeasonConfigUpdate(BaseModel):
    athlete: Optional[AthleteConfig] = None
    block: Optional[BlockConfig] = None
    race_a: Optional[RaceConfig] = None
    race_b: Optional[RaceConfig] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "   # Vite dev modules need inline
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        # Only set HSTS if TLS is in use (i.e. behind a reverse proxy with HTTPS)
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


# ---------------------------------------------------------------------------
# App init
# ---------------------------------------------------------------------------
app = FastAPI(title="AI Coaching Config", docs_url=None, redoc_url=None)
cfg = ConfigManager()

app.add_middleware(SecurityHeadersMiddleware)

# CORS — allow the SPA and known dashboard origins
_CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS", "http://localhost:8080,http://localhost:3000"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _get_library() -> WorkoutLibrary:
    """Lazy-init library using current athlete params from config."""
    c = cfg.load()
    return WorkoutLibrary(
        athlete_ftp=int(c.get("athlete", {}).get("ftp", 250)),
        athlete_lthr=int(c.get("athlete", {}).get("lthr_run", 162)),
    )


# ---------------------------------------------------------------------------
# Static Assets & SPA Entry
# ---------------------------------------------------------------------------
# Mount the frontend directory so Vite's /src/main.js etc are accessible
app.mount("/src", StaticFiles(directory="frontend/src"), name="src")
app.mount("/styles", StaticFiles(directory="frontend/src/styles"), name="styles")

@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = Path("frontend/index.html")
    if not index_path.exists():
        return HTMLResponse("Frontend not initialized. Run Vite setup.", status_code=500)
    return HTMLResponse(index_path.read_text())


@app.get("/workouts", response_class=HTMLResponse)
async def workouts_page_spa():
    """SPA catch-all — serve index.html and let the JS router handle it."""
    index_path = Path("frontend/index.html")
    if not index_path.exists():
        return HTMLResponse("Frontend not initialized.", status_code=500)
    return HTMLResponse(index_path.read_text())


# ---------------------------------------------------------------------------
# POST /save — form submission
# ---------------------------------------------------------------------------
@app.post("/save")
async def save_config(
    request: Request,
    athlete_ftp: int = Form(...),
    athlete_css: str = Form(...),
    athlete_lthr_run: int = Form(...),
    block_phase: str = Form(...),
    block_week: int = Form(...),
    race_a_date: str = Form(...),
    race_a_format: str = Form(...),
    race_a_priority: str = Form(...),
    race_b_date: str = Form(""),
    race_b_format: str = Form(""),
    race_b_priority: str = Form("B"),
    notes: str = Form(""),
):
    cfg.save({
        "athlete": {
            "ftp": athlete_ftp,
            "css": athlete_css,
            "lthr_run": athlete_lthr_run,
        },
        "block": {
            "phase": block_phase,
            "week_in_block": block_week,
        },
        "race_a": {
            "date": race_a_date,
            "format": race_a_format,
            "priority": race_a_priority,
        },
        "race_b": {
            "date": race_b_date,
            "format": race_b_format,
            "priority": race_b_priority,
        },
        "notes": notes,
    })
    return RedirectResponse("/?saved=1", status_code=303)


# ---------------------------------------------------------------------------
# GET /api/config — raw JSON
# ---------------------------------------------------------------------------
@app.get("/api/config")
async def get_config(_: None = Depends(_require_api_key)):
    return JSONResponse(cfg.load())


# ---------------------------------------------------------------------------
# POST /api/config — update via JSON (for scripting)
# ---------------------------------------------------------------------------
@app.post("/api/config")
async def post_config(body: SeasonConfigUpdate, _: None = Depends(_require_api_key)):
    cfg.save(body.model_dump(exclude_none=True))
    return JSONResponse({"status": "ok", "config": cfg.load()})


# ---------------------------------------------------------------------------
# GET /status — live fitness state
# ---------------------------------------------------------------------------
@app.get("/status")
async def get_status(_: None = Depends(_require_api_key)):
    try:
        from backend.storage.influx_client import InfluxClient
        from backend.analysis.fitness_models import calculate_ctl_atl_tsb

        influx = InfluxClient()
        tss = influx.get_daily_tss(days=120)
        hrv = influx.get_hrv_trend(days=14)
        influx.close()

        if tss.empty:
            return JSONResponse({"error": "No TSS data — run a sync first"}, status_code=503)

        ctl, atl, tsb_series = calculate_ctl_atl_tsb(tss)
        return JSONResponse({
            "date": date.today().isoformat(),
            "ctl": round(float(ctl.iloc[-1]), 1),
            "atl": round(float(atl.iloc[-1]), 1),
            "tsb": round(float(tsb_series.iloc[-1]), 1),
            "hrv_trend": hrv,
        })
    except Exception as exc:
        logger.error("Status check failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Status check failed"}, status_code=500)


# ---------------------------------------------------------------------------
# GET /workouts — browse library
# ---------------------------------------------------------------------------
# Legacy HTML /workouts route removed — SPA handles this via /workouts above.
# Use /api/workouts for JSON data access.


# ---------------------------------------------------------------------------
# POST /workouts/upload — import .zwo or .tcx file
# ---------------------------------------------------------------------------
@app.post("/workouts/upload")
async def upload_workout(file: UploadFile = File(...), _: None = Depends(_require_api_key)):
    # Sanitize filename — strip directory components to prevent path traversal
    safe_name = PurePosixPath(file.filename or "upload").name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in (".zwo", ".tcx"):
        return JSONResponse({"error": "Only .zwo and .tcx files supported"}, status_code=400)

    import_dir = Path(os.environ.get("WORKOUT_IMPORT_DIR", "/config/workouts/imports"))
    import_dir.mkdir(parents=True, exist_ok=True)
    dest = import_dir / safe_name

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        return JSONResponse(
            {"error": f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024}MB)"},
            status_code=413,
        )
    dest.write_bytes(contents)

    lib = _get_library()
    sessions = lib.import_file(dest)
    names = ", ".join(s.title for s in sessions) if sessions else "none"
    logger.info("Uploaded %s → %d sessions indexed (%s)", safe_name, len(sessions), names)

    return JSONResponse({"status": "ok", "filename": safe_name, "sessions_imported": len(sessions)})


# ---------------------------------------------------------------------------
# GET /api/workouts — JSON list of all workouts
# ---------------------------------------------------------------------------
@app.get("/api/workouts")
async def api_workouts(sport: str = "", search: str = "", _: None = Depends(_require_api_key)):
    lib = _get_library()
    if search:
        sessions = lib.find_by_name(search, top_n=20)
    elif sport:
        sessions = lib.find_by_sport(sport)
    else:
        sessions = lib.all_sessions()

    return JSONResponse([
        {
            "title": s.title,
            "sport": s.sport,
            "description": s.description,
            "tags": s.rationale,
            "estimated_tss": s.estimated_tss,
            "steps": len(s.steps),
        }
        for s in sorted(sessions, key=lambda x: (x.sport, x.title))
    ])


# ---------------------------------------------------------------------------
# POST /api/health-data — health data from companion app
# ---------------------------------------------------------------------------
@app.post("/api/health-data")
async def post_health_data(body: Dict[str, Any], _: None = Depends(_require_api_key)):
    """Receive health data from iOS Shortcut / Android Tasker."""
    try:
        from backend.schemas.health_data import HealthDataPost
        from backend.data_ingestion.health_data_ingest import HealthDataIngester

        payload = HealthDataPost.model_validate(body)
        ingester = HealthDataIngester()
        result = ingester.process(payload)
        return JSONResponse({"status": "ok", **result})
    except Exception as exc:
        logger.error("Health data ingestion failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Health data ingestion failed"}, status_code=500)


# ---------------------------------------------------------------------------
# GET/POST /api/profile — athlete profile
# ---------------------------------------------------------------------------
@app.get("/api/profile")
async def get_profile(athlete_id: str = "default", _: None = Depends(_require_api_key)):
    try:
        from backend.planning.profile_manager import ProfileManager
        pm = ProfileManager()
        profile = pm.load_profile(athlete_id)
        return JSONResponse(profile.model_dump())
    except Exception as exc:
        logger.error("Profile load failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Profile load failed"}, status_code=500)


@app.post("/api/profile")
async def save_profile(body: Dict[str, Any], _: None = Depends(_require_api_key)):
    try:
        from backend.schemas.athlete_profile import AthleteProfile
        from backend.planning.profile_manager import ProfileManager
        profile = AthleteProfile.model_validate(body)
        pm = ProfileManager()
        pm.save_profile(profile)
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        logger.error("Profile save failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Profile save failed"}, status_code=500)


# ---------------------------------------------------------------------------
# POST /api/extract-event — race event from URL
# ---------------------------------------------------------------------------
@app.post("/api/extract-event")
async def extract_event(body: Dict[str, Any], _: None = Depends(_require_api_key)):
    """Extract race event details from a URL using LLM."""
    url = body.get("url", "")
    priority = body.get("priority", "C")
    if not url:
        return JSONResponse({"error": "url is required"}, status_code=400)
    try:
        from backend.planning.event_extractor import extract_event_from_url
        from backend.orchestration.llm_client import OllamaClient
        llm = OllamaClient()
        event = extract_event_from_url(url, llm)
        event["priority"] = priority
        return JSONResponse({"status": "ok", "event": event})
    except Exception as exc:
        logger.error("Event extraction failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Event extraction failed"}, status_code=500)


# ---------------------------------------------------------------------------
# POST /api/race-result — post-race result ingestion
# ---------------------------------------------------------------------------
@app.post("/api/race-result")
async def post_race_result(body: Dict[str, Any], _: None = Depends(_require_api_key)):
    try:
        from backend.schemas.race_event import RaceResult
        from backend.data_ingestion.race_result_ingest import RaceResultIngester
        result = RaceResult.model_validate(body)
        ingester = RaceResultIngester()
        ingester.store_result(result)
        return JSONResponse({"status": "ok", "event_id": result.event_id})
    except Exception as exc:
        logger.error("Race result ingestion failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Race result ingestion failed"}, status_code=500)


# ---------------------------------------------------------------------------
# POST /api/post-session — post-session RPE/wellness log
# ---------------------------------------------------------------------------
@app.post("/api/post-session")
async def post_session_log(body: Dict[str, Any], _: None = Depends(_require_api_key)):
    try:
        from backend.schemas.injury import PostSessionLog
        from backend.analysis.injury_tracker import InjuryTracker
        log = PostSessionLog.model_validate(body)
        tracker = InjuryTracker()
        result = tracker.log_post_session(log)
        return JSONResponse({"status": "ok", **result})
    except Exception as exc:
        logger.error("Post-session log failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Post-session logging failed"}, status_code=500)


# ---------------------------------------------------------------------------
# Vacation management
# ---------------------------------------------------------------------------
@app.get("/api/vacations")
async def get_vacations(_: None = Depends(_require_api_key)):
    try:
        from backend.planning.vacation_planner import VacationPlanner
        planner = VacationPlanner()
        vacations = planner._pg.get_upcoming_vacations() if planner._pg else []
        return JSONResponse({"vacations": vacations})
    except Exception as exc:
        logger.error("Vacation load failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Failed to load vacations"}, status_code=500)


@app.post("/api/vacations")
async def save_vacation(body: Dict[str, Any], _: None = Depends(_require_api_key)):
    try:
        from backend.schemas.vacation import VacationWindow
        from backend.planning.vacation_planner import VacationPlanner
        vacation = VacationWindow.model_validate(body)
        planner = VacationPlanner()
        planner.save_vacation(vacation)
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        logger.error("Vacation save failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Failed to save vacation"}, status_code=500)


# ---------------------------------------------------------------------------
# Gear tracking
# ---------------------------------------------------------------------------
@app.get("/api/gear")
async def get_gear(athlete_id: str = "default", _: None = Depends(_require_api_key)):
    try:
        from backend.analysis.gear_tracker import GearTracker
        tracker = GearTracker()
        equipment = tracker.load_equipment(athlete_id)
        alerts = tracker.get_all_alerts(athlete_id)
        return JSONResponse({
            "equipment": [e.model_dump() for e in equipment],
            "alerts": [a.model_dump() for a in alerts],
        })
    except Exception as exc:
        logger.error("Gear load failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Failed to load gear"}, status_code=500)


@app.post("/api/gear")
async def save_gear(body: Dict[str, Any], _: None = Depends(_require_api_key)):
    try:
        from backend.schemas.athlete_profile import EquipmentItem
        from backend.analysis.gear_tracker import GearTracker
        athlete_id = body.pop("athlete_id", "default")
        item = EquipmentItem.model_validate(body)
        tracker = GearTracker()
        tracker.save_equipment(athlete_id, item)
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        logger.error("Gear save failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Failed to save gear"}, status_code=500)


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
@app.get("/api/weather")
async def get_weather(
    lat: float = 39.7392, lon: float = -104.9903, days: int = 7,
    _: None = Depends(_require_api_key),
):
    try:
        from backend.data_ingestion.weather_service import WeatherService
        ws = WeatherService(latitude=lat, longitude=lon)
        forecast = ws.get_forecast(days=min(days, 16))
        weekly = ws.get_weekly_weather_context()
        return JSONResponse({"forecast": forecast, "weekly_context": weekly})
    except Exception as exc:
        logger.error("Weather fetch failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Weather data unavailable"}, status_code=500)


# ---------------------------------------------------------------------------
# Data export
# ---------------------------------------------------------------------------
@app.get("/api/export")
async def export_all_data(_: None = Depends(_require_api_key)):
    try:
        from backend.api.export import DataExporter
        from backend.storage.postgres_client import PostgresClient
        from fastapi.responses import StreamingResponse
        pg = PostgresClient()
        exporter = DataExporter(postgres_client=pg, config_manager=cfg)
        buffer = exporter.export_all()
        return StreamingResponse(
            buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=coaching_export_{date.today().isoformat()}.zip"},
        )
    except Exception as exc:
        logger.error("Data export failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Data export failed"}, status_code=500)


# ---------------------------------------------------------------------------
# System health
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health_check(_: None = Depends(_require_api_key)):
    try:
        from backend.orchestration.monitor import PipelineMonitor
        monitor = PipelineMonitor()
        return JSONResponse(monitor.full_health_check())
    except Exception as exc:
        logger.error("Health check failed: %s", exc, exc_info=True)
        return JSONResponse({"status": "error", "error": "Health check failed"}, status_code=500)


# ---------------------------------------------------------------------------
# Season planner — current phase and TSS arc
# ---------------------------------------------------------------------------
@app.get("/api/season")
async def get_season_plan(_: None = Depends(_require_api_key)):
    try:
        from backend.planning.season_planner import SeasonPlanner
        c = cfg.load()
        races = []
        for key in ("race_a", "race_b"):
            r = c.get(key, {})
            if r.get("date"):
                races.append({
                    "event_id": key,
                    "event_date": r["date"],
                    "name": r.get("name", key.replace("_", " ").title()),
                    "format": r.get("format", "Other"),
                    "priority": r.get("priority", "C"),
                })
        planner = SeasonPlanner(races)
        phase = planner.detect_current_phase()
        arc = planner.generate_tss_arc(weeks_ahead=26)
        return JSONResponse({"current_phase": phase, "tss_arc": arc[:12]})
    except Exception as exc:
        logger.error("Season plan failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "Season plan unavailable"}, status_code=500)
