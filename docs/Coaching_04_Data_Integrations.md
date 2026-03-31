# AI Coaching System — Data & Integrations

**Sources · Platforms · Health · Gear · Monitoring · Export**

---

## The API Fragility Problem

The three primary data sources — Garmin Connect, TrainingPeaks, and TrainerRoad — share a structural problem: none have a stable, documented, officially supported public API for personal use. Every library that accesses them is reverse-engineering mobile app authentication. When a platform changes their auth flow, everything breaks simultaneously with no warning.

This has already happened. **garth** is now deprecated — Garmin changed their auth flow and broke it. The community patched `python-garminconnect` quickly, but the same break can happen again at any time.

**Design response:** API-first with file-watch fallback. The pipeline tries the API each morning; if it fails for any reason it processes files from a watched import folder and continues normally. A push notification explains what happened and what to drop where. Nothing stops.

### Ingestion Tier Model

| Tier | Method | Reliability | Friction When Working |
|---|---|---|---|
| **Tier 1 — API sync** | Automated overnight via library | Fragile — breaks on auth changes | Zero |
| **Tier 2 — File watch** | Manual download, drop into watched folder, auto-processed | Stable — file formats don't change | ~2 minutes |
| **Tier 3 — UI upload** | Upload button in Data Source Manager | Always works | Manual each time |

---

## Data Source Overview

| Source | Primary Retrieval | File Fallback | Notes |
|---|---|---|---|
| Garmin Connect | `python-garminconnect` | GDPR bulk export (FIT files) + USB sync | Core — everything else supplements |
| TrainingPeaks | OAuth2 API (community approach) | Manual calendar export (CSV + workout files) | Best multi-sport planned session data |
| TrainerRoad | One-time library export + FIT name lookup | TR account settings export | Bike only; library built once and reused |
| Zwift | File watch on local workouts folder | Same — .zwo files are already local | No API ever needed |
| Coach spreadsheets | File watch on import folder | Same | MCR multi-group format natively supported |
| Apple Health | iOS Shortcut → POST via Tailscale | Apple Health XML export | Phone-side; not callable from server |
| Google Health Connect | Android companion → POST via Tailscale | Health Connect export | Phone-side |
| Open-Meteo | REST API (free, self-hostable) | N/A | Low risk; no auth required |

---

## Garmin Data Pipeline

### Current Library Landscape

**python-garminconnect** (cyberjunky) — currently the most actively maintained option, updated March 2026. Wraps garth-compatible OAuth flow with support for a custom consumer key/secret pair workaround. Covers 127+ endpoints. Has had 401 and 403 errors during recent Garmin server changes — maintainer patches quickly, but gaps happen.

**garmy** — newer library built specifically for AI health agent integration. Built-in SQLite local database, CLI sync tools, MCP server interface. Worth watching as a purpose-built alternative.

**Garmindb** — reads FIT files and Garmin Connect data into a local database. More stable than API libraries because it can operate from locally cached FIT files without a live Garmin Connect connection. Preferred for historical data ingestion.

### Garmin API Usage

Where available, used for:
- `GET /workout-service/schedule/{start}/{end}` — planned workouts from calendar
- `GET /workout-service/workouts/{id}` — individual workout definition with full structure
- `POST /workout-service/workouts` — push system-generated sessions to calendar (appears on watch)

The push path is the most valuable and the most at risk. If it breaks, sessions are still delivered via the morning readout UI and I can add to the watch manually. Degraded but functional.

### Garmin File Fallback

**GDPR bulk export:** Request via Garmin Connect → Settings → Export Your Data. Garmin takes a few days. Delivers all FIT files, sleep data, and health metrics as CSVs. Used for initial historical load or extended API outage recovery.

**USB direct sync:** Garmin device mounts as USB drive. FIT files at `/GARMIN/Activities/`. Garmindb ingests directly — no Garmin Connect needed.

**Watch folder:** `/imports/garmin/fit/` — pipeline watches this and processes any new FIT files on the next morning run.

---

## Planned Workout Retrieval

The planned session is the other side of the plan/actual pair. Without it, there's nothing to score execution against.

### Platform Strategy

| Platform | API Status | Fallback | Key Note |
|---|---|---|---|
| Garmin Connect | Unofficial — breaks periodically | GDPR export, USB FIT files | — |
| TrainingPeaks | Official OAuth2 requires partnership; community approach tolerated | Manual calendar export to CSV | — |
| TrainerRoad | **Not needed as ongoing sync** | One-time library export | Workout name in FIT file; library lookup handles it |
| Zwift | Already local | Same | No API ever needed |
| Coach spreadsheets | File watch | Same | Auto-processed on drop |

### TrainerRoad — FIT Name Lookup

TR workout names are embedded in Garmin FIT file metadata when sessions sync. The name is already there — "Carillon +2", "Pettit", "Galena". The only thing needed from TrainerRoad is a one-time export of the workout library to match those names to full interval structures and coaching text.

**Three-level matching:**
1. **Exact** — "Pettit" → "Pettit"
2. **Base name** — "Carillon +2" strips suffix → tries "Carillon"
3. **Multi-signal fuzzy** — name similarity + IF delta + TSS delta + workout type classification (VO2max / threshold / sweet spot / tempo / endurance derived from actual IF). Workout type pre-filters the library before name similarity is calculated. Hard pass if IF delta > 12% or TSS delta > 30% — too physiologically different regardless of name.

Library is built once, lives locally, works indefinitely. If `trainerroad-export` eventually breaks, the existing library keeps matching.

### Coach Spreadsheets — Supported Layouts

| Layout | Description | Detection |
|---|---|---|
| **MCR multi-group** | Brian Kraft / MCR format: week/date cols, Key Weekly Components col, 4 ability group columns, 3-4 session rows per week | `is_mcr_layout()` detects group column pattern |
| **Layout A** | Weeks as rows, days as columns | Header contains day name keywords |
| **Layout B** | Weeks as columns, session types as rows | Week labels in header, sport in first col |
| **Layout C** | Flat list with explicit date column | Header has 'date' + 'sport' or 'activity' |
| **LLM fallback** | Non-standard layout | First 25 rows rendered as text → LLM extracts sessions |

My ability group column (e.g. `"GB 13.1 26-40"`) is stored in the athlete profile — set once, applied automatically on every import.

### Unified Planned Session Schema

All sources normalise to this schema before storage:

```
planned_session
├── session_id       (uuid)
├── source_platform  (trainingpeaks | trainerroad | zwift | garmin | system | spreadsheet)
├── import_method    (api | file_watch | manual_upload | fit_name_lookup)
├── planned_date
├── sport            (swim | bike | run | strength | climb | yoga | mobility)
├── title
├── coaching_text    ← original coaching intent — preserved verbatim
├── planned_duration_min
├── planned_tss
├── planned_if       ← null for non-power sports
├── planned_distance_m
├── structure
│   ├── warmup        [ {type, distance_m or duration_sec, target} ]
│   ├── main_sets     [ {repeat, distance_m or duration_sec, target, rest_sec} ]
│   └── cooldown
└── targets { hr_zone, power_zone, pace_zone, rpe_target }
```

---

## Plan vs Actual Comparison Engine

### Per-Session Metrics

| Metric | How Measured | Significance |
|---|---|---|
| TSS delta | Actual − Planned TSS | Positive = overcooked; negative = underdelivered |
| IF delta | Actual − Planned IF | Intensity accuracy |
| Duration delta | Actual − Planned duration | Volume compliance |
| Set completion | % of planned sets completed | Did I bail early |
| Zone distribution | Actual % per zone vs planned | Was I in the right zones |
| Pace accuracy (run) | Avg pace vs target per interval | Run execution quality |
| CSS accuracy (swim) | Avg per-100m vs CSS target | Swim execution quality |
| Power accuracy (bike) | Avg power vs target per interval | Most precise |
| Fueling compliance | Actual intake vs planned | For sessions > 90min |

Execution score = weighted composite of TSS ratio, duration ratio, set completion. Flags generated: `OVERCOOKED` (TSS >115%), `UNDERDELIVERED` (<75%), `TOO_HARD` (IF delta >0.10), `BAILED` (set completion <80%).

### Sport-Specific TSS

| Sport | Basis | Notes |
|---|---|---|
| Bike | Power vs FTP | Standard TSS formula |
| Run | Pace vs LTHR | hrTSS using lactate threshold HR |
| Swim | Pace vs CSS | ssTSS — CSS as threshold reference |
| Strength | Volume load proxy | Sets × reps × relative intensity coefficient; rough but trackable |
| Climbing | hrTSS + elevation bonus | HR vs LTHR, small bonus for gained elevation |
| Yoga / mobility | Duration coefficient by subtype | 0.02–0.5 TSS/min; restorative near-zero |

---

## Health Platform Integrations

Garmin doesn't hold menstrual cycle data from tracking apps, medication logs, or CGM blood glucose. Apple Health and Google Health Connect aggregate these from other sources.

**Integration pattern:** Phone-side companion (iOS Shortcut or Android Tasker) reads from the health store and POSTs to the server via Tailscale. Data never leaves the local network.

| Data Type | Apple Health | Google Health Connect | Garmin |
|---|---|---|---|
| Menstrual cycle phase | ✓ HealthKit | ✓ Health Connect | Partial — Lily only |
| Medication log | ✓ HealthKit | Partial | ✗ |
| HRV (supplemental) | ✓ Apple Watch | ✓ | ✓ primary |
| Blood glucose / CGM | ✓ Dexcom, Libre | ✓ | ✗ |
| Sleep (supplemental) | ✓ | ✓ | ✓ primary |

Garmin remains the primary source for HRV, sleep, and activity data. Health platform supplements it — primarily for cycle phase and medications.

---

## Athlete Profile & Medical Context

```
Profile
├── Physiological parameters
│   ├── FTP (synced from Garmin — never manually set here)
│   ├── CSS (calculated quarterly from swim data)
│   ├── LTHR — run and bike separately
│   └── Weight, height, age
├── Health context (encrypted at rest)
│   ├── Menstrual cycle tracking — opted in/out
│   ├── Contraceptive type (affects cycle model)
│   ├── Medications — name, class, known effects
│   └── Medical notes — free text
├── Equipment registry
│   └── Home base equipment (diffed against vacation checklist)
├── Training preferences
│   ├── Preferred rest day
│   ├── Morning / evening preference
│   └── Max weekly hours cap
└── Coach plan group column
    └── e.g. "GB 13.1 26-40" — auto-applied on spreadsheet import
```

### Cycle Phase Interpretation

Hormonal variation is modeled through signal interpretation, not session swapping. A suppressed HRV in late luteal is annotated as expected hormonal context in the LLM prompt — not flagged as overtraining.

| Phase | Days | Load Modifier | Key Behaviour |
|---|---|---|---|
| Menstrual | 1–5 | 0.85 | Perceived effort elevated; HRV suppression expected and normal |
| Follicular | 6–13 | 1.00 | Good loading window |
| Ovulation | ~14 | 1.05 | Peak window — ideal for threshold tests, key sessions |
| Early luteal | 15–21 | 1.00 | Maintain load; core temp slightly elevated |
| Late luteal | 22–28 | 0.90 | HRV may suppress without fatigue cause — annotated, not flagged |

Data from `HKCategoryTypeIdentifierMenstrualFlow` and `HKCategoryTypeIdentifierOvulationTestResult` (Apple) or equivalent Health Connect categories. Clue, Flo, Natural Cycles all write to these stores. Hormonal contraceptives suppress natural variation — cycle model disabled when applicable.

### Medication-Aware Training

| Class | Examples | Effect | System Response |
|---|---|---|---|
| Beta blockers | Metoprolol, Atenolol | Blunts HR 10–30bpm | Disable HR-zone targets entirely; shift to RPE and power |
| SSRIs / SNRIs | Sertraline, Venlafaxine | HRV chronically suppressed | Calibrate baseline with flag; suppress false overtraining alerts |
| ACE inhibitors | Lisinopril | Mild | Advisory flag only |
| Corticosteroids | Prednisone | Short course elevated energy | Flag duration; reduce load if long course |
| Thyroid meds | Levothyroxine | Stable dose: minimal | Note if recently changed |

Medications entered in the Athlete Profile UI — classification maps names to effect flags injected into LLM context.

---

## Weather-Aware Scheduling

Open-Meteo (free, self-hostable via Docker) provides current conditions and 7-day forecasts. Used at weekly review (forecast-based rescheduling) and morning decision (current conditions for session notes and pace adjustments).

| Condition | Impact | Response |
|---|---|---|
| > 32°C outdoor run | Performance risk | Move to early morning; relax pace targets; heat cues in notes |
| > 35°C | Health risk | Substitute indoor or reschedule |
| Heavy rain, outdoor ride | Safety risk | Offer Zwift substitute at same TSS |
| Storm / lightning | Do not ride | Reschedule; Zwift substitute |
| Snow / ice | Surface unsafe | Reschedule or treadmill |
| Strong headwind > 35km/h | Ride feel | Power targets unchanged; note in session |

During vacation/retreat windows weather source switches to destination location automatically.

---

## Gear & Equipment Tracking

### Shoe Mileage

Tracked automatically from Garmin run activity data. Multiple shoes tracked separately; I tag which shoes were worn per session (or infer from activity type).

| State | Mileage | System Action |
|---|---|---|
| Healthy | 0–400km | No flags |
| Approaching limit | 400–600km | Advisory in weekly summary |
| Replace window | 600–750km | Flag in morning readout; note in session |
| Overdue | > 750km | ntfy push alert |

### Bike Component Tracking

| Component | Lifespan | Tracking |
|---|---|---|
| Chain | ~3,000km | Bike distance from Garmin; manual stretch check reminder |
| Cassette | ~9,000–15,000km | From chain replacement intervals |
| Tyres — training | ~5,000km | Distance tracked; manual wear flag |
| Tyres — race | Inspect per race | Prompt during A-race taper week |

---

## HRV Device Normalisation

Garmin, Apple Watch, HRV4Training, Polar, and Whoop produce values that are not directly comparable — measurement window, time of day, algorithm (RMSSD vs SDNN), and body position all differ. Switching devices mid-dataset produces a discontinuity that looks like a fitness change.

**Rules:**
- Every HRV reading tagged with source device from day one
- All trend analysis uses z-scores relative to device-specific 28-day baseline — raw values never compared across devices
- Z-score = (reading − device's 28-day mean) / device's 28-day SD
- On device switch: 14-day overlap calibration period; offset factor calculated if old device still active
- Prefer RMSSD where selectable — most consistent across devices

---

## Notification & Pipeline Monitoring

### What Gets Monitored

| Component | Alert Condition |
|---|---|
| Garmindb sync | No new data when yesterday had planned sessions |
| Health data POST | No companion post received by 7am |
| LLM generation | Job runtime > 2x historical or error in log |
| Garmin workout push | HTTP error or session absent from calendar |
| Zwift file write | File missing or zero-byte |
| InfluxDB / PostgreSQL | Connection failure |
| Disk space | < 20% free on TrueNAS |

### Notification Channels

| Channel | Use Case | Implementation |
|---|---|---|
| Morning readout (web UI) | Normal daily delivery — primary | FastAPI, browser/mobile |
| **ntfy.sh** (self-hosted) | Pipeline failures, NFOR alerts, gear warnings | Single HTTP POST |
| Email (local Postfix) | Weekly summary, race calendar updates | Lightweight SMTP from Steiger |
| Grafana alert | Metric threshold alerts | Built-in Grafana alerting |

### Weekly Summary

Every Sunday: planned vs actual TSS, session completion, best/worst execution, CTL/ATL/TSB, top signal of the week, FTP advisory, weeks to next A-race, coming week's key sessions.

---

## Data Export & Portability

It's my data. Full export possible at any time in open formats.

| Data Type | Export Format |
|---|---|
| All activities | Original FIT files + GPX |
| Training plan history | JSON + CSV |
| Athlete profile | JSON |
| Race results | CSV + JSON |
| Injury log | CSV |
| Signal importance history | CSV (weights over time) |
| Nutrition log | CSV |
| LLM generation log | JSON — full context + output (the fine-tuning dataset) |
| InfluxDB metrics | CSV per measurement type |

One-click **Export All Data** in the UI — async job, zip archive, ntfy when ready.

### Backup Architecture

- PostgreSQL: nightly `pg_dump` → TrueNAS backup pool
- InfluxDB: nightly backup → TrueNAS
- FIT file cache: Garmindb local → TrueNAS
- Chroma/Qdrant: nightly snapshot
- Configuration: version-controlled in private git repo

---

*AI Coaching System — Data & Integrations · Personal Project · 2026*
