# AI Coaching System — Code Scratchpad

**Libraries · Data Formats · Patterns · Implementation Notes**

> This is a living scratchpad — ideas and patterns to pick up when coding starts. Not prescriptive. Expect to revise as implementation reveals better approaches.

---

## Data Ingestion — Completed Activities

### Garmindb

Primary ingestion library. Pulls from Garmin Connect into local SQLite or MySQL. Handles FIT file parsing, activity types, HRV data, sleep, body battery.

```bash
pip install garmindb

python -m garmindb.garmin_db --all --latest   # ongoing sync
python -m garmindb.garmin_db --all            # full historical pull
```

- Activities land in `activities` table with sport type, duration, distance, HR stats
- HRV and sleep in separate tables — join on date for daily readiness context
- FTP stored in `user_profile` table — pull directly rather than calculating
- Planned workout definitions in separate table from completed activities — need both

---

## Planned Workout Retrieval

This is new relative to typical Garmin-only pipelines. Planned sessions are the other side of the plan/actual pair — without them, there is nothing to compare execution against.

### TrainingPeaks API

TrainingPeaks has an official API (OAuth2). This is the richest source for multi-sport planned sessions — swim sets, run intervals, brick sessions, strength days, all with coaching text.

```python
import requests
from datetime import date, timedelta

class TrainingPeaksClient:
    BASE_URL = "https://api.trainingpeaks.com/v1"
    
    def __init__(self, access_token: str):
        self.headers = {"Authorization": f"Bearer {access_token}"}
    
    def get_planned_workouts(self, user_id: int, start_date: date, end_date: date) -> list:
        """Fetch all planned workouts in date range."""
        resp = requests.get(
            f"{self.BASE_URL}/workouts/{user_id}",
            params={
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat()
            },
            headers=self.headers
        )
        resp.raise_for_status()
        return [self._normalise(w) for w in resp.json()]
    
    def _normalise(self, raw: dict) -> dict:
        """Convert TP format to unified planned_session schema."""
        return {
            "session_id": raw["workoutId"],
            "source_platform": "trainingpeaks",
            "planned_date": raw["workoutDay"],
            "sport": self._map_sport(raw["exerciseType"]),
            "title": raw.get("title", ""),
            "coaching_text": raw.get("description", ""),    # coaching intent text
            "planned_duration_min": raw.get("totalTime", 0) / 60,
            "planned_tss": raw.get("tss"),
            "planned_if": raw.get("if"),
            "planned_distance_m": raw.get("distance"),
            "structure": self._parse_structure(raw.get("structure"))
        }
    
    def _map_sport(self, tp_type: str) -> str:
        mapping = {
            "Swim": "swim", "Bike": "bike", "Run": "run",
            "Strength": "strength", "Other": "cross_training"
        }
        return mapping.get(tp_type, "other")
    
    def _parse_structure(self, structure: dict) -> dict:
        """Parse TP structured workout steps into unified format."""
        if not structure:
            return {}
        # TP structure is nested steps with type, duration, targets
        # Map to: {"warmup": {...}, "main_sets": [...], "cooldown": {...}}
        return parse_tp_steps(structure.get("steps", []))
```

### TrainerRoad — Workout Library & FIT Name Lookup

TrainerRoad workout names are embedded in the Garmin FIT file metadata when TR sessions sync through Garmin. The pipeline extracts that name and looks it up in a local copy of the TR workout library to retrieve the full interval structure and coaching text.

**`trainerroad-export`** is only needed once (or occasionally) to build the local library. It's not an ongoing dependency — once the library is on disk, everything runs from that local copy.

```bash
# One-time (or occasional refresh) — pull the full TR workout library
pip install trainerroad-export
trainerroad-export --username X --password Y --output ./tr_library/
```

```python
import json
from pathlib import Path

# ── Step 1: Build the workout library on first run ──────────────────────────

def build_tr_library(export_dir: str) -> int:
    """
    Load TR workout library export into PostgreSQL.
    Keyed by workout name — this is what gets matched against FIT file metadata.
    Run once after trainerroad-export, refresh occasionally.
    """
    count = 0
    for f in Path(export_dir).glob("*.json"):
        raw = json.loads(f.read_text())
        db.execute("""
            INSERT INTO tr_workout_library
                (tr_id, name, name_lower, description, duration_min,
                 tss, intensity_factor, structure)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tr_id) DO UPDATE
            SET name = EXCLUDED.name,
                description = EXCLUDED.description,
                structure = EXCLUDED.structure
        """, (
            raw["Id"],
            raw["Name"],
            raw["Name"].lower().strip(),
            raw.get("Description", ""),
            raw.get("Duration", 0) / 60,
            raw.get("Tss"),
            raw.get("If"),
            json.dumps(parse_tr_intervals(raw.get("Intervals", [])))
        ))
        count += 1
    return count


# ── Step 2: Extract TR workout name from FIT file ───────────────────────────

def extract_tr_workout_name(fit_data: dict) -> str | None:
    """
    Pull the TrainerRoad workout name from FIT file metadata.
    TR embeds the workout name in the 'workout_name' field of the session message.
    """
    return fit_data.get("workout_name") or fit_data.get("session", {}).get("workout_name")


# ── Step 3: Match FIT activity to TR library entry ──────────────────────────

def lookup_tr_workout(workout_name: str) -> dict | None:
    """
    Look up a TR workout by name from the local library.
    Tries exact match first, then normalised match (strip suffixes like +1, -1).
    """
    if not workout_name:
        return None
    
    # Exact match
    result = db.fetchone(
        "SELECT * FROM tr_workout_library WHERE name_lower = %s",
        (workout_name.lower().strip(),)
    )
    if result:
        return result
    
    # Normalised match — strip variant suffix (+1, +2, -1, etc.)
    # "Carillon +2" → try "Carillon" as base workout
    base_name = strip_tr_variant_suffix(workout_name)
    if base_name != workout_name:
        result = db.fetchone(
            "SELECT * FROM tr_workout_library WHERE name_lower = %s",
            (base_name.lower().strip(),)
        )
        if result:
            return {**result, "_matched_as_base": True}
    
    # Fuzzy match — name similarity + physiological profile confirmation
    # Used when exact and base-name matching both fail.
    # Name similarity alone is too weak — many TR workouts have similar names
    # but very different targets. Confirming on IF, TSS, and workout type
    # turns a name guess into a confident physiological match.
    actual_if = activity.get("intensity_factor")
    actual_tss = activity.get("tss")
    actual_duration = activity.get("duration_min")
    
    result = find_tr_workout_by_profile(
        name=workout_name,
        actual_if=actual_if,
        actual_tss=actual_tss,
        actual_duration=actual_duration
    )
    
    if result:
        return {**result, "_matched_as_fuzzy": True}
    
    return None  # Unmatched — log for manual review

def strip_tr_variant_suffix(name: str) -> str:
    """'Carillon +2' → 'Carillon', 'Pettit -1' → 'Pettit'"""
    import re
    return re.sub(r'\s*[+-]\d+$', '', name).strip()


def classify_workout_type(intensity_factor: float | None, duration_min: float | None) -> str:
    """
    Classify a workout into a broad physiological type from IF and duration.
    TR workouts cluster clearly into these types — IF is the primary signal.
    
    Used both to classify the actual workout from the FIT file
    and to filter the library before fuzzy name matching.
    """
    if intensity_factor is None:
        return "unknown"
    
    if intensity_factor >= 1.05:
        return "vo2max"          # VO2max / anaerobic — hard short intervals
    elif intensity_factor >= 0.95:
        return "threshold"       # FTP-level work — over/unders, threshold intervals
    elif intensity_factor >= 0.88:
        return "sweet_spot"      # Sweet spot — 88–94% FTP, TR's bread and butter
    elif intensity_factor >= 0.76:
        return "tempo"           # Tempo / upper Z3
    elif intensity_factor >= 0.60:
        return "endurance"       # Z2 aerobic endurance
    else:
        return "recovery"        # Active recovery / Z1


def find_tr_workout_by_profile(
    name: str,
    actual_if: float | None,
    actual_tss: float | None,
    actual_duration: float | None
) -> dict | None:
    """
    Multi-signal fuzzy match against the TR workout library.
    
    Scoring approach:
    - Name similarity (pg_trgm): directional signal, not sufficient alone
    - Workout type match (derived from IF): must match or very close — eliminates
      the most dangerous mismatches (VO2max ≠ endurance regardless of name)
    - IF delta: within ±0.06 is plausible; tighter is better
    - TSS delta: within ±15% is plausible
    - Duration delta: within ±10min is plausible
    
    A match requires: name similarity > 0.55 AND workout type match
    AND at least one of (IF delta ok OR TSS delta ok).
    All three physiological signals agreeing = high confidence.
    """
    if actual_if is None and actual_tss is None:
        # No physiological data to confirm against — name-only fuzzy is too risky
        return None
    
    actual_type = classify_workout_type(actual_if, actual_duration)
    
    # Pull candidates with name similarity > threshold AND same workout type.
    # Workout type filter is the most important guard — it eliminates entire
    # wrong zones of the library before we score on IF/TSS.
    candidates = db.query("""
        SELECT *,
               similarity(name_lower, %(name)s) AS name_sim
        FROM tr_workout_library
        WHERE similarity(name_lower, %(name)s) > 0.45
          AND workout_type = %(wtype)s
        ORDER BY name_sim DESC
        LIMIT 10
    """, {"name": name.lower().strip(), "wtype": actual_type})
    
    if not candidates:
        # Relax: allow adjacent workout types (e.g. sweet_spot vs threshold)
        adjacent = {
            "vo2max": ["threshold"],
            "threshold": ["sweet_spot", "vo2max"],
            "sweet_spot": ["threshold", "tempo"],
            "tempo": ["sweet_spot", "endurance"],
            "endurance": ["tempo"],
            "recovery": ["endurance"]
        }
        allowed_types = [actual_type] + adjacent.get(actual_type, [])
        
        candidates = db.query("""
            SELECT *,
                   similarity(name_lower, %(name)s) AS name_sim
            FROM tr_workout_library
            WHERE similarity(name_lower, %(name)s) > 0.45
              AND workout_type = ANY(%(types)s)
            ORDER BY name_sim DESC
            LIMIT 10
        """, {"name": name.lower().strip(), "types": allowed_types})
    
    if not candidates:
        return None
    
    # Score each candidate across all available signals
    scored = []
    for c in candidates:
        score = score_tr_candidate(c, name, actual_if, actual_tss, actual_duration)
        if score["total"] >= 0.60 and score["hard_pass"] is False:
            scored.append((score["total"], c, score))
    
    if not scored:
        return None
    
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_match, breakdown = scored[0]
    
    return {
        **best_match,
        "_match_score": round(best_score, 3),
        "_match_breakdown": breakdown
    }


def score_tr_candidate(
    candidate: dict,
    name: str,
    actual_if: float | None,
    actual_tss: float | None,
    actual_duration: float | None
) -> dict:
    """
    Score a library candidate against the actual workout profile.
    Returns a score dict with component scores and a hard_pass flag.
    
    hard_pass = True means this candidate should be rejected regardless of
    name similarity — the physiological profile is too different to be the
    same workout.
    """
    components = {}
    hard_pass = False
    
    # ── Name similarity (0–1) ─────────────────────────────────────────────
    from difflib import SequenceMatcher
    name_sim = SequenceMatcher(None, name.lower(), candidate["name_lower"]).ratio()
    components["name"] = name_sim
    
    # ── IF delta ─────────────────────────────────────────────────────────
    lib_if = candidate.get("intensity_factor")
    if actual_if and lib_if:
        if_delta = abs(actual_if - lib_if)
        if if_delta > 0.12:
            hard_pass = True   # More than 12% IF difference = wrong workout type
        elif if_delta <= 0.03:
            components["if"] = 1.0
        elif if_delta <= 0.06:
            components["if"] = 0.7
        else:
            components["if"] = 0.3   # 0.06–0.12 — plausible but weak
    
    # ── TSS delta ────────────────────────────────────────────────────────
    lib_tss = candidate.get("tss")
    if actual_tss and lib_tss:
        tss_pct_delta = abs(actual_tss - lib_tss) / lib_tss
        if tss_pct_delta > 0.30:
            hard_pass = True   # >30% TSS difference — fundamentally different session
        elif tss_pct_delta <= 0.10:
            components["tss"] = 1.0
        elif tss_pct_delta <= 0.20:
            components["tss"] = 0.6
        else:
            components["tss"] = 0.2
    
    # ── Duration delta ───────────────────────────────────────────────────
    lib_duration = candidate.get("duration_min")
    if actual_duration and lib_duration:
        dur_delta = abs(actual_duration - lib_duration)
        if dur_delta <= 5:
            components["duration"] = 1.0
        elif dur_delta <= 10:
            components["duration"] = 0.7
        elif dur_delta <= 20:
            components["duration"] = 0.3
        # No hard pass on duration — athletes modify session length
    
    # ── Workout type agreement ────────────────────────────────────────────
    actual_type = classify_workout_type(actual_if, actual_duration)
    if candidate.get("workout_type") == actual_type:
        components["workout_type"] = 1.0
    else:
        components["workout_type"] = 0.3   # Adjacent type — tolerated but weighted down
    
    # ── Composite score ───────────────────────────────────────────────────
    # Weights: physiological signals outweigh name similarity.
    # A name match with wrong IF/TSS is a bad match.
    # A physiological match with approximate name is fine.
    weights = {
        "workout_type": 0.30,   # Highest — eliminates entire wrong zones
        "if":           0.25,   # Strong — IF defines the training stimulus
        "tss":          0.20,   # Moderate — total load confirmation
        "name":         0.15,   # Directional only — many similar TR names
        "duration":     0.10    # Weakest — athletes modify durations
    }
    
    total = sum(
        components.get(k, 0.5) * w   # 0.5 default if signal not available
        for k, w in weights.items()
    )
    
    return {
        "total": round(total, 3),
        "components": components,
        "hard_pass": hard_pass,
        "actual_type": actual_type,
        "lib_type": candidate.get("workout_type")
    }


def build_tr_library_with_types(export_dir: str) -> int:
    """
    Extended library build that also classifies and stores workout_type.
    Replaces the original build_tr_library() — run this version.
    """
    count = 0
    for f in Path(export_dir).glob("*.json"):
        raw = json.loads(f.read_text())
        lib_if = raw.get("If")
        lib_duration = raw.get("Duration", 0) / 60
        workout_type = classify_workout_type(lib_if, lib_duration)
        
        db.execute("""
            INSERT INTO tr_workout_library
                (tr_id, name, name_lower, description, duration_min,
                 tss, intensity_factor, workout_type, structure)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tr_id) DO UPDATE
            SET name = EXCLUDED.name,
                description = EXCLUDED.description,
                intensity_factor = EXCLUDED.intensity_factor,
                workout_type = EXCLUDED.workout_type,
                structure = EXCLUDED.structure
        """, (
            raw["Id"], raw["Name"], raw["Name"].lower().strip(),
            raw.get("Description", ""), lib_duration,
            raw.get("Tss"), lib_if, workout_type,
            json.dumps(parse_tr_intervals(raw.get("Intervals", [])))
        ))
        count += 1
    
    # Create trigram index if not exists — needed for similarity() queries
    db.execute("CREATE INDEX IF NOT EXISTS tr_lib_name_trgm ON tr_workout_library USING gin(name_lower gin_trgm_ops)")
    return count


# ── Step 4: Wire into the activity ingestion pipeline ───────────────────────

def enrich_activity_with_tr_plan(activity: dict) -> dict:
    """
    After a FIT file is ingested, try to attach the TR planned session.
    If found, this becomes the 'planned' side of the plan/actual pair.
    """
    workout_name = extract_tr_workout_name(activity.get("fit_metadata", {}))
    
    if not workout_name:
        return activity  # Not a TR workout or name not in FIT
    
    tr_workout = lookup_tr_workout(workout_name)
    
    if tr_workout:
        activity["planned_session"] = {
            "source_platform": "trainerroad",
            "import_method": "fit_name_lookup",
            "title": tr_workout["name"],
            "coaching_text": tr_workout["description"],
            "planned_duration_min": tr_workout["duration_min"],
            "planned_tss": tr_workout["tss"],
            "planned_if": tr_workout["intensity_factor"],
            "structure": json.loads(tr_workout["structure"]) if tr_workout["structure"] else {}
        }
        activity["tr_match_method"] = tr_workout.get("_matched_as_fuzzy") and "fuzzy" or \
                                       tr_workout.get("_matched_as_base") and "base" or "exact"
    else:
        # Log unmatched for review — build up the library over time
        db.execute(
            "INSERT INTO tr_unmatched_names (workout_name, activity_date, activity_id) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (workout_name, activity["date"], activity["activity_id"])
        )
    
    return activity
```

### TrainingPeaks File Fallback

When the TrainingPeaks API is unavailable or the OAuth approach breaks, the athlete exports their calendar manually. TrainingPeaks supports CSV export and individual workout file export.

```python
import csv
from pathlib import Path

TP_IMPORT_DIR = Path("/imports/trainingpeaks")

def load_tp_calendar_csv(csv_path: Path) -> list:
    """
    Parse a TrainingPeaks calendar export CSV into unified planned_session schema.
    TP CSV includes: date, title, duration, TSS, IF, description, sport type.
    """
    sessions = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            sessions.append({
                "session_id": generate_id(row["Date"] + row["Title"]),
                "source_platform": "trainingpeaks",
                "import_method": "file_watch",
                "planned_date": parse_tp_date(row["Date"]),
                "sport": map_tp_sport(row.get("Sport", "")),
                "title": row.get("Title", ""),
                "coaching_text": row.get("Description", ""),
                "planned_duration_min": parse_duration(row.get("Duration")),
                "planned_tss": float(row["TSS"]) if row.get("TSS") else None,
                "planned_if": float(row["IF"]) if row.get("IF") else None,
                "structure": {}   # CSV doesn't include interval structure
            })
    return sessions

def scan_tp_import_folder() -> list:
    """Watch for new TP exports and process them."""
    new_files = get_unprocessed_files(TP_IMPORT_DIR, extensions=[".csv", ".json", ".xml"])
    sessions = []
    for f in new_files:
        if f.suffix == ".csv":
            sessions.extend(load_tp_calendar_csv(f))
        elif f.suffix == ".json":
            sessions.extend(load_tp_workout_json(f))
        mark_processed(str(f))
    return sessions
```

### Master Ingestion Router

The daily pipeline calls this. It tries the API first and silently falls back to file-watch if the API is unavailable. The pipeline never stops because one API is broken.

```python
class GarminAPIUnavailable(Exception): pass
class TrainingPeaksAPIUnavailable(Exception): pass

def run_ingestion(athlete_id: str) -> dict:
    """
    Master ingestion router. API-first, file-watch fallback.
    Returns summary of what was ingested and from which source.
    """
    summary = {"garmin_api": None, "tp_api": None, "file_imports": []}
    
    # ── Garmin completed activities ────────────────────────────────────────
    try:
        client = get_garmin_client(athlete["email"], athlete["password"])
        garmindb_sync(client)
        summary["garmin_api"] = "ok"
    except GarminAPIUnavailable:
        summary["garmin_api"] = "unavailable — using file-watch"
    
    # Always scan file-watch folder regardless of API status
    # API and file-watch are additive — if both work, file-watch just finds nothing new
    new_fit = scan_import_folder(Path(f"/imports/garmin/fit"))
    if new_fit:
        summary["file_imports"].append(f"garmin: {len(new_fit)} FIT files")
    
    # ── TrainingPeaks planned workouts ─────────────────────────────────────
    try:
        tp_sessions = fetch_tp_planned_workouts_api(athlete)
        summary["tp_api"] = "ok"
    except TrainingPeaksAPIUnavailable:
        summary["tp_api"] = "unavailable — using file-watch"
        tp_sessions = []
    
    tp_file_sessions = scan_tp_import_folder()
    if tp_file_sessions:
        summary["file_imports"].append(f"trainingpeaks: {len(tp_file_sessions)} sessions")
    
    # Merge and deduplicate — same session may arrive from both API and file
    all_tp = deduplicate_planned_sessions(tp_sessions + tp_file_sessions)
    store_planned_sessions(all_tp)
    
    # ── TrainerRoad ────────────────────────────────────────────────────────
    # TR workout names come from FIT file metadata — no separate ingestion needed.
    # enrich_activity_with_tr_plan() runs as part of activity ingestion above
    # and looks up the name in the local tr_workout_library table.
    # The library is built once via trainerroad-export and lives on disk.
    summary["trainerroad"] = "name_lookup_from_fit"
    
    log_ingestion_summary(athlete_id, summary)
    return summary
```


# Excel / Google Sheets spreadsheet plans also scan here:
# scan_import_folder(Path("/imports/spreadsheets"), extensions=[".xlsx", ".csv"])

---

## Spreadsheet Plan Ingest

Coach-authored training plans frequently live in Excel or Google Sheets — a grid of weeks, days, and sessions. The ingest layer accepts `.xlsx` and `.csv` drops and handles the most common layouts.

> **Note on your specific spreadsheet:** Once you share the column/row layout of the "2025 Race Team: Winter/Spring Training" sheet, the column_map and layout detection can be tuned to match it exactly. The parser below handles the common cases and falls back to LLM parsing for non-standard formats.

### Common Spreadsheet Layouts

**Layout A — Weeks as rows, days as columns (most common)**
```
Week | Mon       | Tue        | Wed        | Thu        | Fri  | Sat             | Sun
1    | Run 40min | Swim 2500m | Bike 60min | Run 6x800m | REST | Long ride 2.5hr | Long run 90min
     | Easy Z2   | CSS sets   | Threshold  | @ 5k pace  |      | Z2+3x10min SS   |
```

**Layout B — Weeks as columns, sessions as rows**
```
Session    | Wk1        | Wk2         | Wk3
Mon Run    | 40min easy | 45min easy  | 50min easy
Tue Swim   | 2000m      | 2500m CSS   | 3000m threshold
Wed Bike   | 60min Z2   | 75min SS    | 90min threshold
```

**Layout C — Flat list with date column**
```
Date       | Sport | Title         | Duration | Description
2027-01-06 | Run   | Easy Z2       | 45min    | Keep HR below 140
2027-01-07 | Swim  | CSS threshold | 60min    | 8x100 @ CSS 15s rest
```

### Core Parser

```python
import openpyxl
import csv
import re
from pathlib import Path
from datetime import date, timedelta

SPREADSHEET_IMPORT_DIR = Path("/imports/spreadsheets")

def ingest_spreadsheet_plan(
    file_path: Path,
    athlete_id: str,
    plan_start_date: date,
    column_map: dict = None
) -> list[dict]:
    """
    Main entry point. Detects layout, parses sessions, stores to DB.
    plan_start_date: Monday of Week 1 (required for Layout A/B where dates are implied).
    column_map: optional override for non-standard column names.
                e.g. {"sport": "Activity", "description": "Coach Notes"}
    """
    if file_path.suffix in (".xlsx", ".xlsm"):
        rows, headers = load_xlsx(file_path)
    elif file_path.suffix == ".csv":
        rows, headers = load_csv(file_path)
    else:
        raise ValueError(f"Unsupported: {file_path.suffix}")

    layout = detect_layout(headers, rows)

    if layout == "A":
        sessions = parse_layout_a(rows, headers, plan_start_date)
    elif layout == "B":
        sessions = parse_layout_b(rows, headers, plan_start_date)
    elif layout == "C":
        sessions = parse_layout_c(rows, headers, column_map)
    else:
        sessions = llm_parse_spreadsheet(rows, headers, plan_start_date)

    normalised = [normalise_spreadsheet_session(s, athlete_id) for s in sessions]
    store_planned_sessions(normalised)
    mark_processed(str(file_path))
    return normalised


def load_xlsx(path: Path) -> tuple[list, list]:
    """Load all sheets or the first non-empty sheet. Returns (rows, headers)."""
    wb = openpyxl.load_workbook(path, data_only=True)
    all_sessions = []
    headers = []
    
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        sheet_rows = [[cell.value for cell in row] for row in ws.iter_rows()]
        # Skip completely empty sheets
        if not any(any(c for c in r) for r in sheet_rows):
            continue
        # First non-empty row is the header
        for i, row in enumerate(sheet_rows):
            if any(c for c in row):
                if not headers:
                    headers = [str(c) if c else "" for c in row]
                    all_sessions.extend(sheet_rows[i+1:])
                else:
                    # Multi-sheet: each sheet may be a different week or sport
                    # Treat first row of subsequent sheets as a section label, not header
                    all_sessions.extend(sheet_rows[i:])
                break
    
    return all_sessions, headers


def detect_layout(headers: list[str], rows: list[list]) -> str:
    """Sniff layout from header row shape."""
    h = [str(x).lower().strip() for x in headers if x]
    DAY_NAMES = {"mon","tue","wed","thu","fri","sat","sun",
                 "monday","tuesday","wednesday","thursday","friday","saturday","sunday"}
    
    if len(DAY_NAMES & set(h)) >= 4:
        return "A"
    if "date" in h and any(x in h for x in ("sport","activity","type","discipline")):
        return "C"
    week_in_header = any("wk" in x or "week" in x for x in h)
    first_col = [str(r[0]).lower() for r in rows[:8] if r and r[0]]
    sport_in_first_col = any(
        any(s in v for s in ("run","swim","bike","ride","strength"))
        for v in first_col
    )
    if week_in_header and sport_in_first_col:
        return "B"
    return "unknown"


DAY_OFFSETS = {
    "mon":0,"monday":0,"tue":1,"tuesday":1,"wed":2,"wednesday":2,
    "thu":3,"thursday":3,"fri":4,"friday":4,"sat":5,"saturday":5,"sun":6,"sunday":6
}

def parse_layout_a(rows, headers, plan_start: date) -> list[dict]:
    """Weeks as rows, days as columns."""
    sessions = []
    day_cols = {i: DAY_OFFSETS[str(h).lower().strip()]
                for i, h in enumerate(headers)
                if str(h).lower().strip() in DAY_OFFSETS}

    week_num = 0
    for row in rows:
        if not any(str(c).strip() for c in row if c is not None):
            continue
        first = str(row[0] or "").strip().lower()
        wk_match = re.search(r"\d+", first)
        if wk_match and any(kw in first for kw in ("week","wk","")):
            week_num = int(wk_match.group())
        else:
            week_num += 1

        week_start = plan_start + timedelta(weeks=week_num - 1)

        for col_idx, day_offset in day_cols.items():
            if col_idx >= len(row):
                continue
            cell = str(row[col_idx] or "").strip()
            if not cell or cell.lower() in ("rest","off","-",""):
                continue
            session_date = week_start + timedelta(days=day_offset)
            s = parse_cell_to_session(cell, session_date)
            if s:
                sessions.append(s)
    return sessions


def parse_layout_c(rows, headers, column_map: dict = None) -> list[dict]:
    """Flat list with explicit date column."""
    ALIASES = {
        "date":     ["date","day"],
        "sport":    ["sport","activity","type","discipline"],
        "title":    ["title","name","workout","session"],
        "duration": ["duration","time","length"],
        "description": ["description","notes","details","desc","coach notes"],
        "tss":      ["tss","training stress"],
        "planned_if": ["if","intensity factor"],
    }
    col_idx = {}
    for i, h in enumerate(headers):
        key = str(h or "").lower().strip()
        for canonical, aliases in ALIASES.items():
            if key in aliases:
                col_idx[canonical] = i

    sessions = []
    for row in rows:
        if not any(str(c or "").strip() for c in row):
            continue
        def get(field):
            i = col_idx.get(field)
            return str(row[i] or "").strip() if i is not None and i < len(row) else ""

        raw_date = get("date")
        if not raw_date:
            continue
        try:
            from dateutil import parser as dp
            session_date = dp.parse(raw_date).date()
        except Exception:
            continue

        desc = get("description")
        sport = infer_sport(get("sport"), desc)
        sessions.append({
            "planned_date": session_date.isoformat(),
            "sport": sport,
            "title": get("title") or f"{sport.title()} session",
            "coaching_text": desc,
            "planned_duration_min": parse_duration_str(get("duration")),
            "planned_tss": float(get("tss")) if get("tss") else None,
            "planned_if": float(get("planned_if")) if get("planned_if") else None,
        })
    return sessions


def parse_cell_to_session(cell_text: str, session_date: date) -> dict | None:
    """Parse a spreadsheet cell (possibly multi-line) into a session dict."""
    lines = [l.strip() for l in cell_text.strip().splitlines() if l.strip()]
    if not lines:
        return None
    primary = lines[0]
    detail_lines = lines[1:]
    sport = infer_sport_from_text(primary)
    structure = parse_workout_notation(detail_lines, sport)
    return {
        "planned_date": session_date.isoformat(),
        "sport": sport,
        "title": clean_session_title(primary),
        "coaching_text": "\n".join(detail_lines),
        "planned_duration_min": extract_duration(primary),
        "planned_distance_m": extract_distance(primary),
        "structure": structure,
    }


def infer_sport_from_text(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ("swim","pool","open water","css","100m","200m","400m")):
        return "swim"
    if any(w in t for w in ("bike","ride","cycling","zwift","ftp","watts")):
        return "bike"
    if any(w in t for w in ("run","jog","marathon","tempo","intervals","800m","5k","10k")):
        return "run"
    if any(w in t for w in ("strength","gym","weights","lift")):
        return "strength"
    if any(w in t for w in ("yoga","stretch","mobility","foam roll")):
        return "mobility"
    return "other"


def extract_duration(text: str) -> float | None:
    t = text.lower()
    for pattern, fn in [
        (r"(\d+)\s*hr?\s*(\d+)\s*min", lambda m: int(m.group(1))*60+int(m.group(2))),
        (r"(\d+\.?\d*)\s*hr?s?",        lambda m: float(m.group(1))*60),
        (r"(\d+):(\d+)",                 lambda m: int(m.group(1))*60+int(m.group(2))),
        (r"(\d+)\s*min",                 lambda m: float(m.group(1))),
    ]:
        m = re.search(pattern, t)
        if m:
            return fn(m)
    return None


def extract_distance(text: str) -> float | None:
    t = text.lower()
    for pattern, fn in [
        (r"(\d+\.?\d*)\s*km", lambda m: float(m.group(1))*1000),
        (r"(\d+\.?\d*)\s*k\b", lambda m: float(m.group(1))*1000),
        (r"(\d+)\s*m\b", lambda m: float(m.group(1))),
    ]:
        m = re.search(pattern, t)
        if m:
            return fn(m)
    return None


def parse_workout_notation(lines: list[str], sport: str) -> dict:
    if sport == "swim":
        return parse_swim_notation(lines)
    elif sport == "run":
        return parse_run_notation(lines)
    elif sport == "bike":
        return parse_bike_notation(lines)
    return {"main_sets": [], "raw_text": "\n".join(lines)}


def llm_parse_spreadsheet(rows, headers, plan_start: date) -> list[dict]:
    """Last resort — LLM parses non-standard layouts. Called once, result cached."""
    sample_text = "\n".join(
        " | ".join(str(c or "") for c in row)
        for row in [headers] + rows[:25]
    )
    prompt = f"""Extract all planned workout sessions from this training plan spreadsheet.
Plan starts week of {plan_start.isoformat()}.
Return JSON array only. Each item: {{
  "planned_date": "YYYY-MM-DD",
  "sport": "swim|bike|run|strength|mobility|other",
  "title": "short title",
  "coaching_text": "full description as written",
  "planned_duration_min": number_or_null,
  "planned_distance_m": number_or_null
}}

Spreadsheet:
{sample_text}"""
    response = llm_client.generate(prompt, expect_json=True)
    return json.loads(response)


def normalise_spreadsheet_session(raw: dict, athlete_id: str) -> dict:
    return {
        "session_id": generate_stable_id(athlete_id, raw["planned_date"], raw["sport"]),
        "source_platform": "spreadsheet",
        "import_method": "file_ingest",
        "athlete_id": athlete_id,
        "planned_date": raw["planned_date"],
        "sport": raw.get("sport", "other"),
        "title": raw.get("title", ""),
        "coaching_text": raw.get("coaching_text", raw.get("description", "")),
        "planned_duration_min": raw.get("planned_duration_min"),
        "planned_distance_m": raw.get("planned_distance_m"),
        "planned_tss": raw.get("planned_tss"),
        "planned_if": raw.get("planned_if"),
        "structure": raw.get("structure", {}),
        "imported_at": datetime.utcnow().isoformat()
    }
```

---

## MCR / Coach Plan Layout Parser (Layout D)

This layout is specific to coach-authored multi-group training plans in the format seen in the MCR Spring Training spreadsheet. It differs from the generic layouts because:

- **Multiple athlete groups** live in parallel columns (e.g. `GB 13.1 <25`, `GB 13.1 26-40`, `41-60`, `60+`)
- **Multiple tabs** represent different goal races (GB 13.1 = half marathon, BK 5k = 5k)
- **3–4 session rows per week** with the session type in a Key Weekly Components column
- **Session day is implied** from the row label ("Mon Optional" → Monday, "Weds Workout" → Wednesday, "Long Run" → Saturday)
- **Workout descriptions** use running-specific shorthand: ladders (`5-4-3-2-1min`), cruise LRs (`CRUISE LR: X Miles`), complex sets (`4-5min@TP, 3x200h@8K`)
- **Weekly % column** gives intended training intensity load

The plan is ingested once per group — the athlete's ability group is selected at import time (or configured in their profile), and only that column is extracted.

```python
# ── MCR-style layout detection ───────────────────────────────────────────────

def is_mcr_layout(headers: list[str], rows: list[list]) -> bool:
    """
    Detect the MCR/coach multi-group layout.
    Signals:
    - Header row contains 'Key Weekly Components' or similar
    - 4 group columns with patterns like '<25', '26-40', '41-60', '60+'
      OR group names like 'Group A', 'Beginner', etc.
    - First data column contains 'Week' label
    """
    h = [str(x or "").lower() for x in headers]
    has_key_components = any("key" in x and "component" in x for x in h)
    has_group_cols = sum(
        1 for x in h
        if re.search(r"<\d+|\d+-\d+|\d+\+|group [a-z]|beginner|intermediate|advanced", x)
    ) >= 2
    return has_key_components or has_group_cols


def parse_mcr_layout(
    workbook_path: str,
    athlete_group: str,         # e.g. "GB 13.1 26-40" — which column to extract
    athlete_id: str,
    plan_start_date: date = None  # if None, read from sheet dates
) -> list[dict]:
    """
    Parse an MCR-style multi-group coach plan.
    
    athlete_group: the column header of this athlete's ability group.
                   Stored in athlete profile — selected once at plan import.
    """
    import openpyxl
    wb = openpyxl.load_workbook(workbook_path, data_only=True)
    all_sessions = []
    
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        all_rows = [[cell.value for cell in row] for row in ws.iter_rows()]
        
        # Find header row — the row containing the group column names
        header_row_idx, headers = find_mcr_header_row(all_rows)
        if header_row_idx is None:
            continue
        
        # Find which column index corresponds to this athlete's group
        group_col_idx = find_group_column(headers, athlete_group)
        if group_col_idx is None:
            # This tab doesn't have this athlete's group — skip
            continue
        
        # Also capture column indices for context fields
        col = build_mcr_column_map(headers)
        
        # Parse goal race from sheet name or title row
        goal_race = infer_goal_race_from_sheet(sheet_name, all_rows[:3])
        
        # Parse weeks
        data_rows = all_rows[header_row_idx + 1:]
        sessions = parse_mcr_weeks(
            data_rows, col, group_col_idx, goal_race,
            athlete_id, plan_start_date
        )
        all_sessions.extend(sessions)
    
    return all_sessions


def find_mcr_header_row(all_rows: list) -> tuple[int | None, list]:
    """Find the row index containing group column headers."""
    for i, row in enumerate(all_rows):
        row_text = [str(c or "").lower().strip() for c in row]
        # Header row has 'week', 'date', and at least 2 group-like columns
        has_week = any("week" in t for t in row_text)
        has_date = any("date" in t or "mon" in t for t in row_text)
        group_count = sum(
            1 for t in row_text
            if re.search(r"<\d+|\d+-\d+|\d+\+|group [a-z]|bk\s*\d|gb\s*\d", t)
        )
        if has_week and has_date and group_count >= 2:
            return i, [str(c or "") for c in row]
    return None, []


def find_group_column(headers: list[str], athlete_group: str) -> int | None:
    """Find column index for the athlete's group, with fuzzy matching."""
    target = athlete_group.lower().strip()
    for i, h in enumerate(headers):
        if h.lower().strip() == target:
            return i
    # Fuzzy: strip spaces, compare
    for i, h in enumerate(headers):
        if target.replace(" ", "") == h.lower().strip().replace(" ", ""):
            return i
    return None


def build_mcr_column_map(headers: list[str]) -> dict:
    """Map semantic field names to column indices."""
    col = {}
    for i, h in enumerate(headers):
        hl = h.lower().strip()
        if "week" in hl and len(hl) < 8:
            col["week"] = i
        elif "date" in hl or "mon start" in hl:
            col["date"] = i
        elif "key" in hl and "component" in hl:
            col["session_type"] = i
        elif "weekly" in hl and "%" in hl:
            col["weekly_pct"] = i
        elif "race" in hl or "track" in hl:
            col["race_notes"] = i
    return col


def infer_goal_race_from_sheet(sheet_name: str, title_rows: list) -> str:
    """Extract the goal race type from sheet name or title rows."""
    text = sheet_name.lower() + " ".join(
        str(c or "").lower() for row in title_rows for c in row
    )
    if "ironman" in text or "im " in text:      return "ironman"
    if "70.3" in text or "half iron" in text:   return "70.3"
    if "13.1" in text or "half mar" in text:    return "half_marathon"
    if "marathon" in text:                       return "marathon"
    if "5k" in text:                             return "5k"
    if "10k" in text:                            return "10k"
    if "triathlon" in text or "tri" in text:     return "triathlon"
    return "running"


# ── Day mapping from MCR row labels ──────────────────────────────────────────

MCR_DAY_MAP = {
    "mon optional":  (0, True),    # Monday, optional
    "mon":           (0, False),
    "weds workout":  (2, False),   # Wednesday
    "weds":          (2, False),
    "wednesday":     (2, False),
    "long run":      (5, False),   # Saturday
    "lr":            (5, False),
    "sat":           (5, False),
    "pace work":     (4, False),   # Friday or wherever fits — context-dependent
    "tues":          (1, False),
    "thurs":         (3, False),
    "sun":           (6, False),
}

def map_session_day(row_label: str) -> tuple[int, bool]:
    """
    Map a Key Weekly Components label to (day_offset_from_monday, is_optional).
    day_offset: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
    """
    label = row_label.lower().strip()
    for key, value in MCR_DAY_MAP.items():
        if key in label:
            return value
    return (2, False)  # default to Wednesday if unknown


def parse_mcr_weeks(
    data_rows: list,
    col: dict,
    group_col_idx: int,
    goal_race: str,
    athlete_id: str,
    plan_start_date: date | None
) -> list[dict]:
    """
    Parse week/session rows from an MCR-layout plan.
    Each week has 3-4 rows; week number and date come from col A/B/C.
    """
    sessions = []
    current_week_num = None
    current_week_date = None
    current_mesocycle = None
    current_weekly_pct = None

    for row in data_rows:
        if not any(c for c in row if c is not None):
            continue  # skip blank rows

        # Detect mesocycle label (merged cell spanning multiple weeks)
        # Typically in column A or B, text like "1st Mesocycle", "2nd Mesocycle"
        row_a = str(row[0] or "").strip()
        if "mesocycle" in row_a.lower() or "macrocycle" in row_a.lower():
            current_mesocycle = row_a
            continue

        # Detect week number from col B
        week_val = str(row[col.get("week", 1)] or "").strip()
        if week_val.isdigit():
            current_week_num = int(week_val)

        # Detect week start date from col C
        date_val = row[col.get("date", 2)]
        if date_val:
            try:
                if isinstance(date_val, (datetime, date)):
                    current_week_date = date_val if isinstance(date_val, date) else date_val.date()
                else:
                    from dateutil import parser as dp
                    current_week_date = dp.parse(str(date_val)).date()
            except Exception:
                pass

        # Get session type / row label from Key Weekly Components column
        session_type_raw = str(row[col.get("session_type", 3)] or "").strip()
        if not session_type_raw:
            continue

        # Get weekly intensity %
        pct_val = row[col.get("weekly_pct", -1)] if "weekly_pct" in col else None
        if pct_val and str(pct_val).strip().rstrip("%").isdigit():
            current_weekly_pct = int(str(pct_val).strip().rstrip("%"))

        # Get this athlete's workout text
        if group_col_idx >= len(row):
            continue
        workout_text = str(row[group_col_idx] or "").strip()

        # Skip N/A and blank sessions
        if not workout_text or workout_text.upper() in ("N/A", "NA", "-", "REST", "OFF"):
            continue

        # Resolve session date
        if current_week_date:
            day_offset, is_optional = map_session_day(session_type_raw)
            session_date = current_week_date + timedelta(days=day_offset)
        else:
            session_date = plan_start_date + timedelta(weeks=(current_week_num or 1) - 1)

        session = parse_mcr_workout_text(
            workout_text=workout_text,
            session_type_label=session_type_raw,
            session_date=session_date,
            goal_race=goal_race,
            week_num=current_week_num,
            mesocycle=current_mesocycle,
            weekly_pct=current_weekly_pct,
            is_optional=(session_type_raw.lower().startswith("mon optional"))
        )
        sessions.append(session)

    return sessions


def parse_mcr_workout_text(
    workout_text: str,
    session_type_label: str,
    session_date: date,
    goal_race: str,
    week_num: int | None,
    mesocycle: str | None,
    weekly_pct: int | None,
    is_optional: bool
) -> dict:
    """
    Parse an MCR workout cell into a planned session dict.
    Handles MCR-specific notation conventions.
    """
    lines = [l.strip() for l in workout_text.strip().splitlines() if l.strip()]
    primary = lines[0] if lines else workout_text
    detail_lines = lines[1:]

    # Determine sport from session type label
    sport = infer_sport_from_mcr_label(session_type_label, primary)

    # Parse distance from LR lines: "LR: 7-9 Miles" → use midpoint
    distance_m = extract_mcr_distance(primary)
    duration_min = extract_duration(primary)

    # Parse specific MCR workout patterns
    structure = parse_mcr_notation(lines, sport, goal_race)

    return {
        "planned_date": session_date.isoformat(),
        "sport": sport,
        "title": build_mcr_title(session_type_label, primary),
        "coaching_text": workout_text,
        "planned_duration_min": duration_min,
        "planned_distance_m": distance_m,
        "structure": structure,
        "meta": {
            "week": week_num,
            "mesocycle": mesocycle,
            "weekly_intensity_pct": weekly_pct,
            "is_optional": is_optional,
            "session_type": session_type_label,
            "goal_race": goal_race,
        }
    }


def infer_sport_from_mcr_label(label: str, text: str) -> str:
    """MCR plans are run-focused but may include cross-training."""
    label_lower = label.lower()
    text_lower = text.lower()
    # All sessions in MCR plans are running unless explicitly stated
    if any(w in label_lower + text_lower for w in ("swim", "pool", "css")):
        return "swim"
    if any(w in label_lower + text_lower for w in ("bike", "ride", "cycle", "zwift")):
        return "bike"
    if any(w in label_lower + text_lower for w in ("strength", "gym", "weights")):
        return "strength"
    if any(w in label_lower + text_lower for w in ("yoga", "stretch", "mobility")):
        return "mobility"
    return "run"


def extract_mcr_distance(text: str) -> float | None:
    """
    Extract distance from MCR notation.
    "LR: 7-9 Miles" → midpoint 8 miles → 12875m
    "LR: 8 Miles" → 8 miles → 12875m
    "5-6 Miles" → midpoint 5.5 miles
    """
    t = text.lower()
    # Range: 7-9 miles or 7-9 Miles
    m = re.search(r"(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*(mile|km|k\b)", t)
    if m:
        low, high = float(m.group(1)), float(m.group(2))
        mid = (low + high) / 2
        mult = 1000 if "km" in m.group(3) or m.group(3) == "k" else 1609
        return round(mid * mult)
    # Single: 8 miles
    m = re.search(r"(\d+\.?\d*)\s*(mile|km|k\b)", t)
    if m:
        mult = 1000 if "km" in m.group(2) or m.group(2) == "k" else 1609
        return round(float(m.group(1)) * mult)
    # Metres
    m = re.search(r"(\d+)\s*m\b", t)
    if m:
        return int(m.group(1))
    return None


def build_mcr_title(session_type: str, primary_line: str) -> str:
    """Build a readable session title from the session type label and first text line."""
    session_type = session_type.strip()
    # Clean up primary line — strip LR: prefix, etc.
    clean_primary = re.sub(r"^(lr|long run|wu|cd)\s*:\s*", "", primary_line.strip(),
                           flags=re.IGNORECASE).strip()
    if clean_primary and clean_primary.lower() not in session_type.lower():
        return f"{session_type} — {clean_primary}"
    return session_type


def parse_mcr_notation(lines: list[str], sport: str, goal_race: str) -> dict:
    """
    Parse MCR-specific workout notation into structured sets.
    Handles all the patterns visible in the MCR Spring Training plan.
    """
    all_text = " ".join(lines).lower()
    warmup, main_sets, cooldown = [], [], []
    current_section = "main"

    for line in lines:
        line = line.strip()
        if not line:
            continue
        ll = line.lower()

        # Section detection
        if ll.startswith("wu") or "warm" in ll[:6]:
            current_section = "warmup"
        elif ll.startswith("cd") or "cool" in ll[:6]:
            current_section = "cooldown"
        elif any(ll.startswith(x) for x in ("lr:", "long run", "cruise lr")):
            current_section = "main"

        parsed = parse_mcr_line(line, goal_race)

        if current_section == "warmup":
            warmup.append(parsed)
        elif current_section == "cooldown":
            cooldown.append(parsed)
        else:
            main_sets.append(parsed)

    return {"warmup": warmup, "main_sets": main_sets, "cooldown": cooldown}


def parse_mcr_line(line: str, goal_race: str) -> dict:
    """
    Parse a single MCR notation line.
    
    Handles patterns specific to this plan:
      "5-4-3-2-1min Tempo"              → descending ladder
      "Rest = half the next rep"         → rest descriptor
      "3x200"                            → straight repeats
      "4-5min@TP, 3x200h@8K, 4-5min@TP" → compound set
      "CRUISE LR: 8 Miles"               → cruise long run
      "LR: 7-9 Miles"                    → standard long run
      "first 20min easy"                 → paced block
      "middle 30min @ MP+45s"            → paced block with offset
      "cool down to 8-10 miles total"    → finish instruction
      "1600-2200m of hills, 7-9 reps"   → hill repeat volume
    """
    line = line.strip()
    ll = line.lower()

    # Descending/ascending ladder: "5-4-3-2-1min Tempo"
    ladder = re.match(r"([\d]+-[\d-]+min)\s+(.*)", line, re.IGNORECASE)
    if ladder and re.match(r"\d+(-\d+)+", ladder.group(1)):
        steps_raw = ladder.group(1)
        target_raw = ladder.group(2)
        durations = [int(x) for x in re.findall(r"\d+", steps_raw)]
        return {
            "type": "ladder",
            "steps_min": durations,
            "target": parse_run_target(target_raw),
            "raw": line
        }

    # Compound set: "4-5min@TP, 3x200h@8K, 4-5min@TP"
    if "," in line and "@" in line:
        parts = [p.strip() for p in line.split(",")]
        compound = []
        for part in parts:
            compound.append(parse_mcr_line(part, goal_race))
        if len(compound) > 1:
            return {"type": "compound", "sets": compound, "raw": line}

    # Range interval: "4-5min@TP" or "4-6min@TP"
    range_interval = re.match(r"(\d+)\s*[-–]\s*(\d+)\s*min\s*@?\s*(.*)", line, re.IGNORECASE)
    if range_interval:
        return {
            "type": "range_interval",
            "min_min": int(range_interval.group(1)),
            "max_min": int(range_interval.group(2)),
            "target": parse_run_target(range_interval.group(3)),
            "raw": line
        }

    # Hill notation: "1600-2200 meters of hills, 7-9 reps"
    hill = re.search(r"(\d+)[–-](\d+)\s*m.*hill", ll)
    if hill:
        return {
            "type": "hills",
            "min_distance_m": int(hill.group(1)),
            "max_distance_m": int(hill.group(2)),
            "raw": line
        }

    # Repeats with suffix codes: "3x200h@8K" (h=hills), "3x200@TP"
    repeat = re.match(r"(\d+)\s*[x×]\s*(\d+)\s*(h?)\s*@?\s*(.*)", line, re.IGNORECASE)
    if repeat:
        is_hill = repeat.group(3).lower() == "h"
        return {
            "type": "hills_repeat" if is_hill else "interval",
            "repeat": int(repeat.group(1)),
            "distance_m": int(repeat.group(2)),
            "target": parse_run_target(repeat.group(4)),
            "is_hill": is_hill,
            "raw": line
        }

    # Paced block: "middle 30min @ MP+45s", "first 20min easy"
    paced_block = re.match(
        r"(first|middle|last|final|next)?\s*(\d+\.?\d*)\s*(min|mile|km)\s*@?\s*(.*)",
        line, re.IGNORECASE
    )
    if paced_block:
        return {
            "type": "paced_block",
            "position": paced_block.group(1) or "main",
            "duration_min": float(paced_block.group(2)) if "min" in paced_block.group(3).lower() else None,
            "distance_m": (float(paced_block.group(2)) * 1609
                           if "mile" in paced_block.group(3).lower() else
                           float(paced_block.group(2)) * 1000
                           if "km" in paced_block.group(3).lower() else None),
            "target": parse_run_target(paced_block.group(4)),
            "raw": line
        }

    # LR / Cruise LR
    if ll.startswith("lr:") or ll.startswith("long run") or ll.startswith("cruise lr"):
        is_cruise = "cruise" in ll
        dist = extract_mcr_distance(line)
        return {
            "type": "cruise_long_run" if is_cruise else "long_run",
            "distance_m": dist,
            "raw": line
        }

    # Rest descriptor: "Rest = half the next rep", "2 min active rest btw all"
    if "rest" in ll or "recovery" in ll or "btw" in ll:
        return {"type": "rest_descriptor", "raw": line}

    # Fallthrough
    return {"type": "raw", "raw": line}


# ── MCR pace/target references ─────────────────────────────────────────────

MCR_TARGET_MAP = {
    # MCR uses these abbreviations extensively
    "tp":   {"type": "threshold_pace"},          # Threshold Pace
    "mp":   {"type": "marathon_pace"},            # Marathon Pace
    "hmp":  {"type": "race_pace", "distance": "half_marathon"},
    "8k":   {"type": "race_pace", "distance": "8k"},
    "5k":   {"type": "race_pace", "distance": "5k"},
    "10k":  {"type": "race_pace", "distance": "10k"},
    "goal": {"type": "goal_race_pace"},
    "gp":   {"type": "goal_race_pace"},
    "easy": {"type": "zone", "zone": 2},
    "z2":   {"type": "zone", "zone": 2},
    "z3":   {"type": "zone", "zone": 3},
    "z4":   {"type": "zone", "zone": 4},
}

def parse_run_target(text: str) -> dict:
    """Extended run target parser that includes MCR abbreviations."""
    if not text: return {"type": "none"}
    t = text.strip().lower()

    # MP offset: MP+45s, MP-30s (marathon pace ± seconds)
    mp_offset = re.match(r"mp\s*([+-]\s*\d+)\s*s?", t)
    if mp_offset:
        offset_str = mp_offset.group(1).replace(" ", "")
        return {"type": "marathon_pace_offset",
                "offset_sec_per_mile": int(offset_str)}

    # MCR abbreviations
    for abbrev, result in MCR_TARGET_MAP.items():
        if t == abbrev or t.startswith(abbrev + " ") or t.startswith(abbrev + "/"):
            return result

    # Zone
    m = re.search(r"z(?:one\s*)?(\d)", t)
    if m: return {"type": "zone", "zone": int(m.group(1))}

    # HR ceiling
    m = re.search(r"hr\s*[<≤]\s*(\d+)|[<≤]\s*(\d{3})\s*bpm?", t)
    if m: return {"type": "hr_ceiling", "hr_max": int(m.group(1) or m.group(2))}

    # Absolute pace: 7:30/mile, 4:30/km
    m = re.match(r"(\d+):(\d+)\s*(?:/\s*(?:mile|km|m))?", t)
    if m: return {"type": "absolute_pace",
                  "sec": int(m.group(1))*60+int(m.group(2))}

    return {"type": "raw", "raw": text}
```

### Wiring MCR Import into the Master Ingestion Router

```python
# Add to run_ingestion() in the master router:

def scan_spreadsheet_imports(athlete_id: str, athlete_group: str) -> list[dict]:
    """
    Scan the spreadsheet import folder and process any new files.
    Detects MCR layout automatically.
    """
    sessions = []
    for f in Path(SPREADSHEET_IMPORT_DIR).glob("*.xlsx"):
        if str(f) in get_processed_files():
            continue
        
        wb = openpyxl.load_workbook(str(f), data_only=True)
        first_sheet = wb[wb.sheetnames[0]]
        sample_rows = [[c.value for c in row] for row in first_sheet.iter_rows(max_row=5)]
        
        if is_mcr_layout([str(c or "") for c in sample_rows[1]], sample_rows):
            # MCR multi-group layout — use group-aware parser
            sessions.extend(
                parse_mcr_layout(str(f), athlete_group, athlete_id)
            )
        else:
            # Fall back to generic parser
            sessions.extend(
                ingest_spreadsheet_plan(f, athlete_id, plan_start_date=None)
            )
    
    return sessions
```

### Athlete Profile — Group Selection

The athlete's group column is stored in their profile so it's applied automatically on every import:

```python
athlete_profile = {
    # ... other fields ...
    "spreadsheet_group": "GB 13.1 26-40",  # set once at profile creation
    # Maps to the column header in their coach's plan spreadsheet
    # Examples: "BK 5k <25", "GB 13.1 60+", "Group B", "Intermediate"
}
```



---

## Swim & Run Workout Notation Parser

Coach spreadsheets use sport-specific shorthand. This parser handles the common notations for swim and run sessions.

### Swim Notation

```python
# Common swim notation:
#   "400m warmup easy"
#   "8x100 @ CSS / 20s rest"
#   "8x100 @ CSS+5 / 20s"       ← CSS+5 = 5sec/100m slower than CSS
#   "4x200 descend 1-4"          ← each rep faster
#   "3x(4x50 @ Z4/10s) / 2min"  ← nested sets
#   "800m pull buoy"
#   "400m kick"

def parse_swim_notation(lines: list[str]) -> dict:
    warmup, main_sets, cooldown = [], [], []
    current = "main"
    for line in lines:
        line = line.strip()
        if not line: continue
        ll = line.lower()
        if any(w in ll for w in ("warm","wu","w/u")): current = "warmup"
        elif any(w in ll for w in ("cool","cd","c/d","easy down")): current = "cooldown"
        elif any(w in ll for w in ("main set","ms:")): current = "main"
        parsed = parse_swim_line(line)
        (warmup if current == "warmup" else cooldown if current == "cooldown" else main_sets).append(parsed)
    return {"warmup": warmup, "main_sets": main_sets, "cooldown": cooldown}


def parse_swim_line(line: str) -> dict:
    line = line.strip()

    # Nested: 3x(4x50 @ Z4/10s) / 2min
    nested = re.match(r"(\d+)\s*[x×]\s*\((.+?)\)\s*(?:/\s*(.+))?", line)
    if nested:
        return {
            "type": "nested",
            "outer_repeat": int(nested.group(1)),
            "inner_set": parse_swim_line(nested.group(2)),
            "group_rest_sec": parse_rest(nested.group(3) or "")
        }

    # Standard interval: Nx distance @ target / rest
    interval = re.match(
        r"(\d+)\s*[x×]\s*(\d+)\s*m?\s*(?:@\s*([^\n/]+?))?(?:\s*/\s*(.+))?$",
        line, re.IGNORECASE
    )
    if interval:
        return {
            "type": "interval",
            "repeat": int(interval.group(1)),
            "distance_m": int(interval.group(2)),
            "target": parse_swim_target(interval.group(3) or ""),
            "rest_sec": parse_rest(interval.group(4) or ""),
            "raw": line
        }

    # Single block: 400m easy, 800m pull
    single = re.match(r"(\d+)\s*m?\s*(.*)", line, re.IGNORECASE)
    if single:
        desc = single.group(2).strip()
        return {
            "type": "single",
            "distance_m": int(single.group(1)),
            "target": parse_swim_target(desc),
            "modifier": detect_swim_modifier(desc),
            "raw": line
        }

    return {"type": "raw", "raw": line}


def parse_swim_target(text: str) -> dict:
    if not text: return {"type": "none"}
    t = text.strip().lower()

    # CSS offset: CSS+5, CSS-3, CSS
    m = re.match(r"css\s*([+-]\s*\d+)?", t)
    if m:
        offset_str = (m.group(1) or "0").replace(" ", "")
        return {"type": "css_offset", "offset_sec": int(offset_str) if offset_str not in ("","0") else 0}

    # Zone: Z3, zone 4
    m = re.search(r"z(?:one\s*)?(\d)", t)
    if m: return {"type": "pace_zone", "zone": int(m.group(1))}

    # Named intensities
    for keyword, result in [
        ("easy", {"type":"rpe","rpe":3}), ("moderate", {"type":"rpe","rpe":5}),
        ("hard", {"type":"rpe","rpe":7}), ("race pace", {"type":"race_pace"}),
        ("threshold", {"type":"css_offset","offset_sec":0}),
    ]:
        if keyword in t: return result

    # Absolute pace: 1:45/100m
    m = re.match(r"(\d+):(\d+)", t)
    if m: return {"type": "absolute_pace", "sec_per_100m": int(m.group(1))*60+int(m.group(2))}

    return {"type": "raw", "raw": text}


def detect_swim_modifier(text: str) -> str | None:
    t = text.lower()
    for kw, tag in [("pull","pull_buoy"),("kick","kickboard"),("paddle","paddles"),
                    ("drill","drill"),("descend","descend"),("build","build"),
                    ("negative split","neg_split"),("bilateral","bilateral_breathing")]:
        if kw in t: return tag
    return None


def parse_rest(text: str) -> int:
    if not text: return 0
    t = text.strip().lower()
    for pattern, fn in [
        (r"(\d+)\s*min", lambda m: int(m.group(1))*60),
        (r"(\d+):(\d+)", lambda m: int(m.group(1))*60+int(m.group(2))),
        (r"(\d+)\s*s",   lambda m: int(m.group(1))),
        (r"(\d+)",       lambda m: int(m.group(1))),
    ]:
        m = re.search(pattern, t)
        if m: return fn(m)
    return 0
```

### Run Notation

```python
def parse_run_notation(lines: list[str]) -> dict:
    warmup, main_sets, cooldown = [], [], []
    current = "main"
    for line in lines:
        line = line.strip()
        if not line: continue
        ll = line.lower()
        if any(w in ll for w in ("warm","wu","easy first")): current = "warmup"
        elif any(w in ll for w in ("cool","cd","easy last","easy finish")): current = "cooldown"
        parsed = parse_run_line(line)
        (warmup if current=="warmup" else cooldown if current=="cooldown" else main_sets).append(parsed)
    return {"warmup": warmup, "main_sets": main_sets, "cooldown": cooldown}


def parse_run_line(line: str) -> dict:
    line = line.strip()

    # Intervals: 6x800m @ 5k pace / 400m jog
    m = re.match(
        r"(\d+)\s*[x×]\s*(\d+\.?\d*)\s*(m|km|mile|min|sec)\s*"
        r"(?:@\s*([^\n/]+?))?(?:\s*/\s*(.+))?$",
        line, re.IGNORECASE
    )
    if m:
        amount, unit = float(m.group(2)), m.group(3).lower()
        dist = ({"m": amount, "km": amount*1000, "mile": amount*1609}.get(unit)
                if unit in ("m","km","mile","miles") else None)
        dur = ({"min": amount*60, "sec": amount}.get(unit)
               if unit in ("min","sec") else None)
        return {
            "type": "interval",
            "repeat": int(m.group(1)),
            "distance_m": dist,
            "duration_sec": dur,
            "target": parse_run_target(m.group(4) or ""),
            "recovery": parse_run_recovery(m.group(5) or ""),
            "raw": line
        }

    # Steady block: 20min easy, 30min Z2
    m = re.match(r"(\d+\.?\d*)\s*(min|km|miles?)\s*(.*)", line, re.IGNORECASE)
    if m:
        unit = m.group(2).lower()
        return {
            "type": "steady",
            "duration_min": float(m.group(1)) if "min" in unit else None,
            "distance_m": (float(m.group(1)) * (1000 if "km" in unit else 1609))
                          if "min" not in unit else None,
            "target": parse_run_target(m.group(3)),
            "raw": line
        }

    return {"type": "raw", "raw": line}


def parse_run_target(text: str) -> dict:
    if not text: return {"type": "none"}
    t = text.strip().lower()
    for ref, result in [
        ("5k pace",        {"type":"race_pace","distance":"5k"}),
        ("10k pace",       {"type":"race_pace","distance":"10k"}),
        ("marathon pace",  {"type":"race_pace","distance":"marathon"}),
        ("threshold",      {"type":"threshold"}),
        ("tempo",          {"type":"threshold"}),
        ("easy",           {"type":"zone","zone":2}),
        ("recovery",       {"type":"zone","zone":1}),
        ("hard",           {"type":"zone","zone":4}),
    ]:
        if ref in t: return result
    m = re.search(r"z(?:one\s*)?(\d)", t)
    if m: return {"type": "zone", "zone": int(m.group(1))}
    m = re.search(r"hr\s*[<≤]\s*(\d+)|[<≤]\s*(\d{3})\s*bpm", t)
    if m: return {"type": "hr_ceiling", "hr_max": int(m.group(1) or m.group(2))}
    m = re.match(r"(\d+):(\d+)\s*(?:/\s*(?:km|mile))?", t)
    if m: return {"type": "absolute_pace", "sec_per_km": int(m.group(1))*60+int(m.group(2))}
    return {"type": "raw", "raw": text}


def parse_run_recovery(text: str) -> dict:
    if not text: return {"type": "none"}
    t = text.strip().lower()
    if "jog" in t: return {"type": "jog", "distance_m": extract_distance(t), "duration_min": extract_duration(t)}
    if "walk" in t: return {"type": "walk", "duration_min": extract_duration(t)}
    rest_sec = parse_rest(t)
    if rest_sec > 0: return {"type": "rest", "duration_sec": rest_sec}
    return {"type": "raw", "raw": text}
```

---

## Swim Session Classification from FIT Data

When no structured planned session exists, classify the completed swim from lap data.

```python
def classify_swim_session(fit_data: dict, css_sec_per_100m: float) -> dict:
    """
    Classify a completed swim from FIT lap data.
    Garmin pool swim records each length/lap separately — interval structure is detectable.
    """
    laps = fit_data.get("laps", [])
    if not laps:
        return {"session_type": "unstructured"}

    total_dist = sum(l.get("total_distance", 0) for l in laps)
    duration_sec = fit_data.get("duration_sec", 1)
    avg_pace = (duration_sec / total_dist) * 100 if total_dist else None  # sec/100m

    # Separate active laps from rest laps (short-duration, standing between sets)
    active = [l for l in laps if l.get("total_distance", 0) > 25]
    rest_laps = [l for l in laps if 0 < l.get("total_distance", 0) <= 25]

    # Detect interval structure from repeated same-distance laps
    if len(rest_laps) >= 3:
        intervals = detect_swim_intervals(active, rest_laps)
        if intervals:
            return {
                "session_type": "interval",
                "effort": classify_swim_effort(avg_pace, css_sec_per_100m),
                "detected_sets": intervals,
                "total_distance_m": total_dist
            }

    # Continuous swim — classify by pace vs CSS
    if avg_pace and css_sec_per_100m:
        ratio = avg_pace / css_sec_per_100m
        session_type = (
            "threshold_or_above" if ratio < 0.95 else
            "css_pace"           if ratio < 1.05 else
            "aerobic"            if ratio < 1.25 else
            "easy_recovery"
        )
    else:
        session_type = "unclassified"

    return {"session_type": session_type, "total_distance_m": total_dist,
            "avg_pace_sec_100m": round(avg_pace, 1) if avg_pace else None}


def detect_swim_intervals(active_laps: list, rest_laps: list) -> list | None:
    from collections import Counter
    distances = [round(l.get("total_distance", 0) / 25) * 25 for l in active_laps]
    dist_counts = Counter(distances)
    dominant_dist, dominant_count = dist_counts.most_common(1)[0]
    if dominant_count < 3:
        return None

    dominant = [l for l, d in zip(active_laps, distances) if d == dominant_dist]
    avg_lap_time = sum(l.get("total_timer_time", 0) for l in dominant) / len(dominant)
    avg_pace = (avg_lap_time / dominant_dist) * 100
    avg_rest = (sum(l.get("total_timer_time", 0) for l in rest_laps) / len(rest_laps)
                if rest_laps else 0)

    return [{"repeat": dominant_count, "distance_m": dominant_dist,
             "avg_pace_sec_100m": round(avg_pace, 1), "avg_rest_sec": round(avg_rest)}]


def classify_swim_effort(pace: float | None, css: float) -> str:
    if not pace: return "unknown"
    r = pace / css
    if r < 0.95: return "above_css"
    if r < 1.02: return "css"
    if r < 1.10: return "aerobic_threshold"
    if r < 1.25: return "aerobic"
    return "easy_recovery"
```


---

### Zwift .zwo Parser

For historical rides, reconstruct the planned session from the .zwo file that was active at the time of the ride.

```python
import xml.etree.ElementTree as ET

def parse_zwo(filepath: str, ftp_at_time: float) -> dict:
    """
    Parse Zwift .zwo XML into unified planned_session schema.
    ftp_at_time: FTP value active when session was planned (for absolute watts).
    """
    tree = ET.parse(filepath)
    root = tree.getroot()
    
    workout_name = root.find("name").text if root.find("name") is not None else "Zwift Workout"
    
    sets = []
    for elem in root.find("workout") or []:
        tag = elem.tag
        
        if tag == "Warmup":
            duration = int(elem.get("Duration", 0))
            power_high = float(elem.get("PowerHigh", 0.5)) * ftp_at_time
            sets.append({"type": "warmup", "duration_sec": duration, "power_high_w": power_high})
        
        elif tag == "SteadyState":
            sets.append({
                "type": "steady",
                "duration_sec": int(elem.get("Duration", 0)),
                "power_w": float(elem.get("Power", 0)) * ftp_at_time
            })
        
        elif tag == "IntervalsT":
            on_power = float(elem.get("OnPower", 0)) * ftp_at_time
            off_power = float(elem.get("OffPower", 0)) * ftp_at_time
            sets.append({
                "type": "interval",
                "repeat": int(elem.get("Repeat", 1)),
                "on_sec": int(elem.get("OnDuration", 0)),
                "off_sec": int(elem.get("OffDuration", 0)),
                "on_power_w": on_power,
                "off_power_w": off_power
            })
        
        elif tag == "Cooldown":
            sets.append({"type": "cooldown", "duration_sec": int(elem.get("Duration", 0))})
    
    return {
        "source_platform": "zwift",
        "sport": "bike",
        "title": workout_name,
        "structure": {"main_sets": sets}
    }
```

### Garmin Connect Planned Workouts

> **Library status note:** `garth` is deprecated — Garmin changed their auth flow and broke it. Use `python-garminconnect` (cyberjunky) or `garmy` for current integrations. Both carry the same structural risk: they reverse-engineer Garmin's unofficial mobile app API. The file-watch fallback below ensures the pipeline keeps running if either breaks.

```python
# Current working library — as of March 2026
# pip install garminconnect
from garminconnect import Garmin

def get_garmin_client(email: str, password: str, token_dir: str = "~/.garminconnect") -> Garmin:
    """
    Initialise Garmin client with token persistence.
    Tokens saved to disk — avoids re-login on every run.
    If login fails (auth change), falls back to file-watch path.
    """
    client = Garmin(email=email, password=password, is_cn=False,
                    prompt_mfa=lambda: input("MFA code: "))
    try:
        client.login(token_dir)
    except Exception as e:
        log_api_failure("garmin_login", str(e))
        notify("⚠️ Garmin API login failed", f"Error: {e}. Drop FIT exports into /imports/garmin/fit/")
        raise GarminAPIUnavailable(e)
    return client

def get_garmin_planned_workouts(client: Garmin, start_date: str, end_date: str) -> list:
    """Fetch planned workouts from Garmin Connect calendar."""
    try:
        calendar = client.get_workout_list(start_date, end_date)
        workouts = []
        for entry in (calendar or []):
            if entry.get("workoutId"):
                detail = client.get_workout(entry["workoutId"])
                workouts.append(normalise_garmin_workout(detail))
        return workouts
    except Exception as e:
        log_api_failure("garmin_planned_workouts", str(e))
        return []  # pipeline continues — file-watch path picks up the slack
```

### File-Watch Ingestion — Garmin

```python
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import fitparse

GARMIN_IMPORT_DIR = Path("/imports/garmin/fit")

def process_fit_file(fit_path: Path) -> dict | None:
    """
    Parse a FIT file into the unified activity schema.
    Called both by the file watcher and the API pipeline — same output shape.
    """
    try:
        fitfile = fitparse.FitFile(str(fit_path))
        return extract_activity_from_fit(fitfile)
    except Exception as e:
        log_parse_error(fit_path, e)
        return None

def scan_import_folder(folder: Path) -> list:
    """
    Process any FIT files dropped into the import folder since last run.
    Marks processed files to avoid re-ingestion.
    """
    processed = get_processed_files()
    new_files = [f for f in folder.glob("*.fit") if str(f) not in processed]
    
    activities = []
    for fit_path in sorted(new_files):
        activity = process_fit_file(fit_path)
        if activity:
            upsert_activity(activity)
            mark_processed(str(fit_path))
            activities.append(activity)
    
    return activities

class FitFileWatcher(FileSystemEventHandler):
    """Watches the import folder and processes FIT files as they arrive."""
    def on_created(self, event):
        if event.src_path.endswith(".fit"):
            activity = process_fit_file(Path(event.src_path))
            if activity:
                upsert_activity(activity)
                mark_processed(event.src_path)
```



---

## Plan vs Actual Comparison Engine

### Core Execution Scoring

```python
def score_execution(planned: dict, actual: dict) -> dict:
    """
    Compare planned vs actual session. Returns execution score dict.
    actual comes from Garmindb activity record + FIT file analysis.
    planned comes from unified planned_session schema.
    """
    
    tss_ratio = safe_ratio(actual.get("tss"), planned.get("planned_tss"))
    duration_ratio = safe_ratio(actual.get("duration_min"), planned.get("planned_duration_min"))
    if_delta = safe_delta(actual.get("intensity_factor"), planned.get("planned_if"))
    
    # Set completion — requires structured interval extraction from FIT file
    planned_sets = count_planned_sets(planned.get("structure", {}))
    actual_sets = count_actual_sets(actual.get("fit_data"))
    set_ratio = safe_ratio(actual_sets, planned_sets)
    
    # Zone distribution comparison
    planned_zones = planned.get("zone_distribution", {})
    actual_zones = extract_zone_distribution(actual.get("fit_data"))
    zone_delta = compare_zone_distribution(planned_zones, actual_zones)
    
    return {
        "session_date": planned["planned_date"],
        "sport": planned["sport"],
        "tss_ratio": tss_ratio,                # 0.94 = completed 94% of planned TSS
        "duration_ratio": duration_ratio,
        "if_delta": if_delta,                  # positive = went harder than planned
        "set_completion": set_ratio,
        "zone_delta": zone_delta,
        "overall_execution": weighted_score(tss_ratio, duration_ratio, set_ratio),
        "flags": generate_flags(tss_ratio, if_delta, set_ratio)
    }

def generate_flags(tss_ratio, if_delta, set_ratio) -> list:
    flags = []
    if tss_ratio and tss_ratio > 1.15:
        flags.append("OVERCOOKED: TSS significantly exceeded plan")
    if tss_ratio and tss_ratio < 0.75:
        flags.append("UNDERDELIVERED: TSS significantly below plan")
    if if_delta and if_delta > 0.10:
        flags.append("TOO_HARD: Went well above planned intensity")
    if set_ratio and set_ratio < 0.80:
        flags.append("BAILED: Significant set dropout")
    return flags
```

### Sport-Specific TSS Calculation

```python
def calculate_bike_tss(power_data: list, ftp: float, duration_sec: int) -> float:
    """Standard TSS from power data."""
    np = calculate_normalized_power(power_data)
    intensity_factor = np / ftp
    tss = (duration_sec * np * intensity_factor) / (ftp * 3600) * 100
    return round(tss, 1)

def calculate_run_tss(hr_data: list, lthr: float, duration_sec: int) -> float:
    """hrTSS using lactate threshold HR."""
    trimp = calculate_trimp(hr_data, lthr, duration_sec)
    # hrTSS ≈ TRIMP / 100 * some scaling factor — calibrate from your data
    return round(trimp * 0.8, 1)

def calculate_swim_tss(pace_per_100m: float, css_pace: float, duration_sec: int) -> float:
    """
    Swim Stress Score using CSS as threshold reference.
    Analogous to IF for power — swim_if = css_pace / actual_pace.
    For pace, lower is faster: IF > 1 means faster than CSS (harder).
    """
    swim_if = css_pace / pace_per_100m
    duration_hr = duration_sec / 3600
    sss = (swim_if ** 2) * duration_hr * 100
    return round(sss, 1)

def calculate_strength_tss(exercises: list, duration_min: int) -> float:
    """
    Estimated strength TSS using volume load proxy.
    Rough but trackable — calibrate coefficient from HR data over time.
    """
    volume_load = sum(e["sets"] * e["reps"] * (e.get("weight_kg", 0) / 100) for e in exercises)
    rpe_modifier = sum(e.get("rpe", 7) for e in exercises) / len(exercises) / 10 if exercises else 0.7
    base_tss = duration_min * 0.5 * rpe_modifier          # ~30 TSS/hr at moderate RPE
    return round(min(base_tss + volume_load * 0.1, 80), 1) # cap at 80 for a single session

def calculate_climb_tss(hr_data: list, lthr: float, duration_sec: int, elevation_m: float) -> float:
    """hrTSS equivalent for climbing — uses sustained HR."""
    base = calculate_run_tss(hr_data, lthr, duration_sec)  # same HR approach
    elevation_bonus = elevation_m * 0.01                    # small bonus for gained elevation
    return round(base + elevation_bonus, 1)

def calculate_yoga_tss(subtype: str, duration_min: int) -> float:
    """
    Yoga TSS by subtype. Recovery sessions contribute negatively to fatigue
    but this is modeled as a reduced ATL contribution rather than negative TSS.
    """
    coefficients = {
        "hot_yoga": 0.5,        # ~30 TSS/hr
        "vinyasa": 0.4,
        "hatha": 0.25,
        "restorative": 0.05,    # near zero — active recovery
        "mobility": 0.05,
        "stretching": 0.02
    }
    coeff = coefficients.get(subtype, 0.3)
    return round(duration_min * coeff, 1)
```

---

## Cross-Training Logging

### Strength Session Schema & Storage

```python
def log_strength_session(session: dict) -> None:
    """
    Store strength session with computed TSS to PostgreSQL.
    Schema: strength_sessions table.
    """
    tss = calculate_strength_tss(session["exercises"], session["duration_min"])
    
    record = {
        "session_date": session["date"],
        "type": "strength",
        "subtype": session.get("subtype", "gym"),       # gym | bodyweight | climbing_gym | climbing_outdoor
        "duration_min": session["duration_min"],
        "planned_tss": session.get("planned_tss"),
        "actual_tss": tss,
        "exercises": json.dumps(session["exercises"]),   # JSONB in PostgreSQL
        "notes": session.get("notes", ""),
        "rpe_avg": sum(e.get("rpe", 7) for e in session["exercises"]) / len(session["exercises"]),
        "recovery_impact": classify_recovery_impact(tss, session.get("subtype"))
    }
    db.execute("INSERT INTO strength_sessions VALUES %s", record)

def classify_recovery_impact(tss: float, subtype: str) -> str:
    """Tag recovery impact for LLM context."""
    if subtype in ("restorative", "stretching", "mobility"):
        return "positive"
    if tss > 60:
        return "elevated"
    if tss > 35:
        return "standard"
    return "low"
```

### Garmin Activity Type Mapping for Cross-Training

```python
GARMIN_CROSS_TRAINING_MAP = {
    "ROCK_CLIMBING": ("climb", "climbing_outdoor"),
    "INDOOR_CLIMBING": ("climb", "climbing_gym"),
    "YOGA": ("yoga", "hatha"),              # default — refine from activity name
    "FITNESS_EQUIPMENT": ("strength", "gym"),
    "TRAINING": ("strength", "bodyweight"),
    "HIKING": ("climb", "hiking"),          # low TSS but leg load
    "WALKING": None,                         # skip — too low load
}

def map_garmin_cross_training(activity: dict) -> dict | None:
    """Convert Garmin activity type to cross-training session schema."""
    mapping = GARMIN_CROSS_TRAINING_MAP.get(activity["activityType"])
    if not mapping:
        return None
    
    sport, subtype = mapping
    
    if sport == "climb":
        tss = calculate_climb_tss(
            activity.get("hr_data", []),
            activity.get("lthr", 155),
            activity["duration_sec"],
            activity.get("elevation_gain_m", 0)
        )
    elif sport == "yoga":
        # Refine subtype from activity name
        subtype = classify_yoga_subtype(activity.get("name", ""))
        tss = calculate_yoga_tss(subtype, activity["duration_min"])
    else:
        tss = estimate_tss_from_hr(activity)
    
    return {
        "session_date": activity["date"],
        "type": sport,
        "subtype": subtype,
        "duration_min": activity["duration_min"],
        "actual_tss": tss,
        "source": "garmin_auto"
    }
```

---

## Season Planning

### URL-Based Event Extraction

```python
import requests
from bs4 import BeautifulSoup

def extract_event_from_url(url: str, llm_client) -> dict:
    """
    Fetch event page and use LLM to extract race details.
    Handles most structured race registration sites.
    """
    # Fetch page content
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    soup = BeautifulSoup(resp.content, "html.parser")
    
    # Strip navigation, footers, scripts — keep main content
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)[:5000]   # token budget
    
    extraction_prompt = f"""Extract race event details from this page. Return JSON only. No preamble.

Required fields:
- name: string
- date: ISO 8601 date string (YYYY-MM-DD)
- location: city, state/country string
- sport: triathlon | running | cycling | multisport | obstacle
- format: Olympic | 70.3 | Ironman | marathon | half_marathon | 10k | 5k | gran_fondo | enduro | other
- distance_label: human readable e.g. "Olympic Distance" or "13.1 miles"

Optional fields (include if present):
- swim_distance_m: integer
- bike_distance_km: float
- run_distance_km: float
- elevation_gain_m: integer
- registration_deadline: ISO 8601 date string
- event_url: the source URL

Page content:
{text}"""

    response = llm_client.generate(extraction_prompt)
    event = json.loads(response)
    event["source_url"] = url
    event["extracted_at"] = date.today().isoformat()
    return event

def classify_and_store_event(event: dict, priority: str) -> dict:
    """
    Store event with A/B/C priority and compute taper/recovery windows.
    """
    event_date = date.fromisoformat(event["date"])
    taper_days, recovery_days = get_taper_recovery(priority, event["format"])
    
    event.update({
        "priority": priority,
        "taper_start": (event_date - timedelta(days=taper_days)).isoformat(),
        "recovery_end": (event_date + timedelta(days=recovery_days)).isoformat()
    })
    
    db.execute("INSERT INTO race_calendar VALUES %s ON CONFLICT (event_id) DO UPDATE ...", event)
    export_race_calendar_md()   # regenerate human-readable .md on every update
    return event

def get_taper_recovery(priority: str, format: str) -> tuple[int, int]:
    """Return (taper_days, recovery_days) for priority + format combination."""
    matrix = {
        ("A", "Ironman"):     (14, 21),
        ("A", "70.3"):        (12, 14),
        ("A", "Olympic"):     (10, 7),
        ("A", "marathon"):    (14, 14),
        ("B", "Ironman"):     (7, 7),
        ("B", "70.3"):        (5, 5),
        ("B", "Olympic"):     (5, 3),
        ("B", "marathon"):    (7, 5),
        ("C", "Olympic"):     (2, 1),
        ("C", "half_marathon"): (2, 1),
    }
    return matrix.get((priority, format), (7, 5))   # sensible default
```

### Race Calendar Markdown Export

```python
def export_race_calendar_md(output_path: str = "./race_calendar.md") -> None:
    """
    Export current race calendar to Markdown.
    Regenerated on every event add/update/reclassify.
    """
    events = db.query("SELECT * FROM race_calendar ORDER BY date ASC")
    
    lines = [
        "# Race Calendar\n",
        f"_Last updated: {date.today().isoformat()}_\n\n",
        "| Date | Event | Format | Priority | Taper Starts | Recovery End |",
        "|---|---|---|---|---|---|"
    ]
    
    for e in events:
        priority_label = {"A": "🔴 A", "B": "🟡 B", "C": "🟢 C"}.get(e["priority"], e["priority"])
        lines.append(
            f"| {e['date']} | {e['name']} | {e['format']} | {priority_label} "
            f"| {e['taper_start']} | {e['recovery_end']} |"
        )
    
    # Detail blocks per event
    lines.append("\n---\n")
    for e in events:
        lines.append(f"## {e['name']} — {e['date']}")
        lines.append(f"- **Location:** {e.get('location', 'TBC')}")
        lines.append(f"- **Format:** {e['format']} ({e.get('distance_label', '')})")
        lines.append(f"- **Priority:** {e['priority']}")
        if e.get("swim_distance_m"):
            lines.append(f"- **Swim:** {e['swim_distance_m']}m")
        if e.get("bike_distance_km"):
            lines.append(f"- **Bike:** {e['bike_distance_km']}km")
        if e.get("run_distance_km"):
            lines.append(f"- **Run:** {e['run_distance_km']}km")
        if e.get("elevation_gain_m"):
            lines.append(f"- **Elevation:** {e['elevation_gain_m']}m gain")
        lines.append(f"- **Taper window:** {e['taper_start']} → {e['date']}")
        lines.append(f"- **Recovery window:** {e['date']} → {e['recovery_end']}")
        lines.append(f"- **Source:** [{e.get('source_url', '')}]({e.get('source_url', '')})")
        lines.append("")
    
    Path(output_path).write_text("\n".join(lines))
```

---

## Analysis Layer — JupyterLab

### CTL/ATL/TSB Calculation

```python
import pandas as pd
import numpy as np

def calculate_fitness_curves(daily_tss: pd.Series) -> pd.DataFrame:
    """
    Calculate CTL/ATL/TSB from daily TSS across all sports.
    Input: pd.Series with date index, values = combined daily TSS.
    """
    ctl = daily_tss.ewm(span=42).mean()     # Chronic Training Load (fitness)
    atl = daily_tss.ewm(span=7).mean()      # Acute Training Load (fatigue)
    tsb = ctl - atl                          # Training Stress Balance (form)
    
    return pd.DataFrame({"ctl": ctl, "atl": atl, "tsb": tsb, "tss": daily_tss})

def build_daily_tss(db_conn) -> pd.Series:
    """
    Sum TSS across all sports and cross-training per day.
    Pulls from all session tables.
    """
    query = """
        SELECT session_date, SUM(actual_tss) as total_tss
        FROM (
            SELECT session_date, actual_tss FROM garmin_activities   -- swim, bike, run
            UNION ALL
            SELECT session_date, actual_tss FROM strength_sessions   -- gym, climbing
            UNION ALL
            SELECT session_date, actual_tss FROM cross_training_sessions  -- yoga, mobility
        ) all_sessions
        GROUP BY session_date
        ORDER BY session_date
    """
    df = pd.read_sql(query, db_conn, index_col="session_date", parse_dates=["session_date"])
    return df["total_tss"]
```

### CSS Extraction from Swim Data

```python
def estimate_css(best_400m_pace: float, best_200m_pace: float) -> float:
    """
    CSS formula: (400 - 200) / (T400 - T200)
    Inputs are pace in seconds per 100m.
    """
    t400 = best_400m_pace * 4    # total time for 400m in seconds
    t200 = best_200m_pace * 2    # total time for 200m in seconds
    css = (400 - 200) / (t400 - t200)     # metres per second
    return 100 / css                       # return as sec/100m
```

### HRV Correlation Analysis

```python
from scipy import stats

def hrv_execution_correlation(hrv_series: pd.Series, execution_series: pd.Series):
    """
    Find correlation between 7-day HRV trend and next-day execution quality.
    execution_series: daily execution ratios (actual TSS / planned TSS).
    """
    hrv_7d = hrv_series.rolling(7).mean()
    
    # Shift execution forward 1 day — HRV today predicts tomorrow's execution
    execution_next = execution_series.shift(-1)
    
    aligned = pd.DataFrame({"hrv": hrv_7d, "execution": execution_next}).dropna()
    r, p = stats.pearsonr(aligned["hrv"], aligned["execution"])
    
    return {"pearson_r": r, "p_value": p, "n": len(aligned)}
```

---

## LLM Interface

### Ollama Setup

```bash
ollama pull llama3:70b-instruct-q4_K_M   # recommended quantisation
ollama pull mistral:7b-instruct           # faster, lower quality — Phase A testing
```

### Three Prompt Types

The system runs three distinct LLM calls on different schedules. Each has its own context shape and output schema.

---

### 1. Monthly Generation Prompt

Fires at the start of each month or on a block phase transition. Produces the full mesocycle as structured JSON. This is the most expensive call — 70B model, full context, potentially 3,000–5,000 tokens of output for a 4-week plan. Fine for an overnight batch job.

```python
def build_monthly_generation_context(athlete, fitness, block, race_calendar, history) -> dict:
    return {
        "prompt_type": "monthly_generation",
        "athlete": {
            "ftp": athlete.ftp,
            "css_sec_per_100m": athlete.css,
            "lthr_run": athlete.lthr_run,
            "weight_kg": athlete.weight_kg
        },
        "current_state": {
            "ctl": fitness.ctl,
            "atl": fitness.atl,
            "tsb": fitness.tsb,
            "hrv_7d_avg": fitness.hrv_7d,
            "hrv_trend": fitness.hrv_trend,
            "sleep_quality_7d": fitness.sleep_7d
        },
        "block": {
            "phase": block.phase,          # base | build | peak | taper | recovery
            "week_in_block": block.week,
            "total_block_weeks": block.total_weeks,
            "weeks_to_a_race": block.weeks_to_race,
            "race_format": block.race_format
        },
        "prior_month_summary": {
            "avg_execution_ratio": 0.91,
            "sessions_completed": 22,
            "sessions_missed": 2,
            "ctl_change": +4.2,
            "notes": "Missed Wednesday sessions both weeks — schedule conflict, not fatigue"
        },
        "race_calendar": race_calendar,    # all events with priority and taper windows
        "retrieved_history": history       # similar blocks from RAG — Phase D
    }

MONTHLY_SYSTEM_PROMPT = """
You are a triathlon and endurance coach. Generate a full month training plan.
Respond ONLY with valid JSON. No preamble, no markdown, no explanation outside the JSON.

Rules:
- Produce 4 weeks of sessions, 6 training days per week plus 1 rest day
- Week 3 should be peak load week; Week 4 should be recovery (60-70% of week 3 volume)
- For any threshold, VO2max, or race-pace session: include both a primary and a conditional_alt
- conditional_alt is what this session looks like if fatigue signals are elevated that morning
- The alt must be meaningfully different — not just 10% intensity reduction
- Include cross-training (strength, mobility) as scheduled sessions, not afterthoughts
- Load progression must be explicit in the rationale

Output format: see schema below.
"""

MONTHLY_OUTPUT_SCHEMA = {
    "month_rationale": "Why this load arc for this block phase and athlete state",
    "block_phase": "build",
    "weeks": [
        {
            "week_number": 1,
            "week_rationale": "Establish load baseline for this block",
            "target_tss": 420,
            "days": [
                {
                    "day": "Monday",
                    "date": "YYYY-MM-DD",
                    "primary": {
                        "sport": "swim",
                        "title": "CSS Threshold Set",
                        "duration_min": 60,
                        "planned_tss": 65,
                        "planned_if": 0.85,
                        "structure": {
                            "warmup": {"duration_min": 10, "target": "easy"},
                            "main_sets": [
                                {
                                    "repeat": 8,
                                    "distance_m": 100,
                                    "target": "CSS pace",
                                    "rest_sec": 15,
                                    "description": "Hold CSS — no faster"
                                }
                            ],
                            "cooldown": {"duration_min": 10}
                        },
                        "session_notes": "Focus on stroke rate consistency across all 8 reps",
                        "alt_trigger": "HRV suppressed OR sleep < 0.65 OR body battery < 50"
                    },
                    "conditional_alt": {
                        "title": "CSS Threshold Set — Reduced Volume",
                        "duration_min": 45,
                        "planned_tss": 42,
                        "planned_if": 0.78,
                        "structure": {
                            "warmup": {"duration_min": 10, "target": "easy"},
                            "main_sets": [
                                {
                                    "repeat": 5,
                                    "distance_m": 100,
                                    "target": "CSS pace or slightly slower",
                                    "rest_sec": 20
                                }
                            ],
                            "cooldown": {"duration_min": 10}
                        },
                        "session_notes": "Same quality, less quantity. If still feeling off after warmup, stop at 3 reps and call it.",
                        "alt_rationale": "Preserves swim stimulus with reduced volume demand. Still threshold work, not junk miles."
                    }
                }
            ]
        }
    ]
}
```

---

### 2. Weekly Review Prompt

Fires each Sunday overnight. Smaller context, faster — does not regenerate the month, only adjusts the coming week. Uses the monthly plan as the base and modifies it.

```python
def build_weekly_review_context(monthly_plan, week_number, prior_execution, fitness) -> dict:
    coming_week = monthly_plan["weeks"][week_number]
    return {
        "prompt_type": "weekly_review",
        "coming_week": coming_week,          # as generated in monthly plan
        "prior_week_execution": {
            "sessions": [
                {
                    "day": "Monday",
                    "sport": "swim",
                    "planned_tss": 65,
                    "actual_tss": 58,
                    "tss_ratio": 0.89,
                    "set_completion": 0.88,
                    "flags": ["SLIGHT_UNDERDELIVERY"]
                },
                # ... rest of week
            ],
            "week_tss_ratio": 0.91,
            "ctl_actual": fitness.ctl,
            "ctl_predicted": coming_week["predicted_ctl_end"]
        },
        "current_state": {
            "ctl": fitness.ctl,
            "atl": fitness.atl,
            "tsb": fitness.tsb,
            "hrv_trend": fitness.hrv_trend
        },
        "instruction": (
            "Review the coming week sessions against prior week execution. "
            "Adjust targets, reorder days, or modify volumes if fatigue drifted from model. "
            "Do NOT regenerate the full month. Return only the revised week with rationale for each change."
        )
    }

WEEKLY_REVIEW_SYSTEM_PROMPT = """
You are a triathlon coach reviewing a week of training before it begins.
Respond ONLY with valid JSON. Return the full revised week with a changes_rationale field.
If no changes are needed, return the week unchanged with changes_rationale: "No adjustments needed."
Preserve conditional_alt sessions from the monthly plan — do not remove them.
"""
```

---

### 3. Morning Decision Prompt

Fires daily at 3am. Smallest and fastest call. Takes today's planned session (primary + conditional_alt from the stored monthly/weekly plan) and overnight biometrics. Returns the final versions of both options plus a signal summary for the morning readout.

```python
def build_morning_decision_context(today_session, biometrics, yesterday_execution) -> dict:
    hrv_baseline = biometrics["hrv_7d_avg"]
    hrv_today = biometrics["hrv_this_morning"]
    hrv_pct_delta = ((hrv_today - hrv_baseline) / hrv_baseline) * 100
    
    return {
        "prompt_type": "morning_decision",
        "today_planned": today_session,       # primary + conditional_alt from stored plan
        "biometrics": {
            "hrv_this_morning": hrv_today,
            "hrv_7d_baseline": hrv_baseline,
            "hrv_pct_vs_baseline": round(hrv_pct_delta, 1),
            "hrv_available": hrv_today is not None,    # False if reading missing
            "sleep_score": biometrics.get("sleep_score"),
            "body_battery": biometrics.get("body_battery"),
            "resting_hr": biometrics.get("resting_hr")
        },
        "yesterday": {
            "sport": yesterday_execution.get("sport"),
            "tss_ratio": yesterday_execution.get("tss_ratio"),
            "flags": yesterday_execution.get("flags", [])
        }
    }

def assess_signal_conflict(biometrics: dict, athlete_id: str) -> dict:
    """
    Determine conflict level using the athlete's learned signal importance weights.
    Falls back to equal weighting if insufficient data to have learned weights yet.
    
    Returns a conflict assessment dict rather than a simple string —
    includes which signals drove the assessment and their individual contributions,
    so the morning readout can explain itself honestly.
    """
    weights = load_signal_weights(athlete_id)
    signals = extract_all_signals(biometrics)
    
    # Score each signal: how suppressed is it, weighted by how predictive it is for this athlete
    signal_scores = {}
    weighted_suppression = 0.0
    total_weight = 0.0
    
    for signal_name, signal_value in signals.items():
        if signal_value is None:
            continue
        
        weight = weights.get(signal_name, weights["_default"])
        suppression = score_signal_suppression(signal_name, signal_value, biometrics)
        weighted_contribution = suppression * weight
        
        signal_scores[signal_name] = {
            "value": signal_value,
            "suppression": round(suppression, 2),    # 0 = normal, 1 = maximally suppressed
            "weight": round(weight, 2),               # learned importance for this athlete
            "contribution": round(weighted_contribution, 2)
        }
        weighted_suppression += weighted_contribution
        total_weight += weight
    
    composite_score = weighted_suppression / total_weight if total_weight > 0 else 0
    
    # Determine conflict level from composite
    if composite_score < 0.20:
        level = "clear"
    elif composite_score < 0.45:
        level = "mild"
    elif composite_score < 0.70:
        level = "significant"
    else:
        level = "high"
    
    # Identify the top drivers — what's actually pulling the score down
    top_drivers = sorted(
        [(k, v) for k, v in signal_scores.items() if v["contribution"] > 0.05],
        key=lambda x: x[1]["contribution"],
        reverse=True
    )[:3]
    
    return {
        "level": level,                   # clear | mild | significant | high
        "composite_score": round(composite_score, 3),
        "signal_scores": signal_scores,
        "top_drivers": [name for name, _ in top_drivers],
        "driver_detail": {name: data for name, data in top_drivers},
        "hrv_available": biometrics.get("hrv_available", False),
        "weights_source": weights.get("_source", "default")  # default | learned | partial
    }


def extract_all_signals(biometrics: dict) -> dict:
    """
    Extract every available readiness signal into a normalised dict.
    New signals can be added here without touching the conflict assessment logic.
    """
    return {
        "hrv_pct_vs_baseline":    biometrics.get("hrv_pct_vs_baseline"),      # % delta from 7d mean
        "sleep_score":            biometrics.get("sleep_score"),               # 0–1 Garmin score
        "sleep_duration_hr":      biometrics.get("sleep_duration_hr"),         # hours
        "body_battery":           biometrics.get("body_battery"),              # 0–100
        "resting_hr_vs_baseline": biometrics.get("resting_hr_vs_baseline"),   # % delta from 7d mean
        "prior_day_tss_ratio":    biometrics.get("prior_day_tss_ratio"),       # actual/planned TSS yesterday
        "rolling_7d_tss_ratio":   biometrics.get("rolling_7d_tss_ratio"),     # execution trend this week
        "tsb":                    biometrics.get("tsb"),                       # training stress balance
        "cycle_phase_modifier":   biometrics.get("cycle_phase_modifier"),     # 0.85–1.05 from cycle engine
        "stress_score":           biometrics.get("stress_score"),             # Garmin all-day stress 0–100
        "respiration_rate_delta": biometrics.get("respiration_rate_delta"),   # vs baseline — illness proxy
        "skin_temp_delta":        biometrics.get("skin_temp_delta"),          # vs baseline — illness/fever proxy
    }


def score_signal_suppression(signal_name: str, value: float, biometrics: dict) -> float:
    """
    Convert a raw signal value to a suppression score 0–1.
    0 = completely normal. 1 = maximally suppressed / concerning.
    Each signal has its own scale and direction.
    """
    if signal_name == "hrv_pct_vs_baseline":
        # Negative = suppressed. -20% or worse = fully suppressed
        return max(0, min(1, (-value) / 20)) if value < 0 else 0

    elif signal_name == "sleep_score":
        # 0–1 score. Below 0.70 starts to matter. Below 0.50 is significant.
        return max(0, min(1, (0.75 - value) / 0.35))

    elif signal_name == "sleep_duration_hr":
        # Below 7hrs starts to matter. Below 5hrs is high suppression.
        return max(0, min(1, (7.0 - value) / 2.5))

    elif signal_name == "body_battery":
        # 0–100. Below 60 starts to matter. Below 30 is high suppression.
        return max(0, min(1, (65 - value) / 45))

    elif signal_name == "resting_hr_vs_baseline":
        # Positive = elevated vs baseline (bad). +10% or more is concerning.
        return max(0, min(1, value / 12)) if value > 0 else 0

    elif signal_name == "prior_day_tss_ratio":
        # Ratio > 1.15 = overcooked yesterday = carry-over fatigue
        return max(0, min(1, (value - 1.0) / 0.25)) if value > 1.0 else 0

    elif signal_name == "rolling_7d_tss_ratio":
        # Consistently over-delivering this week = accumulating fatigue
        return max(0, min(1, (value - 1.05) / 0.20)) if value > 1.05 else 0

    elif signal_name == "tsb":
        # Negative TSB = fatigued. -20 or worse is significant.
        return max(0, min(1, (-value) / 25)) if value < 0 else 0

    elif signal_name == "cycle_phase_modifier":
        # Modifier below 1.0 = suppression expected from cycle phase
        return max(0, 1.0 - value) if value < 1.0 else 0

    elif signal_name == "stress_score":
        # Garmin all-day stress. Above 50 starts to matter. Above 75 is significant.
        return max(0, min(1, (value - 45) / 40))

    elif signal_name == "respiration_rate_delta":
        # Elevated respiration vs baseline — illness proxy. +10% is concerning.
        return max(0, min(1, value / 15)) if value > 0 else 0

    elif signal_name == "skin_temp_delta":
        # Elevated skin temp vs baseline — fever/illness proxy.
        return max(0, min(1, value / 1.5)) if value > 0 else 0

    return 0

MORNING_SYSTEM_PROMPT = """
You are a triathlon coach reviewing this morning's readiness before a training session.
The athlete will see both the primary and alt session and choose. Do not choose for them.
Respond ONLY with valid JSON. Include a signal_summary: one sentence explaining the signals.

The signal assessment includes top_drivers — the signals most responsible for any conflict.
Lead with those in your signal_summary, not with HRV by default.
If HRV is not among the top drivers, do not mention it first.

If hrv_available is false and conflict level is clear by other signals, note HRV is missing
but proceed with the planned session. Do not default to alt just because HRV is absent.

Output format:
{
  "signal_summary": "Sleep 5.4hrs, body battery 38 — sleep debt is the concern today, not HRV.",
  "primary": { ...session... },
  "alt": { ...session... },
  "alt_label": "Reduced volume version",
  "leading_signal": "sleep_duration_hr"   // what actually drove the assessment
}
"""
```

### Morning Readout Delivery

The morning readout can be as simple as a text file, a Grafana annotation, or a push notification depending on what's built by Phase C.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tuesday 10 June — Morning Readout
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Signal: Sleep 5.4hrs, body battery 38.
Sleep debt is the concern today — HRV is actually fine.

🔵 PRIMARY   CSS Threshold Set — 60min — TSS 65
             8 × 100m @ CSS, 15s rest

🟡 ALT       CSS Threshold Set (Reduced) — 45min — TSS 42
             5 × 100m @ CSS or slightly slower, 20s rest
             Same quality, less volume.

Your call.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Logging Athlete Choice

```python
def log_athlete_choice(session_date: str, choice: str, reason: str = None) -> None:
    """
    Log whether athlete took primary or alt, and why if provided.
    This data is the training signal for future HRV weighting calibration.
    """
    db.execute("""
        INSERT INTO athlete_choices
        (session_date, choice, reason, biometrics_snapshot, execution_score_next_day)
        VALUES (%s, %s, %s, %s, NULL)
    """, (session_date, choice, reason, json.dumps(today_biometrics)))
    # execution_score_next_day populated the following morning after sync

### Signal Importance Learning Engine

This is the analytical layer that answers "what actually predicts a good or bad session for this athlete?" It runs in the background as data accumulates, periodically recalculates signal weights, and replaces the default equal-weighting with athlete-specific learned weights. After enough data exists, HRV might rank 4th. Sleep duration might rank 1st. The system should know that and act accordingly.

```python
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import ElasticNet
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score
from sklearn.inspection import permutation_importance
from scipy import stats
import json
from datetime import date, timedelta

# ── Default weights ── used before enough data to learn
DEFAULT_SIGNAL_WEIGHTS = {
    "hrv_pct_vs_baseline":    0.20,   # starts with conventional wisdom
    "sleep_score":            0.18,
    "sleep_duration_hr":      0.15,
    "body_battery":           0.14,
    "resting_hr_vs_baseline": 0.10,
    "tsb":                    0.10,
    "prior_day_tss_ratio":    0.07,
    "rolling_7d_tss_ratio":   0.04,
    "stress_score":           0.02,
    "cycle_phase_modifier":   0.00,   # zero until cycle data confirmed active
    "respiration_rate_delta": 0.00,
    "skin_temp_delta":        0.00,
    "_default":               0.05,   # fallback for any signal not listed
    "_source":               "default"
}

def load_signal_weights(athlete_id: str) -> dict:
    """Load current signal weights — learned if available, default if not."""
    record = db.fetchone(
        """SELECT weights, source, trained_on, n_samples
           FROM signal_weights WHERE athlete_id = %s
           ORDER BY trained_on DESC LIMIT 1""",
        (athlete_id,)
    )
    if not record or record["n_samples"] < 60:
        # Not enough data yet — use defaults
        return {**DEFAULT_SIGNAL_WEIGHTS, "_source": "default"}
    
    weights = json.loads(record["weights"])
    weights["_source"] = f"learned ({record['n_samples']} sessions)"
    return weights


def build_signal_training_dataset(athlete_id: str, lookback_days: int = 730) -> pd.DataFrame:
    """
    Build the dataset for signal importance analysis.
    
    Each row = one training session with:
    - All morning biometric signals as features
    - Execution quality (TSS ratio or overall execution score) as target
    
    This dataset is what the model learns from.
    """
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    
    query = """
        SELECT
            -- Target variable: how well did the session go?
            es.overall_execution              AS execution_score,
            es.tss_ratio                      AS tss_ratio,
            es.if_delta                       AS if_delta,
            es.set_completion                 AS set_completion,
            es.sport                          AS sport,
            
            -- Biometric signals from the morning BEFORE this session
            b.hrv_pct_vs_baseline,
            b.sleep_score,
            b.sleep_duration_hr,
            b.body_battery,
            b.resting_hr_vs_baseline,
            b.tsb,
            b.prior_day_tss_ratio,
            b.rolling_7d_tss_ratio,
            b.stress_score,
            b.cycle_phase_modifier,
            b.respiration_rate_delta,
            b.skin_temp_delta,
            
            -- Context that might moderate relationships
            b.hrv_available,
            es.session_date,
            es.block_phase
            
        FROM execution_scores es
        JOIN daily_biometrics b ON b.date = es.session_date AND b.athlete_id = es.athlete_id
        WHERE es.athlete_id = %s
          AND es.session_date >= %s
          AND es.overall_execution IS NOT NULL
          AND es.planned_tss > 20          -- ignore junk/easy sessions below this threshold
        ORDER BY es.session_date
    """
    
    df = pd.read_sql(query, db_conn, params=(athlete_id, cutoff))
    return df


def calculate_signal_importance(
    df: pd.DataFrame,
    target: str = "execution_score",
    min_samples: int = 60
) -> dict:
    """
    Calculate which signals actually predict session execution quality for this athlete.
    
    Uses multiple methods and ensembles the results — no single method is reliable
    on a small-ish dataset, but three methods pointing the same direction is a real signal.
    
    Returns a weight dict ready to store and use in assess_signal_conflict().
    """
    
    signal_cols = [
        "hrv_pct_vs_baseline", "sleep_score", "sleep_duration_hr",
        "body_battery", "resting_hr_vs_baseline", "tsb",
        "prior_day_tss_ratio", "rolling_7d_tss_ratio", "stress_score",
        "cycle_phase_modifier", "respiration_rate_delta", "skin_temp_delta"
    ]
    
    # Only use columns with enough non-null values to be meaningful
    available_signals = [
        col for col in signal_cols
        if col in df.columns and df[col].notna().sum() >= min_samples * 0.5
    ]
    
    df_clean = df[available_signals + [target]].dropna()
    
    if len(df_clean) < min_samples:
        return {"_source": "default", "_insufficient_data": True, **DEFAULT_SIGNAL_WEIGHTS}
    
    X = df_clean[available_signals]
    y = df_clean[target]
    
    importance_scores = {}
    
    # ── Method 1: Pearson correlation (linear relationship) ──────────────────
    pearson = {}
    for col in available_signals:
        r, p = stats.pearsonr(X[col], y)
        pearson[col] = abs(r) if p < 0.10 else 0   # only count if statistically meaningful
    
    # ── Method 2: Spearman correlation (monotonic, robust to outliers) ───────
    spearman = {}
    for col in available_signals:
        r, p = stats.spearmanr(X[col], y)
        spearman[col] = abs(r) if p < 0.10 else 0
    
    # ── Method 3: Random Forest permutation importance ───────────────────────
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    rf = RandomForestRegressor(n_estimators=200, max_depth=4, random_state=42)
    rf.fit(X_scaled, y)
    perm = permutation_importance(rf, X_scaled, y, n_repeats=20, random_state=42)
    rf_importance = {
        col: max(0, perm.importances_mean[i])
        for i, col in enumerate(available_signals)
    }
    
    # ── Method 4: ElasticNet (regularised linear — stable on small datasets) ─
    en = ElasticNet(alpha=0.01, l1_ratio=0.5, max_iter=2000)
    en.fit(X_scaled, y)
    en_importance = {
        col: abs(en.coef_[i])
        for i, col in enumerate(available_signals)
    }
    
    # ── Ensemble: normalise each method to sum=1, then average ───────────────
    methods = [pearson, spearman, rf_importance, en_importance]
    
    def normalise(d: dict) -> dict:
        total = sum(d.values())
        return {k: v / total for k, v in d.items()} if total > 0 else d
    
    normalised = [normalise(m) for m in methods]
    
    ensemble = {}
    for col in available_signals:
        ensemble[col] = np.mean([m.get(col, 0) for m in normalised])
    
    # Renormalise ensemble to sum = 1
    total = sum(ensemble.values())
    ensemble = {k: v / total for k, v in ensemble.items()} if total > 0 else ensemble
    
    # Fill in any signals not in the dataset with a small non-zero weight
    # so they are not completely ignored if data starts arriving
    all_signals = set(signal_cols)
    missing = all_signals - set(available_signals)
    for col in missing:
        ensemble[col] = 0.01
    
    # Re-normalise after adding missing signals
    total = sum(ensemble.values())
    final_weights = {k: round(v / total, 4) for k, v in ensemble.items()}
    
    # Metadata
    final_weights["_source"] = "learned"
    final_weights["_n_samples"] = len(df_clean)
    final_weights["_trained_date"] = date.today().isoformat()
    final_weights["_default"] = 0.03
    
    return final_weights


def run_signal_importance_update(athlete_id: str) -> dict:
    """
    Full pipeline: build dataset → train → store → return summary.
    Called monthly by the analysis cron, or manually via UI.
    """
    df = build_signal_training_dataset(athlete_id)
    
    if len(df) < 60:
        return {
            "status": "insufficient_data",
            "sessions_available": len(df),
            "sessions_needed": 60,
            "message": f"Need {60 - len(df)} more sessions before signal learning is possible."
        }
    
    # Calculate per-sport weights — HRV might predict swim well but not bike
    sport_weights = {}
    for sport in df["sport"].unique():
        sport_df = df[df["sport"] == sport]
        if len(sport_df) >= 30:
            sport_weights[sport] = calculate_signal_importance(sport_df)
    
    # Calculate overall weights across all sports
    overall_weights = calculate_signal_importance(df)
    
    # Store in database
    db.execute("""
        INSERT INTO signal_weights (athlete_id, scope, weights, n_samples, trained_on)
        VALUES (%s, %s, %s, %s, NOW())
    """, (athlete_id, "overall", json.dumps(overall_weights), len(df)))
    
    for sport, weights in sport_weights.items():
        db.execute("""
            INSERT INTO signal_weights (athlete_id, scope, weights, n_samples, trained_on)
            VALUES (%s, %s, %s, %s, NOW())
        """, (athlete_id, sport, json.dumps(weights), len(df[df["sport"] == sport])))
    
    # Generate human-readable summary for the UI
    summary = generate_signal_importance_summary(overall_weights, sport_weights, df)
    
    return {
        "status": "updated",
        "sessions_analysed": len(df),
        "top_predictors": summary["top_predictors"],
        "surprising_findings": summary["surprising_findings"],
        "weights": overall_weights
    }


def generate_signal_importance_summary(
    overall: dict,
    by_sport: dict,
    df: pd.DataFrame
) -> dict:
    """
    Produce human-readable insights from the signal importance analysis.
    Surfaced in the UI signal importance dashboard.
    Identifies where HRV is not the top predictor and says so plainly.
    """
    
    SIGNAL_LABELS = {
        "hrv_pct_vs_baseline":    "HRV vs 7-day baseline",
        "sleep_score":            "Sleep quality score",
        "sleep_duration_hr":      "Sleep duration",
        "body_battery":           "Body battery",
        "resting_hr_vs_baseline": "Resting HR vs baseline",
        "tsb":                    "Training Stress Balance (TSB)",
        "prior_day_tss_ratio":    "Prior day load execution",
        "rolling_7d_tss_ratio":   "7-day execution trend",
        "stress_score":           "All-day stress score",
        "cycle_phase_modifier":   "Menstrual cycle phase",
        "respiration_rate_delta": "Respiration rate vs baseline",
        "skin_temp_delta":        "Skin temperature vs baseline",
    }
    
    # Rank signals by learned weight
    ranked = sorted(
        [(k, v) for k, v in overall.items() if not k.startswith("_")],
        key=lambda x: x[1],
        reverse=True
    )
    
    top_3 = [(SIGNAL_LABELS.get(k, k), round(v * 100, 1)) for k, v in ranked[:3]]
    hrv_rank = next((i + 1 for i, (k, _) in enumerate(ranked) if k == "hrv_pct_vs_baseline"), None)
    
    surprising = []
    
    if hrv_rank and hrv_rank > 2:
        top_signal = SIGNAL_LABELS.get(ranked[0][0], ranked[0][0])
        surprising.append(
            f"HRV ranks #{hrv_rank} for you — {top_signal} is a stronger predictor of how "
            f"your sessions go. The system has adjusted the morning signal weighting accordingly."
        )
    
    # Check if TSB (cumulative fatigue) is dominant — suggests overtraining risk pattern
    tsb_rank = next((i + 1 for i, (k, _) in enumerate(ranked) if k == "tsb"), None)
    if tsb_rank and tsb_rank <= 2:
        surprising.append(
            "Cumulative fatigue (TSB) is among your top predictors. "
            "Single-day readiness signals matter less for you than training load trend. "
            "The system will weight load management more heavily in session adjustments."
        )
    
    # Check for sport-specific HRV divergence
    for sport, weights in by_sport.items():
        sport_ranked = sorted(
            [(k, v) for k, v in weights.items() if not k.startswith("_")],
            key=lambda x: x[1], reverse=True
        )
        sport_hrv_rank = next(
            (i + 1 for i, (k, _) in enumerate(sport_ranked) if k == "hrv_pct_vs_baseline"), None
        )
        if sport_hrv_rank and hrv_rank and abs(sport_hrv_rank - hrv_rank) >= 2:
            surprising.append(
                f"HRV predicts your {sport} sessions differently (rank #{sport_hrv_rank}) "
                f"than your overall pattern (rank #{hrv_rank}). "
                f"Sport-specific weights will be used for {sport} sessions."
            )
    
    return {
        "top_predictors": [
            {"signal": label, "weight_pct": weight} for label, weight in top_3
        ],
        "hrv_rank": hrv_rank,
        "surprising_findings": surprising,
        "interpretation": (
            "These weights reflect your personal data, not population averages. "
            "They update monthly as more sessions accumulate."
        )
    }


def get_sport_specific_weights(athlete_id: str, sport: str) -> dict:
    """
    Load sport-specific weights if available, fall back to overall, then default.
    Used when sport of today's session is known at morning decision time.
    """
    record = db.fetchone(
        """SELECT weights, n_samples FROM signal_weights
           WHERE athlete_id = %s AND scope = %s
           ORDER BY trained_on DESC LIMIT 1""",
        (athlete_id, sport)
    )
    if record and record["n_samples"] >= 30:
        weights = json.loads(record["weights"])
        weights["_source"] = f"learned:{sport}"
        return weights
    
    # Fall back to overall
    return load_signal_weights(athlete_id)
```

### Signal Importance Dashboard Data

The UI exposes this as a readable panel — not just for debugging, but because the athlete should understand what the system thinks about their physiology.

```python
@app.get("/api/signal-importance")
async def get_signal_importance(athlete_id: str = "1"):
    """Return current signal importance for display in the UI."""
    weights = load_signal_weights(athlete_id)
    
    # Get sport-specific breakdowns
    sport_weights = {}
    for sport in ["swim", "bike", "run", "strength"]:
        sw = db.fetchone(
            "SELECT weights, n_samples FROM signal_weights WHERE athlete_id = %s AND scope = %s ORDER BY trained_on DESC LIMIT 1",
            (athlete_id, sport)
        )
        if sw:
            sport_weights[sport] = json.loads(sw["weights"])
    
    # Get the human-readable summary generated at last training run
    summary = db.fetchone(
        "SELECT summary_json FROM signal_importance_summaries WHERE athlete_id = %s ORDER BY created_at DESC LIMIT 1",
        (athlete_id,)
    )
    
    return {
        "weights": weights,
        "by_sport": sport_weights,
        "summary": json.loads(summary["summary_json"]) if summary else None,
        "data_source": weights.get("_source", "default"),
        "last_trained": weights.get("_trained_date"),
        "sessions_used": weights.get("_n_samples", 0)
    }

@app.post("/api/signal-importance/retrain")
async def trigger_signal_retrain(athlete_id: str = "1"):
    """Manually trigger a signal importance recalculation."""
    result = run_signal_importance_update(athlete_id)
    return result
```

### How It Feeds Back Into Morning Readout

```python
def build_morning_decision_context(today_session, biometrics, yesterday_execution, athlete_id) -> dict:
    # Get sport-specific weights — bike HRV pattern may differ from run
    sport = today_session.get("sport", "all")
    weights = get_sport_specific_weights(athlete_id, sport)
    
    # Score signals with learned weights
    conflict = assess_signal_conflict(biometrics, athlete_id)
    
    # Enrich biometrics with cycle context if active
    cycle_ctx = get_cycle_context(today(), athlete_id)
    med_ctx = build_medication_context(today())
    
    return {
        "prompt_type": "morning_decision",
        "today_planned": today_session,
        "conflict_assessment": conflict,              # level, top_drivers, composite_score
        "biometrics": biometrics,
        "signal_weights_source": weights.get("_source"),  # tells LLM if weights are learned
        "cycle_context": cycle_ctx,
        "medication_context": med_ctx,
        "yesterday": {
            "sport": yesterday_execution.get("sport"),
            "tss_ratio": yesterday_execution.get("tss_ratio"),
            "flags": yesterday_execution.get("flags", [])
        }
    }
```

### Logging Athlete Choice — Extended for Signal Learning

```python
def log_athlete_choice(
    session_date: str,
    choice: str,
    conflict_assessment: dict,
    notes: str = None
) -> None:
    """
    Log athlete choice with the full conflict assessment snapshot.
    The conflict assessment captures which signals drove the recommendation —
    so when execution data arrives tomorrow, we can attribute outcome to the right signals.
    """
    db.execute("""
        INSERT INTO athlete_choices
        (session_date, choice, notes, conflict_assessment, biometrics_snapshot,
         leading_signal, composite_score, execution_score)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NULL)
    """, (
        session_date, choice, notes,
        json.dumps(conflict_assessment),
        json.dumps(conflict_assessment.get("signal_scores", {})),
        conflict_assessment["top_drivers"][0] if conflict_assessment["top_drivers"] else None,
        conflict_assessment["composite_score"]
    ))
    # execution_score populated the next morning after Garmin sync


def backfill_execution_scores() -> None:
    """
    Run each morning: find yesterday's logged choices and attach execution scores
    now that Garmin data has synced.
    """
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    
    choice = db.fetchone(
        "SELECT * FROM athlete_choices WHERE session_date = %s AND execution_score IS NULL",
        (yesterday,)
    )
    if not choice:
        return
    
    execution = db.fetchone(
        "SELECT overall_execution FROM execution_scores WHERE session_date = %s",
        (yesterday,)
    )
    if execution:
        db.execute(
            "UPDATE athlete_choices SET execution_score = %s WHERE session_date = %s",
            (execution["overall_execution"], yesterday)
        )
```
```



---

## Output Generation

### Zwift .zwo File Generation

```python
ZWO_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<workout_file>
    <author>AI Coaching System</author>
    <name>{name}</name>
    <description>{description}</description>
    <sportType>bike</sportType>
    <workout>
{segments}
    </workout>
</workout_file>"""

def session_to_zwo(session: dict, ftp: float) -> str:
    segments = []
    
    for step in session["structure"].get("main_sets", []):
        stype = step.get("type") or step.get("description", "").lower()
        
        if "warmup" in stype or step.get("target_zone", "").lower() == "z1":
            segments.append(
                f'        <Warmup Duration="{step["duration_sec"]}" '
                f'PowerLow="0.40" PowerHigh="0.60"/>'
            )
        elif step.get("repeat"):
            on_power = (step.get("target_watts") or ftp * 0.95) / ftp
            off_power = 0.50
            segments.append(
                f'        <IntervalsT Repeat="{step["repeat"]}" '
                f'OnDuration="{step["on_sec"]}" OffDuration="{step["off_sec"]}" '
                f'OnPower="{on_power:.2f}" OffPower="{off_power:.2f}"/>'
            )
        elif "cooldown" in stype:
            segments.append(
                f'        <Cooldown Duration="{step["duration_sec"]}" '
                f'PowerLow="0.60" PowerHigh="0.40"/>'
            )
        else:
            power = (step.get("target_watts") or ftp * 0.75) / ftp
            segments.append(
                f'        <SteadyState Duration="{step["duration_sec"]}" Power="{power:.2f}"/>'
            )
    
    return ZWO_TEMPLATE.format(
        name=session["title"],
        description=session.get("session_notes", ""),
        segments="\n".join(segments)
    )

def write_zwo_to_zwift(zwo_content: str, filename: str, zwift_user_id: str) -> None:
    """Write .zwo file to Zwift workouts folder via SMB share."""
    smb_path = f"\\\\zwift-machine\\Zwift\\Workouts\\{zwift_user_id}\\{filename}.zwo"
    with open(smb_path, "w", encoding="utf-8") as f:
        f.write(zwo_content)
```

### Garmin Workout Push

```python
def push_to_garmin(session: dict, sport: str, client: Garmin) -> bool:
    """
    Push a generated session to Garmin Connect calendar via python-garminconnect.
    Returns True on success, False on failure.
    On failure: session is still delivered via morning readout UI — watch sync is a bonus,
    not a dependency. Athlete can manually add to watch if needed.
    """
    payload = {
        "workoutName": session["title"],
        "sportType": {"sportTypeId": GARMIN_SPORT_IDS[sport]},
        "workoutSegments": build_garmin_segments(session["structure"], sport)
    }
    
    try:
        client.upload_workout(payload)
        log_push_success(session["session_id"], "garmin")
        return True
    except Exception as e:
        log_push_failure(session["session_id"], "garmin", str(e))
        notify(
            "⚠️ Garmin session push failed",
            f"'{session['title']}' could not be pushed to your watch. "
            f"Check the morning readout for session details.",
            priority="low"
        )
        return False

GARMIN_SPORT_IDS = {
    "run": 1, "bike": 2, "swim": 5,
    "strength": 14, "yoga": 15, "climb": 26
}

# Graceful degradation: if Garmin API is unavailable, the morning readout
# is the primary delivery channel. The watch push is a convenience layer.
# Sessions are always stored in PostgreSQL and visible in the UI regardless.
```

---

## Orchestration & Scheduling

### Daily Pipeline

```bash
# /etc/systemd/system/coaching-pipeline.timer
[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
```

```python
def run_daily_pipeline():
    """Main orchestration — runs at 3am."""
    
    # 1. Sync completed activities
    garmindb_sync()
    
    # 2. Fetch today's planned workouts from all platforms
    planned = fetch_all_planned_workouts(date.today())
    
    # 3. Score yesterday's execution
    yesterday_planned = get_planned_session(date.today() - timedelta(days=1))
    yesterday_actual = get_completed_session(date.today() - timedelta(days=1))
    execution_score = score_execution(yesterday_planned, yesterday_actual)
    
    # 4. Update fitness curves
    daily_tss = build_daily_tss(db)
    fitness = calculate_fitness_curves(daily_tss)
    
    # 5. Assemble LLM context
    context = build_context(fitness, execution_score)
    
    # 6. Generate week plan via LLM
    plan = llm_generate_plan(context)
    
    # 7. Push to devices
    for session in plan["sessions"]:
        if session["sport"] == "bike":
            zwo = session_to_zwo(session, athlete_ftp())
            write_zwo_to_zwift(zwo, session["title"], ZWIFT_USER_ID)
        else:
            push_to_garmin(session, session["sport"])
    
    # 8. Log everything — inputs, outputs, context (builds fine-tuning dataset)
    log_pipeline_run(context, plan, execution_score)
```

### Fine-Tuning Dataset Collection

```python
log_entry = {
    "timestamp": datetime.utcnow().isoformat(),
    "input_context": context,
    "llm_output": plan,
    "execution_data": {},           # populated 24hrs later when actual arrives
    "execution_ratio": None         # calculated once actual data lands
}
```

---

## RAG Layer — Phase D

### Vector Database Setup

```bash
pip install chromadb   # or qdrant-client for Qdrant
docker run -p 6333:6333 qdrant/qdrant
```

### What to Embed

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')

block_summary = f"""
Phase: {block['phase']}, Week: {block['week']}, Format: {block['format']}
CTL: {state['ctl']}, ATL: {state['atl']}, TSB: {state['tsb']}
HRV trend: {state['hrv_trend']}, Sleep: {state['sleep_quality']}
Cross-training load prior week: {cross_tss} TSS from {cross_sessions} sessions
Outcome: CTL change +{outcome['ctl_change']}, Execution ratio {outcome['execution_ratio']}
"""

embedding = model.encode(block_summary)
```

### Retrieval Query

```python
query = f"""
Build block week 6, Olympic tri target, CTL 68 ATL 72, HRV suppressed,
temperature averaging 28C, 8 weeks to race,
strength session 2 days ago, yoga yesterday
"""

results = collection.query(
    query_embeddings=[model.encode(query)],
    n_results=3
)
```

---

*AI Coaching System — Code Ideas & Scratchpad · March 2026 · *

---

## Health Platform Integrations

### Apple HealthKit — iOS Shortcut Companion

The Shortcut reads from HealthKit and POSTs to the server. No app needed — runs on schedule or manually.

```javascript
// iOS Shortcut — "Get Health Data" — runs daily at 5am via Automation
// Uses Shortcut actions:
// 1. "Get Health Sample" — Menstrual Flow (last 7 days)
// 2. "Get Health Sample" — Resting Heart Rate (today)
// 3. POST to server via "Get Contents of URL"

// Equivalent logic (Shortcut scripting pseudo-code):
const today = new Date().toISOString().split('T')[0];

const payload = {
  date: today,
  source: "apple_health",
  menstrual_flow: ShortcutInput.menstrualFlow,      // none | light | medium | heavy | unspecified
  cycle_phase: ShortcutInput.cyclePhase,            // if predicted by Health app
  ovulation_test_result: ShortcutInput.ovulation,   // positive | negative | indeterminate
  resting_hr: ShortcutInput.restingHR,
  medications_today: ShortcutInput.medications      // from Health medication log
};

// POST to server via Tailscale
fetch("http://steiger.tail-network.ts.net:8000/api/health-data", {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-API-Key": "LOCAL_KEY" },
  body: JSON.stringify(payload)
});
```

### Google Health Connect — Android

```python
# Android companion — Tasker HTTP Request task, or minimal Python script
# Health Connect requires Android 9+ and the Health Connect app installed

# Tasker HTTP Post action:
# URL: http://steiger.tail-network.ts.net:8000/api/health-data
# Content-Type: application/json
# Body: built from Tasker variables populated by Health Connect plugin

# Alternatively — a minimal Python script on a rooted device or via ADB:
import requests
from health_connect import HealthConnectClient  # hypothetical wrapper

client = HealthConnectClient()
cycle_data = client.read_records("MenstrualCycle", time_range_start=yesterday, time_range_end=today)
meds = client.read_records("MedicationIntake", time_range_start=today, time_range_end=today)

payload = {
    "source": "google_health",
    "date": today,
    "menstrual_phase": cycle_data.phase if cycle_data else None,
    "medications_today": [m.medication_name for m in meds]
}
requests.post("http://steiger.tail-net/api/health-data", json=payload, headers={"X-API-Key": KEY})
```

### Server-Side Health Data Ingestion

```python
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter()

class HealthDataPayload(BaseModel):
    date: str
    source: str                          # apple_health | google_health
    menstrual_flow: str | None = None    # none | light | medium | heavy
    cycle_phase: str | None = None       # menstrual | follicular | ovulation | luteal
    ovulation_test_result: str | None = None
    resting_hr: float | None = None
    medications_today: list[str] = []

@router.post("/api/health-data")
async def ingest_health_data(payload: HealthDataPayload, x_api_key: str = Header(None)):
    if x_api_key != settings.LOCAL_API_KEY:
        raise HTTPException(status_code=401)
    
    # Derive cycle phase if not directly provided
    cycle_phase = payload.cycle_phase or derive_cycle_phase(payload.date, payload.menstrual_flow)
    
    # Map medication names to known classes
    med_flags = classify_medications(payload.medications_today)
    
    db.execute("""
        INSERT INTO health_context (date, source, cycle_phase, menstrual_flow, 
                                    ovulation_result, resting_hr, medications_raw,
                                    beta_blocker_active, ssri_active, hr_zones_disabled)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (date) DO UPDATE SET ...
    """, (payload.date, payload.source, cycle_phase, payload.menstrual_flow,
          payload.ovulation_test_result, payload.resting_hr,
          payload.medications_today, med_flags.beta_blocker,
          med_flags.ssri, med_flags.disable_hr_zones))

def classify_medications(med_names: list[str]) -> MedFlags:
    """Map medication names to effect flags for LLM context injection."""
    BETA_BLOCKERS = ["metoprolol", "atenolol", "bisoprolol", "carvedilol", "propranolol"]
    SSRIS = ["sertraline", "fluoxetine", "escitalopram", "venlafaxine", "duloxetine"]
    
    names_lower = [n.lower() for n in med_names]
    return MedFlags(
        beta_blocker=any(b in names_lower for b in BETA_BLOCKERS),
        ssri=any(s in names_lower for s in SSRIS),
        disable_hr_zones=any(b in names_lower for b in BETA_BLOCKERS)
    )
```

---

## Menstrual Cycle Phase Engine

```python
def get_cycle_context(date: str, athlete_id: str) -> dict:
    """
    Build cycle context for LLM prompt injection.
    Reads from health_context table; infers phase from flow data if not directly provided.
    """
    record = db.fetchone(
        "SELECT cycle_phase, menstrual_flow, ovulation_result FROM health_context WHERE date = %s",
        (date,)
    )
    
    if not record or record["cycle_phase"] is None:
        # Estimate from recent flow data
        phase = estimate_phase_from_flow_history(athlete_id, date)
    else:
        phase = record["cycle_phase"]
    
    phase_context = CYCLE_PHASE_CONTEXT.get(phase, {})
    
    return {
        "cycle_phase": phase,
        "hrv_suppression_expected": phase in ("menstrual", "late_luteal"),
        "performance_window": phase == "ovulation",
        "load_modifier": phase_context.get("load_modifier", 1.0),
        "prompt_annotation": phase_context.get("annotation", "")
    }

CYCLE_PHASE_CONTEXT = {
    "menstrual": {
        "load_modifier": 0.85,
        "annotation": "Menstrual phase — perceived effort elevated, fatigue recovery slower. "
                      "Soften intensity targets. HRV suppression expected and normal."
    },
    "follicular": {
        "load_modifier": 1.0,
        "annotation": "Follicular phase — estrogen rising. Good window for progressive loading."
    },
    "ovulation": {
        "load_modifier": 1.05,
        "annotation": "Ovulation window — peak performance. Good session for threshold test or key effort."
    },
    "early_luteal": {
        "load_modifier": 1.0,
        "annotation": "Early luteal — maintain load. Core temp slightly elevated; extra hydration cues warranted."
    },
    "late_luteal": {
        "load_modifier": 0.90,
        "annotation": "Late luteal — progesterone declining. HRV may suppress without underlying fatigue. "
                      "Do not misread as overtraining. Perceived effort often elevated."
    }
}
```

---

## Medication Context Injection

```python
def build_medication_context(date: str) -> dict:
    """Build medication flags for LLM context. Called during context assembly."""
    record = db.fetchone(
        "SELECT beta_blocker_active, ssri_active, hr_zones_disabled, medications_raw "
        "FROM health_context WHERE date = %s", (date,)
    )
    
    if not record:
        return {"medications_active": False}
    
    ctx = {
        "medications_active": True,
        "beta_blocker": record["beta_blocker_active"],
        "ssri": record["ssri_active"],
        "hr_zones_disabled": record["hr_zones_disabled"],
        "annotations": []
    }
    
    if record["beta_blocker_active"]:
        ctx["annotations"].append(
            "Beta blocker active. Heart rate response is blunted — HR zones are unreliable. "
            "All intensity targets must use power (bike) or RPE (run/swim). "
            "Do not generate HR ceiling targets for any session today."
        )
    
    if record["ssri_active"]:
        ctx["annotations"].append(
            "SSRI active. HRV baseline may be chronically suppressed. "
            "Do not flag HRV as acute overtraining signal without corroborating sleep or TSB data."
        )
    
    return ctx
```

---

## Vacation & Travel Mode

### Vacation Declaration API

```python
class VacationWindow(BaseModel):
    type: str                              # active | rest | retreat
    start_date: str
    end_date: str
    location: str
    altitude_m: int = 0
    climate: str = "temperate"            # hot_dry | hot_humid | cold | temperate | altitude
    available_equipment: list[str] = []
    pool_access: bool = False
    gym_access: str = "none"              # none | cardio_only | full
    training_intent: str = "maintain"    # maintain | reduce | opportunistic
    notes: str = ""

@router.post("/api/vacation")
async def declare_vacation(window: VacationWindow):
    # Store window
    db.execute("INSERT INTO vacation_windows VALUES ...", window.dict())
    
    # Trigger re-plan for affected month(s)
    affected_months = get_affected_months(window.start_date, window.end_date)
    for month in affected_months:
        queue_monthly_replan(month, reason="vacation_window_added")
    
    return {"status": "ok", "replan_queued": affected_months}

# Equipment → allowed session types mapping
EQUIPMENT_SESSION_MAP = {
    "road_bike": ["bike_outdoor", "bike_brick"],
    "indoor_trainer": ["bike_indoor"],
    "pool_access": ["swim"],
    "open_water": ["swim_open_water"],
    "gym_full": ["strength_gym"],
    "gym_cardio_only": ["strength_bodyweight"],  # downgrade to bodyweight
    "resistance_bands": ["strength_bodyweight"],
    "running_shoes": ["run"],                    # always available — implicit
}

def get_allowed_sessions(equipment: list[str], pool_access: bool, gym_access: str) -> list[str]:
    allowed = {"run", "mobility", "yoga"}       # always possible
    for item in equipment:
        allowed.update(EQUIPMENT_SESSION_MAP.get(item, []))
    if pool_access:
        allowed.add("swim")
    if gym_access == "full":
        allowed.add("strength_gym")
    return list(allowed)
```

### Environmental Modifiers

```python
CLIMATE_MODIFIERS = {
    "hot_dry": {
        "run_pace_modifier": 0.94,          # slow pace targets 6%
        "bike_power_modifier": 1.0,         # power unchanged — heat is felt but watts are watts
        "preferred_session_time": "early_morning",
        "hydration_note": "Add hydration cue to all session notes. Pre-cool if available.",
        "hrv_note": "Heat may suppress HRV. Annotate as environmental, not fatigue."
    },
    "hot_humid": {
        "run_pace_modifier": 0.90,
        "bike_power_modifier": 1.0,
        "preferred_session_time": "early_morning",
        "hydration_note": "Aggressive hydration cues. Sweat rate elevated. Consider electrolytes.",
        "hrv_note": "Humidity significantly suppresses HRV baseline. Do not alarm on low readings."
    },
    "altitude": {
        "run_pace_modifier": 0.88,          # significant — altitude pace is slower
        "bike_power_modifier": 1.0,         # power unchanged; HR elevated
        "intensity_days_1_3": 0.85,         # acclimatisation reduction
        "hr_note": "HR will run 5–15bpm higher than normal at equivalent effort. Do not target HR zones.",
        "hrv_note": "HRV suppression expected during acclimatisation. Normal from day 4–5 onward."
    },
    "cold": {
        "run_pace_modifier": 0.98,
        "bike_power_modifier": 1.0,
        "preferred_session_time": "midday",
        "notes": "Extended warmup recommended. Layer appropriately."
    },
    "temperate": {}                          # no modifications
}
```

---

## Training Retreat Mode

```python
class TrainingRetreat(BaseModel):
    type: str                              # cycling_camp | swim_camp | altitude_camp | tri_resort | run_retreat
    start_date: str
    end_date: str
    location: str
    altitude_m: int = 0
    available_sports: list[str]
    pool_access: bool = False
    coaching_on_site: bool = False
    daily_structure: str = "1x"           # 1x | 2x | 3x
    target_daily_tss: int = 150
    block_role: str = "volume_injection"  # volume_injection | intensity_block | recovery_camp
    notes: str = ""

def build_retreat_plan_context(retreat: TrainingRetreat) -> dict:
    """Inject retreat context into monthly generation prompt."""
    days = (date.fromisoformat(retreat.end_date) - date.fromisoformat(retreat.start_date)).days
    total_tss = retreat.target_daily_tss * days
    
    altitude_protocol = None
    if retreat.altitude_m >= 1500:
        altitude_protocol = {
            "days_1_to_3": "Acclimatisation — reduce intensity 15%, maintain volume. HR will be elevated.",
            "days_4_plus": "Full training with altitude-adjusted targets. Power unchanged; pace relaxed."
        }
    
    return {
        "retreat_active": True,
        "type": retreat.type,
        "duration_days": days,
        "location": retreat.location,
        "altitude_m": retreat.altitude_m,
        "altitude_protocol": altitude_protocol,
        "available_sports": retreat.available_sports,
        "coaching_on_site": retreat.coaching_on_site,
        "daily_sessions": retreat.daily_structure,
        "target_daily_tss": retreat.target_daily_tss,
        "total_block_tss": total_tss,
        "block_role": retreat.block_role,
        "notes": retreat.notes,
        "pre_retreat_taper_days": 3,       # arrive fresh
        "post_retreat_recovery_days": 5    # absorb the ATL spike
    }

# If coaching is on-site, suppress Garmin pushes for coached sessions
def should_push_to_garmin(session_date: str) -> bool:
    retreat = get_active_retreat(session_date)
    if retreat and retreat.coaching_on_site:
        return False    # coach directs — don't conflict with Garmin push
    return True
```

---

## Web UI — FastAPI Backend Patterns

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AI Coaching System")

# Serve React build as static files
app.mount("/app", StaticFiles(directory="frontend/dist", html=True), name="frontend")

# CORS for local dev only
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"])

# Key API endpoints

@app.get("/api/season")
async def get_season_overview():
    """Return full year race calendar + block structure for Season Builder canvas."""
    events = db.query("SELECT * FROM race_calendar ORDER BY date")
    blocks = db.query("SELECT * FROM training_blocks ORDER BY start_date")
    return {"events": events, "blocks": blocks, "tss_arc": calculate_tss_arc(blocks)}

@app.post("/api/season/events")
async def add_event(url: str = None, event: RaceEvent = None):
    """Add race via URL extraction or manual entry."""
    if url:
        extracted = extract_event_from_url(url, llm_client)
        return {"extracted": extracted, "needs_classification": True}
    if event:
        stored = classify_and_store_event(event.dict(), event.priority)
        return stored

@app.get("/api/morning-readout")
async def get_morning_readout(date: str = None):
    """Return today's primary + alt session with signal summary."""
    target_date = date or today()
    return db.fetchone(
        "SELECT * FROM morning_readouts WHERE session_date = %s", (target_date,)
    )

@app.post("/api/morning-readout/choice")
async def log_choice(date: str, choice: str, notes: str = ""):
    """Log athlete's primary/alt choice."""
    log_athlete_choice(date, choice, notes)
    return {"logged": True}

@app.get("/api/athlete-profile")
async def get_profile():
    return db.fetchone("SELECT * FROM athlete_profiles WHERE athlete_id = 1")

@app.put("/api/athlete-profile")
async def update_profile(profile: AthleteProfile):
    """Update profile — triggers context rebuild on next pipeline run."""
    db.execute("UPDATE athlete_profiles SET ... WHERE athlete_id = 1", profile.dict())
    return {"updated": True}

@app.get("/api/data-sources")
async def get_data_sources():
    """Return connection status for all configured data sources."""
    return {
        "garmin": check_garmindb_status(),
        "trainingpeaks": check_tp_connection(),
        "trainerroad": check_tr_export_status(),
        "apple_health": check_last_health_data_post(),
        "google_health": check_last_health_data_post(source="google_health"),
        "zwift": check_zwift_folder_access()
    }

@app.post("/api/pipeline/replan")
async def trigger_replan(scope: str = "month"):
    """Manually trigger a replan — month, week, or morning decision only."""
    if scope == "month":
        queue_monthly_replan(current_month(), reason="manual_trigger")
    elif scope == "week":
        queue_weekly_review(reason="manual_trigger")
    elif scope == "morning":
        run_morning_decision(today())
    return {"queued": scope}
```

### React Frontend — Key Component Sketches

```jsx
// SeasonBuilder.jsx — canvas-based year view
// Uses react-big-calendar or a custom SVG timeline

function SeasonBuilder() {
    const [events, setEvents] = useState([]);
    const [blocks, setBlocks] = useState([]);
    const [tssArc, setTssArc] = useState([]);

    const handleUrlDrop = async (url) => {
        const extracted = await api.post('/api/season/events', { url });
        setShowClassifyDialog(true);
        setPendingEvent(extracted);
    };

    return (
        <div className="season-builder">
            <TimelineCanvas events={events} blocks={blocks} tssArc={tssArc} />
            <UrlDropZone onDrop={handleUrlDrop} />
            <EventClassifyDialog event={pendingEvent} onConfirm={saveEvent} />
        </div>
    );
}

// MorningReadout.jsx — primary + alt cards
function MorningReadout() {
    const [readout, setReadout] = useState(null);
    const [choice, setChoice] = useState(null);

    const logChoice = async (selected) => {
        setChoice(selected);
        await api.post('/api/morning-readout/choice', { date: today, choice: selected });
    };

    return (
        <div className="morning-readout">
            <SignalSummary text={readout?.signal_summary} />
            <div className="session-cards">
                <SessionCard
                    session={readout?.primary}
                    label="Primary"
                    selected={choice === 'primary'}
                    onSelect={() => logChoice('primary')}
                />
                {readout?.alt && (
                    <SessionCard
                        session={readout?.alt}
                        label={readout?.alt_label}
                        selected={choice === 'alt'}
                        onSelect={() => logChoice('alt')}
                    />
                )}
            </div>
        </div>
    );
}

// DataSourceManager.jsx — connection status + actions
function DataSourceManager() {
    const [sources, setSources] = useState({});

    return (
        <div className="data-sources">
            {Object.entries(sources).map(([name, status]) => (
                <DataSourceRow
                    key={name}
                    name={name}
                    status={status.connected ? 'connected' : 'disconnected'}
                    lastSync={status.last_sync}
                    onConnect={() => initiateOAuth(name)}
                    onSync={() => triggerSync(name)}
                />
            ))}
        </div>
    );
}
```

---

*AI Coaching System — Code Ideas & Scratchpad · March 2026 · *

---

## Nutrition & Fueling

```python
# Caloric expenditure estimation
def estimate_calories(tss: float, ftp: float, sport: str) -> float:
    efficiency = {"bike": 0.235, "run": 0.42, "swim": 0.38, "strength": 0.30}
    e = efficiency.get(sport, 0.35)
    return round((tss / 100) * ftp * 3600 * e / 4184 * 1000, 0)  # kcal

# In-session fueling prescription
def calculate_fueling_targets(duration_min: int, tss: float, sport: str, race_format: str = None) -> dict:
    if duration_min < 60:
        return {"carbs_g_hr": 0, "fluid_ml_hr": 500, "note": "Pre-load sufficient"}
    elif duration_min < 90:
        return {"carbs_g_hr": 35, "fluid_ml_hr": 625, "note": "Optional but beneficial at high intensity"}
    elif duration_min < 180:
        return {"carbs_g_hr": 70, "fluid_ml_hr": 875, "note": "Required — dual-source carbs (2:1 glucose:fructose)"}
    else:
        target = 90 if race_format in ("ironman", "70.3") else 80
        return {
            "carbs_g_hr": target,
            "fluid_ml_hr": 875,
            "note": f"Gut training target — build to {target}g/hr progressively",
            "sodium_mg_hr": 500  # sweat rate calibration needed for individual
        }

# Race-day fueling plan generator (injected into taper week LLM prompt)
def build_race_day_fueling_context(race_format: str, athlete_ftp: float, race_date: str) -> dict:
    plans = {
        "olympic": {
            "carb_load_days": 1,
            "race_morning_carbs_g": 100,
            "on_course_carbs_g_hr": 50,
            "on_course_note": "One gel before T2; sip electrolyte on bike only"
        },
        "70.3": {
            "carb_load_days": 2,
            "race_morning_carbs_g": 150,
            "on_course_carbs_g_hr": 75,
            "on_course_note": "Every 20min on bike; gel at T2; 2 gels on run"
        },
        "ironman": {
            "carb_load_days": 3,
            "race_morning_carbs_g": 200,
            "on_course_carbs_g_hr": 90,
            "on_course_note": "Every 15min on bike from 30min in; aid station every 2.5km on run"
        }
    }
    return plans.get(race_format, plans["olympic"])

# Fueling compliance field added to execution score
def score_fueling_compliance(planned_carbs_g: float, actual_carbs_g: float) -> dict:
    if planned_carbs_g == 0:
        return {"fueling_scored": False}
    ratio = actual_carbs_g / planned_carbs_g
    return {
        "fueling_scored": True,
        "fueling_ratio": round(ratio, 2),
        "fueling_flag": "UNDER_FUELED" if ratio < 0.75 else ("OVER_FUELED" if ratio > 1.30 else "OK")
    }
```

---

## Injury Tracking & RPE Logging

```python
from pydantic import BaseModel
from typing import Optional, List

class PostSessionLog(BaseModel):
    session_date: str
    sport: str
    rpe: int                            # 1–10
    leg_feel: int                       # 1–5
    motivation: int                     # 1–5
    pain_reported: bool = False
    pain_entries: List[dict] = []       # [{location, type, severity, onset}]
    notes: str = ""
    fueling_actual_carbs_g: Optional[float] = None

@app.post("/api/post-session-log")
async def save_post_session_log(log: PostSessionLog):
    db.execute("INSERT INTO post_session_logs VALUES ...", log.dict())
    
    # Check for injury risk signals immediately on save
    flags = check_injury_signals(log)
    if flags:
        notify_injury_risk(flags)
    
    return {"saved": True, "flags": flags}

def check_injury_signals(log: PostSessionLog) -> list:
    flags = []
    
    # Recurring pain at same location
    if log.pain_reported:
        for entry in log.pain_entries:
            recent_pains = db.query("""
                SELECT COUNT(*) FROM post_session_logs,
                       json_array_elements(pain_entries) AS p
                WHERE session_date >= NOW() - INTERVAL '21 days'
                  AND p->>'location' = %s
            """, (entry["location"],))
            if recent_pains[0]["count"] >= 2:
                flags.append({
                    "type": "RECURRING_NIGGLE",
                    "location": entry["location"],
                    "message": f"3rd report of pain at {entry['location']} in 3 weeks — consider rest or medical review"
                })
    
    # RPE higher than expected for TSS
    recent_rpe = db.query("""
        SELECT AVG(p.rpe) as avg_rpe, AVG(e.tss_ratio) as avg_execution
        FROM post_session_logs p
        JOIN execution_scores e USING (session_date)
        WHERE p.session_date >= NOW() - INTERVAL '14 days'
          AND p.sport = %s
    """, (log.sport,))
    
    if recent_rpe and recent_rpe[0]["avg_execution"] and recent_rpe[0]["avg_execution"] < 0.88:
        if recent_rpe[0]["avg_rpe"] > 7.5:
            flags.append({
                "type": "RPE_EXECUTION_MISMATCH",
                "message": "High RPE relative to low execution for 2+ weeks — hidden fatigue or illness pattern"
            })
    
    return flags

def calculate_acute_chronic_ratio(athlete_id: str, sport: str = "all") -> float:
    """
    Acute:chronic workload ratio. > 1.5 is the established injury risk threshold.
    """
    acute_tss = get_rolling_tss(athlete_id, days=7, sport=sport)
    chronic_tss = get_rolling_tss(athlete_id, days=28, sport=sport)
    if chronic_tss == 0:
        return 1.0
    return round(acute_tss / chronic_tss, 2)
```

---

## Race Result Ingestion

```python
class RaceResult(BaseModel):
    race_id: str                        # links to race_calendar
    overall_time_sec: int
    placement_overall: Optional[int] = None
    placement_ag: Optional[int] = None
    swim_time_sec: Optional[int] = None
    t1_time_sec: Optional[int] = None
    bike_time_sec: Optional[int] = None
    t2_time_sec: Optional[int] = None
    run_time_sec: Optional[int] = None
    bike_avg_power_w: Optional[float] = None
    bike_normalized_power_w: Optional[float] = None
    run_avg_pace_sec_km: Optional[float] = None
    avg_hr: Optional[int] = None
    water_temp_c: Optional[float] = None
    air_temp_c: Optional[float] = None
    wetsuit_used: bool = False
    fueling_carbs_g_hr: Optional[float] = None
    gi_issues: bool = False
    subjective_swim: Optional[int] = None   # 1–10
    subjective_bike: Optional[int] = None
    subjective_run: Optional[int] = None
    notes: str = ""

def analyse_race_result(result: RaceResult, athlete: dict, ctl_at_race: float) -> dict:
    analysis = {}
    
    # Pacing analysis — run fade
    if result.run_time_sec and result.run_avg_pace_sec_km:
        # Pull split data from Garmin FIT file for the race activity
        run_splits = get_run_splits_from_fit(result.race_id)
        if run_splits and len(run_splits) >= 2:
            first_half_pace = avg_pace(run_splits[:len(run_splits)//2])
            second_half_pace = avg_pace(run_splits[len(run_splits)//2:])
            fade_pct = ((second_half_pace - first_half_pace) / first_half_pace) * 100
            analysis["run_fade_pct"] = round(fade_pct, 1)
            if fade_pct > 8:
                analysis["run_pacing_note"] = f"Run faded {fade_pct:.0f}% in second half — started too fast or under-fueled"
    
    # Bike power vs expected
    if result.bike_avg_power_w and athlete.get("ftp"):
        race_if = result.bike_avg_power_w / athlete["ftp"]
        expected_if = {"olympic": 0.85, "70.3": 0.78, "ironman": 0.72}.get(
            get_race_format(result.race_id), 0.80
        )
        analysis["bike_if"] = round(race_if, 2)
        analysis["bike_if_vs_expected"] = round(race_if - expected_if, 2)
    
    # CTL correlation — store for long-term pattern building
    analysis["ctl_at_race"] = ctl_at_race
    analysis["performance_index"] = calculate_performance_index(result, athlete)
    
    return analysis

def embed_race_result_for_rag(result: RaceResult, analysis: dict) -> str:
    """Create rich text summary for vector embedding."""
    return f"""
Race: {get_race_name(result.race_id)} — {get_race_format(result.race_id)}
CTL at race: {analysis['ctl_at_race']:.0f}
Overall time: {format_time(result.overall_time_sec)}
Bike IF: {analysis.get('bike_if', 'n/a')} (expected: {analysis.get('expected_if', 'n/a')})
Run fade: {analysis.get('run_fade_pct', 'n/a')}%
Conditions: {result.air_temp_c}°C, wetsuit {'yes' if result.wetsuit_used else 'no'}
GI issues: {'yes' if result.gi_issues else 'no'}
Notes: {result.notes}
"""
```

---

## NFOR Detection

```python
def check_nfor_signals(athlete_id: str) -> dict:
    """
    Multi-week overreaching detector. Runs nightly alongside daily pipeline.
    Returns assessment and whether to trigger recovery block insertion.
    """
    signals_suppressed = []
    
    # HRV: 7-day mean vs 28-day mean
    hrv_7d = get_rolling_hrv_mean(athlete_id, days=7)
    hrv_28d = get_rolling_hrv_mean(athlete_id, days=28)
    if hrv_7d and hrv_28d:
        consecutive_suppressed = count_consecutive_days_hrv_suppressed(athlete_id, threshold=0.90)
        if consecutive_suppressed >= 10:
            signals_suppressed.append({
                "signal": "hrv_trend",
                "detail": f"HRV 7d mean {(hrv_7d/hrv_28d - 1)*100:.0f}% below 28d mean for {consecutive_suppressed} days"
            })
    
    # Execution ratio: rolling 7-day
    exec_7d = get_rolling_execution_ratio(athlete_id, days=7)
    if exec_7d and exec_7d < 0.80:
        # Check it's not a planned deload
        if not is_deload_week(athlete_id):
            signals_suppressed.append({
                "signal": "execution_ratio",
                "detail": f"7-day execution ratio {exec_7d:.0%} — consistent underdelivery without planned deload"
            })
    
    # RPE drift: compare last 2 weeks vs prior 4 weeks at similar TSS
    rpe_drift = calculate_rpe_drift(athlete_id, weeks_recent=2, weeks_prior=4)
    if rpe_drift and rpe_drift > 0.8:  # >0.8 RPE points per TSS unit increase
        signals_suppressed.append({
            "signal": "rpe_drift",
            "detail": f"RPE rising {rpe_drift:.1f} points per equivalent TSS unit over 2 weeks"
        })
    
    # Resting HR elevation
    rhr_7d_vs_28d = get_resting_hr_delta_pct(athlete_id)
    if rhr_7d_vs_28d and rhr_7d_vs_28d > 5.0:
        consecutive_elevated = count_consecutive_days_rhr_elevated(athlete_id)
        if consecutive_elevated >= 7:
            signals_suppressed.append({
                "signal": "resting_hr",
                "detail": f"Resting HR {rhr_7d_vs_28d:.0f}% above 28d mean for {consecutive_elevated} days"
            })
    
    nfor_detected = len(signals_suppressed) >= 2
    
    if nfor_detected:
        # Check load context — is this training-induced or life stress?
        recent_tss = get_rolling_tss(athlete_id, days=14)
        normal_tss = get_rolling_tss(athlete_id, days=60) / 60 * 14
        load_is_cause = recent_tss > normal_tss * 0.9  # load was normal or high
        
        action = "insert_recovery_block" if load_is_cause else "flag_life_stress"
        
        # Notify
        notify_nfor(athlete_id, signals_suppressed, action)
        
        if action == "insert_recovery_block":
            queue_monthly_replan(current_month(), reason="nfor_detected",
                                 override={"insert_recovery_block": True, "duration_weeks": 2})
    
    return {
        "nfor_detected": nfor_detected,
        "signals": signals_suppressed,
        "n_signals": len(signals_suppressed),
        "action": action if nfor_detected else None
    }
```

---

## Notification & Pipeline Monitoring

```python
import httpx

NTFY_URL = "http://localhost:8080"   # self-hosted ntfy instance

def notify(title: str, message: str, priority: str = "default", tags: list = None):
    """Send push notification via ntfy.sh."""
    httpx.post(f"{NTFY_URL}/coaching-alerts", json={
        "title": title,
        "message": message,
        "priority": priority,          # min | low | default | high | urgent
        "tags": tags or []
    })

def notify_pipeline_failure(component: str, error: str):
    notify(
        title=f"⚠️ Pipeline failure: {component}",
        message=error,
        priority="high",
        tags=["warning", "pipeline"]
    )

def notify_nfor(athlete_id: str, signals: list, action: str):
    signal_names = ", ".join(s["signal"] for s in signals)
    notify(
        title="🚨 Overreaching detected",
        message=f"Signals: {signal_names}. Action: {action.replace('_', ' ')}.",
        priority="urgent",
        tags=["health", "overreaching"]
    )

def check_pipeline_health() -> dict:
    """Run before each daily pipeline job. Returns health dict; notifies on failures."""
    checks = {}
    
    # Garmindb last sync
    last_sync = db.fetchone("SELECT MAX(sync_time) FROM garmindb_sync_log")
    hours_since = (datetime.now() - last_sync["max"]).total_seconds() / 3600
    checks["garmindb"] = "ok" if hours_since < 26 else "stale"
    
    # Health data post
    last_health = db.fetchone(
        "SELECT MAX(created_at) FROM health_context WHERE date = %s", (today(),)
    )
    checks["health_data"] = "ok" if last_health["max"] else "missing"
    
    # Disk space (TrueNAS or local)
    import shutil
    total, used, free = shutil.disk_usage("/mnt/truenas")
    checks["disk_space"] = "ok" if (free / total) > 0.20 else "low"
    
    # Database connections
    try:
        db.execute("SELECT 1")
        checks["postgresql"] = "ok"
    except Exception as e:
        checks["postgresql"] = f"error: {e}"
    
    failures = [k for k, v in checks.items() if v != "ok"]
    if failures:
        notify_pipeline_failure(", ".join(failures), str(checks))
    
    return checks

def generate_weekly_summary(athlete_id: str) -> str:
    """Build weekly retrospective text. Delivered via email and UI."""
    week_start = get_week_start()
    
    planned = get_weekly_planned_tss(athlete_id, week_start)
    actual = get_weekly_actual_tss(athlete_id, week_start)
    sessions = get_weekly_sessions(athlete_id, week_start)
    fitness = get_current_fitness(athlete_id)
    top_signal = get_top_signal_this_week(athlete_id, week_start)
    
    completed = len([s for s in sessions if s["executed"]])
    total = len(sessions)
    
    return f"""
Week {get_week_number()} Summary — {week_start} to {get_week_end()}
{'─' * 45}
Planned TSS: {planned:.0f}    Actual TSS: {actual:.0f}    Execution: {actual/planned*100:.0f}%
Sessions completed: {completed}/{total}

CTL: {fitness['ctl']:.1f} ({fitness['ctl_delta']:+.1f} this week)   ATL: {fitness['atl']:.1f}   TSB: {fitness['tsb']:.1f}
Top signal this week: {top_signal}

FTP advisory: {get_ftp_advisory(athlete_id)}
Weeks to A-race ({get_next_a_race_name(athlete_id)}): {get_weeks_to_a_race(athlete_id)}
{'─' * 45}
"""
```

---

## Testing Protocol Generation

```python
def generate_ftp_test_session(protocol: str, ftp_current: float) -> dict:
    protocols = {
        "20min": {
            "title": "FTP Test — 20 Minute",
            "structure": {
                "warmup": {"duration_min": 15, "target": "Build from Z1 to Z3"},
                "main_sets": [
                    {"type": "effort", "duration_min": 5, "target": "maximal — clear legs"},
                    {"type": "rest", "duration_min": 5, "target": "easy spin"},
                    {"type": "effort", "duration_min": 20, "target": "maximal sustained — your FTP is 95% of avg power here"},
                ],
                "cooldown": {"duration_min": 10}
            },
            "result_calculation": lambda avg_20min_power: avg_20min_power * 0.95
        },
        "ramp": {
            "title": "FTP Test — Ramp",
            "structure": {
                "warmup": {"duration_min": 10, "target": "easy"},
                "main_sets": [
                    {"type": "ramp", "start_watts": round(ftp_current * 0.45),
                     "increment_watts_per_min": round(ftp_current * 0.033),
                     "target": "hold each step until failure"}
                ],
                "cooldown": {"duration_min": 5}
            },
            "result_calculation": lambda peak_1min_power: peak_1min_power * 0.75
        }
    }
    return protocols[protocol]

def detect_test_from_fit(fit_data: dict, session_date: str) -> dict | None:
    """
    Detect if a completed session matches an FTP or CSS test protocol.
    Returns test type and calculated result if detected.
    """
    duration_min = fit_data["duration_sec"] / 60
    
    # 20-minute test signature: single long maximal effort ~20min
    power_efforts = extract_sustained_efforts(fit_data["power_stream"], min_duration_sec=1100)
    if power_efforts:
        best_20min = max(e["avg_power"] for e in power_efforts if 1100 < e["duration_sec"] < 1400)
        if best_20min:
            return {"type": "ftp_20min", "raw_value": best_20min, "ftp_estimate": best_20min * 0.95}
    
    # CSS test signature: two maximal swim efforts (400m + 200m)
    if fit_data.get("sport") == "swim":
        swim_efforts = extract_swim_efforts(fit_data)
        if len(swim_efforts) >= 2:
            best_400 = next((e for e in swim_efforts if 350 < e["distance_m"] < 450), None)
            best_200 = next((e for e in swim_efforts if 175 < e["distance_m"] < 225), None)
            if best_400 and best_200:
                css = (400 - 200) / (best_400["duration_sec"] - best_200["duration_sec"])
                return {"type": "css", "raw_value": css, "css_sec_per_100m": round(100 / css, 1)}
    
    return None
```

---

## Weather-Aware Scheduling

```python
import openmeteo_requests

def get_forecast(lat: float, lon: float, days: int = 7) -> list:
    """Fetch daily forecast from Open-Meteo."""
    client = openmeteo_requests.Client()
    response = client.weather_api("https://api.open-meteo.com/v1/forecast", params={
        "latitude": lat, "longitude": lon,
        "daily": ["temperature_2m_max", "precipitation_sum", "windspeed_10m_max",
                  "weathercode"],
        "forecast_days": days
    })
    return parse_forecast(response[0].Daily())

def score_weather_for_session(forecast_day: dict, session: dict) -> dict:
    """Score a day's forecast suitability for an outdoor session."""
    sport = session.get("sport")
    temp = forecast_day["temp_max_c"]
    precip = forecast_day["precipitation_mm"]
    wind = forecast_day["windspeed_max_kmh"]
    wmo_code = forecast_day["weathercode"]
    
    issues = []
    severity = "ok"
    
    # Temperature checks
    if sport == "run":
        if temp > 35:
            issues.append({"issue": "extreme_heat", "severity": "high"})
            severity = "reschedule"
        elif temp > 32:
            issues.append({"issue": "heat", "severity": "moderate"})
            severity = "modify"
    
    if sport == "bike" and temp > 35:
        issues.append({"issue": "extreme_heat", "severity": "high"})
        severity = "reschedule"
    
    # Storm / lightning (WMO codes 95–99)
    if wmo_code >= 95:
        issues.append({"issue": "storm_lightning", "severity": "high"})
        severity = "substitute_indoor"
    elif precip > 10 and sport == "bike":
        issues.append({"issue": "heavy_rain_cycling", "severity": "moderate"})
        severity = "substitute_indoor"
    
    # Snow / ice (WMO codes 71–77, 85–86)
    if wmo_code in range(71, 78) or wmo_code in (85, 86):
        issues.append({"issue": "snow_ice", "severity": "high"})
        severity = "reschedule_or_treadmill"
    
    return {"severity": severity, "issues": issues, "forecast": forecast_day}

def apply_weather_to_weekly_review(week_sessions: list, forecast: list, athlete_location: dict) -> list:
    """Check each outdoor session against forecast. Return modified week."""
    modified = []
    for session in week_sessions:
        if session.get("environment") == "outdoor":
            day_idx = (date.fromisoformat(session["date"]) - date.today()).days
            if 0 <= day_idx < len(forecast):
                weather = score_weather_for_session(forecast[day_idx], session)
                if weather["severity"] != "ok":
                    session["weather_flag"] = weather
                    session["weather_note"] = build_weather_note(weather, session)
        modified.append(session)
    return modified
```

---

## Gear & Equipment Tracking

```python
def get_shoe_mileage(shoe_id: str, athlete_id: str) -> dict:
    """Current mileage for a shoe from Garmin run activities since purchase date."""
    shoe = db.fetchone("SELECT * FROM gear_items WHERE gear_id = %s", (shoe_id,))
    
    mileage_km = db.fetchone("""
        SELECT COALESCE(SUM(distance_m) / 1000, 0) as km
        FROM garmin_activities
        WHERE athlete_id = %s
          AND sport = 'run'
          AND activity_date >= %s
          AND (gear_id = %s OR gear_id IS NULL)  -- tagged or untagged (ambiguous)
    """, (athlete_id, shoe["purchase_date"], shoe_id))["km"]
    
    status = (
        "healthy" if mileage_km < 400 else
        "approaching_limit" if mileage_km < 600 else
        "replace_window" if mileage_km < 750 else
        "overdue"
    )
    
    if status in ("replace_window", "overdue"):
        notify(
            title=f"👟 Shoe check: {shoe['name']}",
            message=f"{mileage_km:.0f}km — time to replace",
            priority="default" if status == "replace_window" else "high"
        )
    
    return {"shoe": shoe["name"], "mileage_km": round(mileage_km, 0), "status": status}

def get_chain_wear_status(bike_id: str) -> dict:
    """Estimate chain mileage since last replacement."""
    last_replacement = db.fetchone("""
        SELECT replacement_date FROM gear_maintenance
        WHERE gear_id = %s AND component = 'chain'
        ORDER BY replacement_date DESC LIMIT 1
    """, (bike_id,))
    
    since_date = last_replacement["replacement_date"] if last_replacement else None
    
    km_since = db.fetchone("""
        SELECT COALESCE(SUM(distance_m) / 1000, 0) as km
        FROM garmin_activities
        WHERE sport IN ('bike', 'virtual_ride')
          AND gear_id = %s
          AND activity_date >= %s
    """, (bike_id, since_date or "2020-01-01"))["km"]
    
    status = "healthy" if km_since < 2500 else "approaching" if km_since < 3000 else "replace"
    return {"km_since_replacement": round(km_since, 0), "status": status}
```

---

## HRV Device Normalisation

```python
def get_hrv_zscore(athlete_id: str, date_str: str) -> dict:
    """
    Return HRV as z-score relative to device-specific baseline.
    Never compare raw HRV values across devices.
    """
    record = db.fetchone(
        "SELECT hrv_value, device_source FROM daily_biometrics WHERE athlete_id = %s AND date = %s",
        (athlete_id, date_str)
    )
    if not record or not record["hrv_value"]:
        return {"hrv_available": False}
    
    device = record["device_source"]
    
    # Get 28-day baseline FOR THIS DEVICE only
    stats = db.fetchone("""
        SELECT AVG(hrv_value) as mean, STDDEV(hrv_value) as sd
        FROM daily_biometrics
        WHERE athlete_id = %s
          AND device_source = %s
          AND date BETWEEN %s - INTERVAL '28 days' AND %s - INTERVAL '1 day'
          AND hrv_value IS NOT NULL
    """, (athlete_id, device, date_str, date_str))
    
    if not stats["sd"] or stats["sd"] == 0:
        return {"hrv_available": True, "hrv_zscore": 0, "device": device, "normalised": False}
    
    zscore = (record["hrv_value"] - stats["mean"]) / stats["sd"]
    pct_vs_baseline = ((record["hrv_value"] - stats["mean"]) / stats["mean"]) * 100
    
    return {
        "hrv_available": True,
        "hrv_raw": record["hrv_value"],
        "hrv_zscore": round(zscore, 2),     # USE THIS for cross-session comparison
        "hrv_pct_vs_baseline": round(pct_vs_baseline, 1),
        "hrv_baseline_mean": round(stats["mean"], 1),
        "device": device,
        "normalised": True
    }

def handle_device_transition(athlete_id: str, old_device: str, new_device: str, transition_date: str):
    """
    When athlete switches HRV device, initiate overlap calibration period.
    During 14-day overlap both devices record; calculate offset factor.
    """
    db.execute("""
        INSERT INTO device_transitions (athlete_id, old_device, new_device, transition_date, calibration_complete)
        VALUES (%s, %s, %s, %s, FALSE)
    """, (athlete_id, old_device, new_device, transition_date))
    
    notify(
        title="📱 HRV device transition detected",
        message=f"Switched from {old_device} to {new_device}. Using device-specific z-scores. "
                f"Wear both devices for 14 days if possible to calibrate offset.",
        priority="low"
    )
```

---

## Multi-Athlete Support

```python
# Per-athlete database routing — all queries go through this
class AthleteDB:
    def __init__(self, athlete_id: str):
        self.athlete_id = athlete_id
        self.db_name = f"athlete_{athlete_id}"
        self.conn = get_db_connection(self.db_name)
    
    def execute(self, query, params=None):
        return self.conn.execute(query, params)
    
    def fetchone(self, query, params=None):
        return self.conn.fetchone(query, params)

# Athlete switcher middleware — all API requests include athlete context
@app.middleware("http")
async def inject_athlete_context(request: Request, call_next):
    athlete_id = request.headers.get("X-Athlete-ID") or request.cookies.get("athlete_id")
    if athlete_id:
        request.state.athlete_db = AthleteDB(athlete_id)
        request.state.athlete_id = athlete_id
    return await call_next(request)

# Pipeline runner — always athlete-scoped
def run_daily_pipeline(athlete_id: str):
    adb = AthleteDB(athlete_id)      # all DB access goes through this
    athlete = adb.fetchone("SELECT * FROM athlete_profiles WHERE athlete_id = 1")
    
    garmindb_sync(athlete["garmin_credentials"])   # separate credentials per athlete
    planned = fetch_all_planned_workouts(athlete, adb)
    # ... all subsequent steps use adb, never shared db
```

---

## Brick & Open Water Specifics

```python
def calculate_brick_run_targets(athlete: dict, bike_tss: float, bike_duration_min: int) -> dict:
    """
    Generate run pace targets for brick sessions.
    First 5 minutes explicitly slower than steady state — this is correct, not a failure.
    """
    lthr = athlete["lthr_run"]
    threshold_pace = athlete["threshold_pace_sec_km"]
    
    # Expected leg heaviness modifier — empirical, calibrate from athlete's brick history
    opening_modifier = 1.06  # ~6% slower for first 5 min off the bike
    # Bigger bikes require more adjustment
    if bike_duration_min > 90:
        opening_modifier = 1.09
    if bike_tss > 100:
        opening_modifier = 1.12
    
    return {
        "opening_5min_pace_sec_km": round(threshold_pace * opening_modifier),
        "steady_state_pace_sec_km": threshold_pace,
        "note": (
            f"First 5 min: {format_pace(threshold_pace * opening_modifier)}/km — "
            f"legs will feel heavy, this is normal. "
            f"Settle to {format_pace(threshold_pace)}/km from 5min onwards."
        )
    }

def score_brick_execution(planned: dict, fit_data: dict) -> dict:
    """Score brick as combined session with discipline breakdown."""
    bike_data = extract_discipline_split(fit_data, "bike")
    run_data = extract_discipline_split(fit_data, "run")
    
    run_splits = extract_km_splits(run_data)
    opening_pace = avg_pace(run_splits[:5]) if len(run_splits) >= 5 else None
    steady_pace = avg_pace(run_splits[5:]) if len(run_splits) > 5 else None
    final_third = avg_pace(run_splits[len(run_splits)*2//3:]) if len(run_splits) >= 6 else None
    mid_third = avg_pace(run_splits[len(run_splits)//3:len(run_splits)*2//3]) if len(run_splits) >= 6 else None
    
    run_fade = None
    if final_third and mid_third:
        run_fade = ((final_third - mid_third) / mid_third) * 100  # positive = slowing
    
    return {
        "bike_tss_ratio": safe_ratio(bike_data.get("tss"), planned.get("bike_planned_tss")),
        "bike_if": safe_ratio(bike_data.get("normalized_power"), planned.get("ftp")),
        "t2_sec": fit_data.get("t2_duration_sec"),
        "run_opening_pace": opening_pace,
        "run_steady_pace": steady_pace,
        "run_fade_pct": round(run_fade, 1) if run_fade else None,
        "run_fade_flag": "FADE" if run_fade and run_fade > 6 else "OK"
    }

def log_open_water_session(session_data: dict, garmin_activity: dict) -> dict:
    """Supplement Garmin open water sync with additional context."""
    return {
        **garmin_activity,
        "water_temp_c": session_data.get("water_temp_c"),
        "wetsuit_used": session_data.get("wetsuit_used", False),
        "conditions": session_data.get("conditions", "unknown"),  # flat|choppy|rough
        "sighting_frequency": session_data.get("sighting_per_100m"),
        "pool_equivalent_pace": calculate_pool_equivalent(
            garmin_activity["avg_pace_sec_100m"],
            session_data.get("conditions"),
            session_data.get("wetsuit_used")
        )
    }
```

---

## Sleep Staging Integration

```python
def get_sleep_detail(athlete_id: str, date_str: str) -> dict:
    """Pull sleep staging breakdown from Garmindb alongside aggregate score."""
    record = db.fetchone("""
        SELECT sleep_score, total_sleep_min, deep_sleep_min, rem_sleep_min,
               light_sleep_min, awake_min
        FROM garmin_sleep
        WHERE athlete_id = %s AND sleep_date = %s
    """, (athlete_id, date_str))
    
    if not record:
        return {"sleep_available": False}
    
    flags = []
    if record["deep_sleep_min"] < 60:
        flags.append("LOW_DEEP_SLEEP")
    if record["rem_sleep_min"] < 90:
        flags.append("LOW_REM")
    if record["awake_min"] > 30:
        flags.append("FRAGMENTED_SLEEP")
    
    return {
        "sleep_available": True,
        "sleep_score": record["sleep_score"] / 100 if record["sleep_score"] else None,
        "total_hr": round(record["total_sleep_min"] / 60, 1),
        "deep_hr": round(record["deep_sleep_min"] / 60, 1),
        "rem_hr": round(record["rem_sleep_min"] / 60, 1),
        "awake_min": record["awake_min"],
        "flags": flags,
        # Signal value for importance model — independent from score
        "deep_sleep_signal": record["deep_sleep_min"] / 60
    }
```

---

## Data Export & Portability

```python
import zipfile, io, csv, json
from pathlib import Path

@app.post("/api/export/all")
async def export_all_data(athlete_id: str = "1", background_tasks: BackgroundTasks = None):
    """Trigger full data export. Runs async — notifies via ntfy when ready."""
    background_tasks.add_task(run_full_export, athlete_id)
    return {"status": "export_queued", "message": "Export started — you'll be notified when ready"}

def run_full_export(athlete_id: str):
    adb = AthleteDB(athlete_id)
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        
        # Athlete profile
        profile = adb.fetchone("SELECT * FROM athlete_profiles")
        zf.writestr("athlete_profile.json", json.dumps(profile, indent=2, default=str))
        
        # Race calendar
        races = adb.query("SELECT * FROM race_calendar ORDER BY date")
        zf.writestr("race_calendar.json", json.dumps(races, indent=2, default=str))
        
        # Execution scores — CSV
        scores = adb.query("SELECT * FROM execution_scores ORDER BY session_date")
        zf.writestr("execution_scores.csv", to_csv(scores))
        
        # Post-session logs
        logs = adb.query("SELECT * FROM post_session_logs ORDER BY session_date")
        zf.writestr("post_session_logs.csv", to_csv(logs))
        
        # Race results
        results = adb.query("SELECT * FROM race_results ORDER BY race_date")
        zf.writestr("race_results.json", json.dumps(results, indent=2, default=str))
        
        # Signal importance history
        weights = adb.query("SELECT * FROM signal_weights ORDER BY trained_on")
        zf.writestr("signal_importance_history.json", json.dumps(weights, indent=2, default=str))
        
        # LLM generation log (fine-tuning dataset)
        llm_log = adb.query("SELECT * FROM pipeline_run_log ORDER BY timestamp")
        zf.writestr("llm_generation_log.json", json.dumps(llm_log, indent=2, default=str))
        
        # Original FIT files from Garmindb cache
        fit_dir = Path(f"/data/garmindb/{athlete_id}/activities")
        for fit_file in fit_dir.glob("*.fit"):
            zf.write(fit_file, f"fit_files/{fit_file.name}")
    
    # Save to outputs dir and notify
    export_path = Path(f"/data/exports/{athlete_id}_export_{date.today().isoformat()}.zip")
    export_path.write_bytes(zip_buffer.getvalue())
    
    notify(
        title="📦 Data export ready",
        message=f"Your full data export is ready to download.",
        priority="default",
        tags=["export"]
    )
```

---

*AI Coaching System — Code Ideas & Scratchpad · March 2026 · , *
