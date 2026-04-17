# AI Triathlon Coaching System

A self-hosted AI coaching engine for endurance athletes. Generates, delivers, and continuously refines triathlon training plans across swim, bike, and run — informed by Garmin data, HRV, sleep, nutrition, weather, and race context. Runs overnight on your own hardware. No subscriptions, no cloud dependency, no averaged-population plans.

---

## What It Does

A three-tier planning loop runs fully automated:

| Tier | Frequency | Output |
|---|---|---|
| **Monthly** | 1st of month / block transition | Full mesocycle — sessions, load arc, taper positioning, conditional alternates pre-authored for every hard session |
| **Weekly** | Sunday overnight | LLM reviews prior week execution, adjusts coming week against 7-day weather and fitness drift |
| **Morning** | Daily at 3am | Checks overnight biometrics against learned signal weights — surfaces primary + conditional alt with signal summary |

The LLM (~6 calls/week on a 70B model) handles planning and review. Everything else — FIT parsing, TSS/CTL/ATL math, signal learning, NFOR detection, gear tracking — is deterministic code or conventional ML.

---

## Architecture

```
Garmin Connect / FIT files
    ↓
Data Ingestion (garmindb, python-garminconnect, FIT file fallback)
    ↓
InfluxDB (time-series: HR, power, pace, HRV, TSS)
PostgreSQL (plans, execution pairs, profiles, gear, race results)
ChromaDB (RAG: historical training blocks)
    ↓
Analysis Pipeline (CTL/ATL/TSB, signal importance, NFOR, HRV normalisation)
    ↓
LLM Context Assembly → Ollama 70B (external host)
    ↓
Plan output → Garmin Connect (.fit) + Zwift (.zwo)
Notifications → ntfy.sh
Dashboards → Grafana
Web UI → FastAPI + React
```

**External dependency:** Ollama running separately on any host with sufficient VRAM (16GB+ for 70B Q4). The compose stack connects to it via `OLLAMA_BASE_URL`.

---

## Stack

| Layer | Tool |
|---|---|
| Data ingestion | garmindb, python-garminconnect, FIT file watch folder |
| Planned sessions | TrainingPeaks API, TrainerRoad library lookup, Zwift .zwo, coach spreadsheets |
| Health data | Apple Health (iOS Shortcut) / Google Health Connect (Tasker) via Tailscale |
| Time-series | InfluxDB 2.x |
| Relational | PostgreSQL 16 |
| Vector / RAG | ChromaDB |
| LLM inference | Ollama (llama3.1:70b or qwen2.5:72b recommended) |
| Analysis | Python, scikit-learn (Random Forest, ElasticNet for signal importance) |
| Output | .fit generation (Garmin push), .zwo generation (Zwift) |
| Notifications | ntfy.sh (self-hosted) |
| Dashboards | Grafana |
| Web UI | FastAPI + React |

---

## Prerequisites

- Docker + Docker Compose
- Ollama running externally with a 70B model loaded (or smaller for testing)
- Garmin Connect account (for data sync + workout push)
- ~16GB RAM for the stack; Ollama host needs GPU with 16GB+ VRAM for 70B Q4

---

## Setup

**1. Clone and configure**
```bash
git clone https://github.com/sasharif87/Personal-Training-App.git
cd Personal-Training-App
cp .env.example .env
```

Edit `.env` — at minimum set:
- `OLLAMA_BASE_URL` → your Ollama host URL
- `INFLUXDB_TOKEN` → generate with `openssl rand -hex 32`
- `INFLUXDB_PASSWORD`, `GRAFANA_PASSWORD`, `DATABASE_URL` passwords
- `GARMIN_USERNAME` / `GARMIN_PASSWORD`
- `NTFY_TOPIC` → generate a random topic name (see comment in `.env.example`)
- `TZ` → your local timezone

**2. Create your season config**
```bash
cp config/season.json.example config/season.json  # if provided, or create manually
```
`config/season.json` is gitignored — it holds your personal thresholds (FTP, CSS, LTHR) and race calendar.

**3. Start the stack**
```bash
docker compose up -d
```

Services: InfluxDB `:8086`, PostgreSQL `:5432`, ChromaDB `:8000`, Grafana `:3000`, Config UI `:8080`

**4. Verify**
```bash
docker compose ps
docker compose logs coaching-app --tail 50
```

The coaching app runs a 3am daily pipeline via internal APScheduler. To trigger manually:
```bash
docker exec coaching_app python main.py --run-daily
```

---

## Project Structure

```
backend/
  analysis/         # CTL/ATL/TSB, signal importance, HRV normalisation, NFOR
  api/              # FastAPI app + data export endpoints
  data_ingestion/   # Garmin sync, TrainingPeaks, health data, weather
  library/          # Workout library (TrainerRoad, Zwift, TCX parsers)
  llm/              # Ollama client, database hooks
  orchestration/    # Daily/weekly/monthly pipeline runners
  output/           # .fit generation (Garmin), .zwo generation (Zwift)
  planning/         # Season planner, context builders, LLM prompts
  rag/              # ChromaDB vector indexing and retrieval
  schemas/          # Pydantic models for all data exchange
  storage/          # InfluxDB + PostgreSQL clients
config/
  workouts/         # Generic workout library (run.json, swim.json)
  season.json       # Your thresholds and race calendar (gitignored)
docs/               # Architecture and design documentation
frontend/           # React UI (season builder, morning readout, nutrition)
```

---

## Status

> **Active development — last updated April 2026**

This project is being built and used. It is not abandoned or stale — commits are ongoing and the pipeline runs nightly on real training data.

| Area | State |
|---|---|
| Core backend pipeline | Implemented |
| Data ingestion (Garmin, TP, TR, spreadsheets) | Implemented |
| Analysis (CTL/ATL/TSB, NFOR, signal importance) | Implemented |
| LLM orchestration (daily/weekly/monthly) | Implemented |
| Garmin + Zwift output | Implemented |
| FastAPI backend + export API | Implemented |
| Frontend (React UI) | In progress |
| TrueNAS SCALE deployment | In progress |
| End-to-end pipeline testing | In progress |

See [docs/](docs/) for full architecture and design detail.

---

## Documentation

| Doc | Contents |
|---|---|
| [01 Vision & Architecture](docs/Coaching_01_Vision_Architecture.md) | System design, LLM vs code breakdown, planning tiers, UI modules, hardware |
| [02 Planning & Roadmap](docs/Coaching_02_Planning.md) | Phase A–E timelines, build order, dependencies |
| [03 Training Logic](docs/Coaching_03_Training_Logic.md) | Race formats, signal learning, NFOR, test protocols, bricks |
| [04 Data & Integrations](docs/Coaching_04_Data_Integrations.md) | Data sources, API fragility design, health platforms, gear, HRV |
| [05 Nutrition](docs/Coaching_05_Nutrition.md) | Meal planning, in-session fueling, gut training, race day |
