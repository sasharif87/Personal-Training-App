# backend/api/app.py
"""
Coaching config UI — FastAPI app.

Routes:
  GET  /              — season/block/race/athlete config form
  POST /save          — update config
  GET  /workouts      — browse workout library + upload .zwo/.tcx files
  POST /workouts/upload — import a .zwo or .tcx workout file
  GET  /api/config    — raw JSON config
  POST /api/config    — update config via JSON
  GET  /api/workouts  — JSON list of all indexed workouts
  GET  /status        — CTL/ATL/TSB + HRV from InfluxDB

Run:
  uvicorn backend.api.app:app --host 0.0.0.0 --port 8080
"""

import os
import logging
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from backend.config_manager import ConfigManager, BLOCK_PHASES, RACE_FORMATS, RACE_PRIORITIES
from backend.library.workout_library import WorkoutLibrary

logger = logging.getLogger(__name__)

app = FastAPI(title="AI Coaching Config", docs_url=None, redoc_url=None)
cfg = ConfigManager()

def _get_library() -> WorkoutLibrary:
    """Lazy-init library using current athlete params from config."""
    c = cfg.load()
    return WorkoutLibrary(
        athlete_ftp=int(c.get("athlete", {}).get("ftp", 250)),
        athlete_lthr=int(c.get("athlete", {}).get("lthr_run", 162)),
    )


# ---------------------------------------------------------------------------
# GET / — config form
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(saved: str = ""):
    config = cfg.load()
    banner = ""
    if saved == "1":
        banner = '<div class="banner">Config saved.</div>'
    return HTMLResponse(_render_page(config, banner))


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
async def get_config():
    return JSONResponse(cfg.load())


# ---------------------------------------------------------------------------
# POST /api/config — update via JSON (for scripting)
# ---------------------------------------------------------------------------
@app.post("/api/config")
async def post_config(body: Dict[str, Any]):
    cfg.save(body)
    return JSONResponse({"status": "ok", "config": cfg.load()})


# ---------------------------------------------------------------------------
# GET /status — live fitness state
# ---------------------------------------------------------------------------
@app.get("/status")
async def get_status():
    try:
        from backend.storage.influx_client import InfluxClient
        from backend.analysis.fitness_models import calculate_ctl_atl_tsb

        influx = InfluxClient()
        tss = influx.get_daily_tss(days=120)
        hrv = influx.get_hrv_trend(days=14)
        influx.close()

        if tss.empty:
            return JSONResponse({"error": "No TSS data in InfluxDB — run a sync first"}, status_code=503)

        ctl, atl, tsb_series = calculate_ctl_atl_tsb(tss)
        return JSONResponse({
            "date": date.today().isoformat(),
            "ctl": round(float(ctl.iloc[-1]), 1),
            "atl": round(float(atl.iloc[-1]), 1),
            "tsb": round(float(tsb_series.iloc[-1]), 1),
            "hrv_trend": hrv,
        })
    except Exception as exc:
        logger.error("Status check failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# GET /workouts — browse library
# ---------------------------------------------------------------------------
@app.get("/workouts", response_class=HTMLResponse)
async def workouts_page(sport: str = "", search: str = "", uploaded: str = ""):
    lib = _get_library()
    if search:
        sessions = lib.find_by_name(search, top_n=20)
    elif sport:
        sessions = lib.find_by_sport(sport)
    else:
        sessions = lib.all_sessions()

    summary = lib.summary()
    banner = ""
    if uploaded:
        banner = f'<div class="banner">Imported {uploaded} — library reloaded.</div>'

    return HTMLResponse(_render_workouts_page(sessions, summary, sport, search, banner))


# ---------------------------------------------------------------------------
# POST /workouts/upload — import .zwo or .tcx file
# ---------------------------------------------------------------------------
@app.post("/workouts/upload")
async def upload_workout(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".zwo", ".tcx"):
        return JSONResponse({"error": "Only .zwo and .tcx files supported"}, status_code=400)

    import_dir = Path(os.environ.get("WORKOUT_IMPORT_DIR", "/config/workouts/imports"))
    import_dir.mkdir(parents=True, exist_ok=True)
    dest = import_dir / file.filename

    contents = await file.read()
    dest.write_bytes(contents)

    lib = _get_library()
    sessions = lib.import_file(dest)
    names = ", ".join(s.title for s in sessions) if sessions else "none"
    logger.info("Uploaded %s → %d sessions indexed (%s)", file.filename, len(sessions), names)

    return RedirectResponse(f"/workouts?uploaded={file.filename}", status_code=303)


# ---------------------------------------------------------------------------
# GET /api/workouts — JSON list of all workouts
# ---------------------------------------------------------------------------
@app.get("/api/workouts")
async def api_workouts(sport: str = "", search: str = ""):
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
async def post_health_data(body: Dict[str, Any]):
    """Receive health data from iOS Shortcut / Android Tasker."""
    try:
        from backend.schemas.health_data import HealthDataPost
        from backend.data_ingestion.health_data_ingest import HealthDataIngester

        payload = HealthDataPost.model_validate(body)
        ingester = HealthDataIngester()
        result = ingester.process(payload)
        return JSONResponse({"status": "ok", **result})
    except Exception as exc:
        logger.error("Health data ingestion failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# GET/POST /api/profile — athlete profile
# ---------------------------------------------------------------------------
@app.get("/api/profile")
async def get_profile(athlete_id: str = "default"):
    try:
        from backend.planning.profile_manager import ProfileManager
        pm = ProfileManager()
        profile = pm.load_profile(athlete_id)
        return JSONResponse(profile.model_dump())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/profile")
async def save_profile(body: Dict[str, Any]):
    try:
        from backend.schemas.athlete_profile import AthleteProfile
        from backend.planning.profile_manager import ProfileManager
        profile = AthleteProfile.model_validate(body)
        pm = ProfileManager()
        pm.save_profile(profile)
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# POST /api/extract-event — race event from URL
# ---------------------------------------------------------------------------
@app.post("/api/extract-event")
async def extract_event(body: Dict[str, Any]):
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
        logger.error("Event extraction failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# POST /api/race-result — post-race result ingestion
# ---------------------------------------------------------------------------
@app.post("/api/race-result")
async def post_race_result(body: Dict[str, Any]):
    try:
        from backend.schemas.race_event import RaceResult
        from backend.data_ingestion.race_result_ingest import RaceResultIngester
        result = RaceResult.model_validate(body)
        ingester = RaceResultIngester()
        ingester.store_result(result)
        return JSONResponse({"status": "ok", "event_id": result.event_id})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# POST /api/post-session — post-session RPE/wellness log
# ---------------------------------------------------------------------------
@app.post("/api/post-session")
async def post_session_log(body: Dict[str, Any]):
    try:
        from backend.schemas.injury import PostSessionLog
        from backend.analysis.injury_tracker import InjuryTracker
        log = PostSessionLog.model_validate(body)
        tracker = InjuryTracker()
        result = tracker.log_post_session(log)
        return JSONResponse({"status": "ok", **result})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Vacation management
# ---------------------------------------------------------------------------
@app.get("/api/vacations")
async def get_vacations():
    try:
        from backend.planning.vacation_planner import VacationPlanner
        planner = VacationPlanner()
        vacations = planner._pg.get_upcoming_vacations() if planner._pg else []
        return JSONResponse({"vacations": vacations})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/vacations")
async def save_vacation(body: Dict[str, Any]):
    try:
        from backend.schemas.vacation import VacationWindow
        from backend.planning.vacation_planner import VacationPlanner
        vacation = VacationWindow.model_validate(body)
        planner = VacationPlanner()
        planner.save_vacation(vacation)
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Gear tracking
# ---------------------------------------------------------------------------
@app.get("/api/gear")
async def get_gear(athlete_id: str = "default"):
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
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/gear")
async def save_gear(body: Dict[str, Any]):
    try:
        from backend.schemas.athlete_profile import EquipmentItem
        from backend.analysis.gear_tracker import GearTracker
        athlete_id = body.pop("athlete_id", "default")
        item = EquipmentItem.model_validate(body)
        tracker = GearTracker()
        tracker.save_equipment(athlete_id, item)
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
@app.get("/api/weather")
async def get_weather(lat: float = 39.7392, lon: float = -104.9903, days: int = 7):
    try:
        from backend.data_ingestion.weather_service import WeatherService
        ws = WeatherService(latitude=lat, longitude=lon)
        forecast = ws.get_forecast(days=days)
        weekly = ws.get_weekly_weather_context()
        return JSONResponse({"forecast": forecast, "weekly_context": weekly})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Data export
# ---------------------------------------------------------------------------
@app.get("/api/export")
async def export_all_data():
    try:
        from backend.api.export import DataExporter
        from fastapi.responses import StreamingResponse
        exporter = DataExporter(config_manager=cfg)
        buffer = exporter.export_all()
        return StreamingResponse(
            buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=coaching_export_{date.today().isoformat()}.zip"},
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# System health
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health_check():
    try:
        from backend.orchestration.monitor import PipelineMonitor
        monitor = PipelineMonitor()
        return JSONResponse(monitor.full_health_check())
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Season planner — current phase and TSS arc
# ---------------------------------------------------------------------------
@app.get("/api/season")
async def get_season_plan():
    try:
        from backend.planning.season_planner import SeasonPlanner
        # Attempt to get races from the config
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
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# HTML renderer — workouts page
# ---------------------------------------------------------------------------
def _render_page(config: dict, banner: str = "") -> str:
    a = config.get("athlete", {})
    b = config.get("block", {})
    ra = config.get("race_a", {})
    rb = config.get("race_b", {})

    def phase_opts(selected):
        return "\n".join(
            f'<option value="{p}" {"selected" if p == selected else ""}>{p}</option>'
            for p in BLOCK_PHASES
        )

    def format_opts(selected):
        return "\n".join(
            f'<option value="{f}" {"selected" if f == selected else ""}>{f}</option>'
            for f in [""] + RACE_FORMATS
        )

    def priority_opts(selected):
        return "\n".join(
            f'<option value="{p}" {"selected" if p == selected else ""}>{p}</option>'
            for p in RACE_PRIORITIES
        )

    weeks_to_race = ""
    if ra.get("date"):
        try:
            delta = (date.fromisoformat(ra["date"]) - date.today()).days
            weeks = delta // 7
            weeks_to_race = f'<p class="hint">{weeks} weeks to race A from today</p>' if weeks >= 0 else '<p class="hint warn">Race date is in the past</p>'
        except ValueError:
            pass

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Coach — Season Config</title>
<style>
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --border: #2e3147;
    --accent: #4f7cff;
    --text: #e0e2f0;
    --muted: #7b7f9e;
    --green: #3dd68c;
    --warn: #f5a623;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: system-ui, sans-serif;
         font-size: 15px; line-height: 1.6; }}
  .wrap {{ max-width: 680px; margin: 0 auto; padding: 32px 20px 60px; }}
  h1 {{ font-size: 1.3rem; font-weight: 600; color: var(--accent); margin-bottom: 4px; }}
  .subtitle {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 28px; }}
  .banner {{ background: var(--green); color: #0a1a12; border-radius: 6px;
             padding: 10px 16px; margin-bottom: 20px; font-weight: 500; }}
  section {{ background: var(--surface); border: 1px solid var(--border);
             border-radius: 10px; padding: 24px; margin-bottom: 20px; }}
  section h2 {{ font-size: 0.78rem; text-transform: uppercase; letter-spacing: .08em;
                color: var(--muted); margin-bottom: 18px; }}
  .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .field {{ display: flex; flex-direction: column; gap: 6px; }}
  .field.full {{ grid-column: 1 / -1; }}
  label {{ font-size: 0.82rem; color: var(--muted); }}
  input, select, textarea {{
    background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
    color: var(--text); font-size: 0.95rem; padding: 8px 12px; width: 100%;
    outline: none; transition: border-color .15s;
  }}
  input:focus, select:focus, textarea:focus {{ border-color: var(--accent); }}
  textarea {{ resize: vertical; min-height: 72px; }}
  .hint {{ font-size: 0.8rem; color: var(--muted); margin-top: 6px; }}
  .hint.warn {{ color: var(--warn); }}
  .actions {{ display: flex; gap: 12px; align-items: center; margin-top: 8px; }}
  button[type=submit] {{
    background: var(--accent); color: #fff; border: none; border-radius: 6px;
    padding: 10px 28px; font-size: 0.95rem; font-weight: 600; cursor: pointer;
    transition: opacity .15s;
  }}
  button[type=submit]:hover {{ opacity: .85; }}
  a.status-link {{ color: var(--muted); font-size: 0.85rem; text-decoration: none; }}
  a.status-link:hover {{ color: var(--text); }}
</style>
</head>
<body>
<div class="wrap">
  <h1>AI Coach — Season Config</h1>
  <p class="subtitle">Changes take effect on the next pipeline run (3 AM or manual trigger)</p>
  {banner}

  <form method="post" action="/save">

    <section>
      <h2>Athlete</h2>
      <div class="row">
        <div class="field">
          <label for="ftp">FTP (Watts)</label>
          <input type="number" id="ftp" name="athlete_ftp" value="{a.get('ftp', 250)}" min="50" max="600" required>
        </div>
        <div class="field">
          <label for="css">CSS (pace / 100m, e.g. 1:45/100m)</label>
          <input type="text" id="css" name="athlete_css" value="{a.get('css', '1:45/100m')}" placeholder="1:45/100m" required>
        </div>
        <div class="field">
          <label for="lthr">LTHR Run (BPM)</label>
          <input type="number" id="lthr" name="athlete_lthr_run" value="{a.get('lthr_run', 162)}" min="100" max="220" required>
        </div>
      </div>
    </section>

    <section>
      <h2>Training Block</h2>
      <div class="row">
        <div class="field">
          <label for="phase">Phase</label>
          <select id="phase" name="block_phase">
            {phase_opts(b.get('phase', 'Base'))}
          </select>
        </div>
        <div class="field">
          <label for="week">Week in Block</label>
          <input type="number" id="week" name="block_week" value="{b.get('week_in_block', 1)}" min="1" max="24" required>
        </div>
      </div>
    </section>

    <section>
      <h2>Race A — Peak Event</h2>
      <div class="row">
        <div class="field">
          <label for="ra_date">Date</label>
          <input type="date" id="ra_date" name="race_a_date" value="{ra.get('date', '')}">
        </div>
        <div class="field">
          <label for="ra_format">Format</label>
          <select id="ra_format" name="race_a_format">
            {format_opts(ra.get('format', 'Olympic'))}
          </select>
        </div>
        <div class="field">
          <label for="ra_priority">Priority</label>
          <select id="ra_priority" name="race_a_priority">
            {priority_opts(ra.get('priority', 'A'))}
          </select>
        </div>
      </div>
      {weeks_to_race}
    </section>

    <section>
      <h2>Race B — Optional</h2>
      <div class="row">
        <div class="field">
          <label for="rb_date">Date</label>
          <input type="date" id="rb_date" name="race_b_date" value="{rb.get('date', '')}">
        </div>
        <div class="field">
          <label for="rb_format">Format</label>
          <select id="rb_format" name="race_b_format">
            {format_opts(rb.get('format', ''))}
          </select>
        </div>
        <div class="field">
          <label for="rb_priority">Priority</label>
          <select id="rb_priority" name="race_b_priority">
            {priority_opts(rb.get('priority', 'B'))}
          </select>
        </div>
      </div>
    </section>

    <section>
      <h2>Notes</h2>
      <div class="field full">
        <label for="notes">Season notes / context for the LLM</label>
        <textarea id="notes" name="notes" placeholder="e.g. Coming back from 2-week illness. Base build. Conservative ramp.">{config.get('notes', '')}</textarea>
      </div>
    </section>

    <div class="actions">
      <button type="submit">Save Config</button>
      <a class="status-link" href="/workouts">Browse workout library →</a>
      <a class="status-link" href="/status" target="_blank">Fitness status →</a>
    </div>

  </form>
</div>
</body>
</html>"""


def _render_workouts_page(sessions, summary: Dict, sport: str, search: str, banner: str) -> str:
    sport_counts = "  ".join(
        f'<a class="sport-pill {"active" if sport == s else ""}" href="/workouts?sport={s}">'
        f'{s.title()} <span>{n}</span></a>'
        for s, n in sorted(summary.items())
    )

    rows = ""
    for s in sorted(sessions, key=lambda x: (x.sport, x.title)):
        tags_html = " ".join(
            f'<span class="tag">{t.strip()}</span>'
            for t in s.rationale.split(",") if t.strip()
        )
        rows += f"""
        <tr>
          <td><span class="sport-badge {s.sport}">{s.sport}</span></td>
          <td class="title">{s.title}</td>
          <td>{s.description[:90]}{"…" if len(s.description) > 90 else ""}</td>
          <td class="tss">{s.estimated_tss:.0f}</td>
          <td>{len(s.steps)}</td>
          <td>{tags_html}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Coach — Workout Library</title>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --border: #2e3147;
    --accent: #4f7cff; --text: #e0e2f0; --muted: #7b7f9e;
    --green: #3dd68c; --warn: #f5a623;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: system-ui, sans-serif;
         font-size: 14px; line-height: 1.5; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 28px 20px 60px; }}
  h1 {{ font-size: 1.2rem; color: var(--accent); margin-bottom: 4px; }}
  .subtitle {{ color: var(--muted); font-size: 0.82rem; margin-bottom: 20px; }}
  .banner {{ background: var(--green); color: #0a1a12; border-radius: 6px;
             padding: 10px 16px; margin-bottom: 16px; font-weight: 500; }}
  .toolbar {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: center;
              margin-bottom: 18px; }}
  .sport-pill {{ background: var(--surface); border: 1px solid var(--border); border-radius: 20px;
                 padding: 5px 14px; color: var(--muted); text-decoration: none; font-size: 0.82rem; }}
  .sport-pill:hover, .sport-pill.active {{ border-color: var(--accent); color: var(--accent); }}
  .sport-pill span {{ opacity: .6; }}
  .search-box {{ flex: 1; min-width: 180px; background: var(--surface);
                 border: 1px solid var(--border); border-radius: 6px;
                 color: var(--text); padding: 6px 12px; font-size: 0.9rem; outline: none; }}
  .search-box:focus {{ border-color: var(--accent); }}
  .upload-btn {{ background: var(--surface); border: 1px solid var(--border);
                 color: var(--muted); border-radius: 6px; padding: 6px 14px;
                 font-size: 0.82rem; cursor: pointer; }}
  .upload-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ text-align: left; font-size: 0.72rem; text-transform: uppercase;
        letter-spacing: .06em; color: var(--muted); padding: 0 10px 10px; }}
  td {{ padding: 10px; border-top: 1px solid var(--border); vertical-align: middle; }}
  tr:hover td {{ background: var(--surface); }}
  td.title {{ font-weight: 500; color: var(--text); }}
  td.tss {{ font-weight: 600; color: var(--accent); text-align: right; }}
  .sport-badge {{ display: inline-block; border-radius: 4px; padding: 2px 8px;
                  font-size: 0.72rem; font-weight: 600; text-transform: uppercase; }}
  .sport-badge.swim {{ background: #1a3a5c; color: #5bc0f8; }}
  .sport-badge.run  {{ background: #1a3a2a; color: #3dd68c; }}
  .sport-badge.bike {{ background: #3a2a1a; color: #f5a623; }}
  .sport-badge.brick{{ background: #2a1a3a; color: #a78bfa; }}
  .tag {{ background: var(--border); border-radius: 4px; padding: 1px 6px;
          font-size: 0.70rem; color: var(--muted); margin-right: 3px; }}
  .upload-form {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,.6);
                  align-items: center; justify-content: center; z-index: 100; }}
  .upload-form.show {{ display: flex; }}
  .upload-card {{ background: var(--surface); border: 1px solid var(--border);
                  border-radius: 12px; padding: 28px; width: 420px; }}
  .upload-card h2 {{ font-size: 1rem; margin-bottom: 16px; }}
  .upload-card p {{ color: var(--muted); font-size: 0.82rem; margin-bottom: 20px; }}
  .upload-card input[type=file] {{ width: 100%; margin-bottom: 16px;
                                   color: var(--muted); font-size: 0.9rem; }}
  .btn-row {{ display: flex; gap: 10px; }}
  .btn-primary {{ background: var(--accent); color: #fff; border: none; border-radius: 6px;
                  padding: 9px 20px; font-weight: 600; cursor: pointer; }}
  .btn-cancel  {{ background: transparent; border: 1px solid var(--border); color: var(--muted);
                  border-radius: 6px; padding: 9px 16px; cursor: pointer; }}
  .back {{ color: var(--muted); font-size: 0.82rem; text-decoration: none; }}
  .back:hover {{ color: var(--text); }}
</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="/">← Season config</a>
  <h1 style="margin-top:12px">Workout Library</h1>
  <p class="subtitle">{len(sessions)} workouts shown · Drop .zwo (TrainerRoad/Zwift) or .tcx (TrainingPeaks) to import</p>
  {banner}

  <div class="toolbar">
    <a class="sport-pill {"active" if not sport and not search else ""}" href="/workouts">All</a>
    {sport_counts}
    <form method="get" action="/workouts" style="display:contents">
      <input class="search-box" name="search" value="{search}" placeholder="Search by name…">
    </form>
    <button class="upload-btn" onclick="document.getElementById('uploadModal').classList.add('show')">
      + Import file
    </button>
  </div>

  <table>
    <thead>
      <tr>
        <th>Sport</th><th>Title</th><th>Description</th>
        <th style="text-align:right">TSS</th><th>Steps</th><th>Tags</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>

<!-- Upload modal -->
<div class="upload-form" id="uploadModal">
  <div class="upload-card">
    <h2>Import Workout File</h2>
    <p>Supports .zwo (TrainerRoad/Zwift) and .tcx (TrainingPeaks).<br>
       Files are saved to the imports folder and indexed immediately.</p>
    <form method="post" action="/workouts/upload" enctype="multipart/form-data">
      <input type="file" name="file" accept=".zwo,.tcx" required>
      <div class="btn-row">
        <button type="submit" class="btn-primary">Import</button>
        <button type="button" class="btn-cancel"
                onclick="document.getElementById('uploadModal').classList.remove('show')">
          Cancel
        </button>
      </div>
    </form>
  </div>
</div>
</body>
</html>"""
