# AI Coaching System — Vision & Architecture

**Self-Hosted · Personal Project · Multi-Sport · Physiologically Personal**

---

## What This Is

A self-hosted AI coaching system built for one athlete — me. It generates, delivers, and continuously refines triathlon and endurance training plans across swim, bike, run, and cross-training, informed by 10+ years of personal Garmin data, HRV, sleep, environmental conditions, race format context, and nutrition. Not a subscription. Not a generic plan adapted for my zones. A system that knows my physiology specifically because it was built from my data.

The gap this fills: every commercial tool either treats me as an average athlete, runs only on their servers with their constraints, or handles one sport well and ignores the others. This handles everything, runs locally, and gets better the longer it runs because it's learning from my execution data — not a population.

This is a long-term personal engineering project, built in phases over a few years alongside actual training. The goal is a system running continuously by 2028, generating daily coaching decisions autonomously overnight.

---

## What Exists and Isn't Worth Rebuilding

Several good tools exist for pieces of this. Worth using where they make sense:

| Tool | What It Does Well | Why Not Rely On It Entirely |
|---|---|---|
| Intervals.icu | Excellent fitness modeling (CTL/ATL/TSB), clean API, free | Cloud-hosted, no local LLM, no planned workout authoring, no nutrition |
| Garmindb | Solid local FIT file ingestion | Read-only — no workout push, no session authoring |
| Open-Meteo | Weather forecast API, free, self-hostable | Data source only |
| ntfy.sh | Lightweight self-hosted push notifications | Delivery layer only |
| Grafana | Excellent time-series dashboarding | Visualisation only |

The parts that don't exist anywhere: the three-tier planning loop, conditional alt workouts authored at generation time, learned signal importance per athlete, menstrual cycle and medication context, vacation equipment constraints, gut training protocol, coach spreadsheet ingestion (including MCR-format multi-group plans), TrainerRoad workout library lookup from FIT names, run/swim notation parsing, race result ingestion feeding RAG, and the plan/actual comparison engine. That's the project.

---

## What the LLM Does vs What's Just Code

Worth being explicit about this — it changes how to think about the complexity.

**LLM touch points — roughly 6 calls per week:**
- Monthly plan generation (one call, overnight, 70B model)
- Weekly review and session adjustment (one call, Sunday overnight)
- Morning decision — alt wording when signals conflict (one call, 3am, often skipped when signals are clear)
- Weekly meal plan generation (one call, Monday morning)
- Race day fueling plan — one call during taper week
- Spreadsheet LLM fallback — only when layout detection fails, occasional

**Everything else is deterministic code or conventional ML:**
- FIT file parsing, TSS calculations, zone scoring — code
- TrainerRoad name lookup with multi-signal matching — code
- Swim notation parser, run notation parser, MCR spreadsheet parser — code
- Plan vs actual execution scoring — code
- CTL/ATL/TSB fitness curves — standard formulas
- Signal importance learning (which signals actually predict my session quality) — scikit-learn on tabular data: Random Forest, ElasticNet, Pearson/Spearman correlations
- HRV device normalisation — statistics
- Gear mileage tracking, weather rescheduling, NFOR detection — rules and thresholds

The LLM is important for what it does. But most of what makes this useful is the data pipeline, the parsing infrastructure, the signal processing, and the context assembly that feeds the LLM. Those are engineering problems, not AI problems.

**Fine-tuning** is the long-game payoff. After 12–18 months of operation, ~1,000 labelled plan/execution/outcome pairs exist that no commercial tool has for my physiology. QLoRA fine-tuning a 34B model on that dataset is what turns a well-prompted general model into something genuinely personal. Phase E work.

---

## System Architecture

### Planning Cycle — Three Tiers

| Tier | Frequency | What It Does |
|---|---|---|
| **Monthly generation** | 1st of month / block transition | LLM authors a full 4–5 week mesocycle — load arc, intensity distribution, taper positioning, and conditional alts pre-authored for every threshold-or-above session |
| **Weekly review** | Sunday overnight | LLM reviews prior week execution against the monthly plan — adjusts targets, reorders days, checks 7-day weather for outdoor session conflicts |
| **Morning decision** | Daily at 3am | Checks overnight biometrics against learned signal weights — surfaces primary + conditional alt with one-sentence signal summary. I choose. |

Monthly plan is the structural scaffold. Weekly review keeps it calibrated. Morning decision is advisory — I have the final call, and my choice is logged as a training data point.

### The Alt Workout Design

Hard swaps based on HRV are wrong — HRV is noisy, and subjective feel is a valid input the system can't read. When signals conflict: show both options, let me decide. The system leads with the actual top signal driver (might be sleep duration, body battery, or prior day load — not always HRV). My choice is logged with the biometric snapshot and connected to next day's execution score, building the dataset that teaches the system how predictive each signal actually is for me personally.

| Scenario | Primary | Alt |
|---|---|---|
| HRV suppressed, feel good | Session as planned | Reduced intensity version |
| HRV suppressed, feel rough | Session as planned | Rest or mobility only |
| HRV normal, feel rough | Session as planned | First interval only — abort option |
| HRV elevated, feel great | Session as planned | Extended version if block allows |
| HRV missing / no reading | Session as planned | Same session with HR ceiling — Z3 cap |

### Garmin API Reality

Garmin's Connect API is unofficial — no public developer programme for personal use. Every third-party library reverse-engineers the mobile app authentication. **garth** (referenced in earlier notes) is now deprecated — Garmin changed their auth flow and broke it. Current working option is `python-garminconnect` (cyberjunky), same structural risk.

Design response: API-first with file-watch fallback. Pipeline tries the API each morning; if it fails, processes FIT files from a watched import folder instead. Garmin provides GDPR bulk export and the device mounts as USB — reliable file access that doesn't depend on Garmin's auth staying stable. The system keeps running either way.

Same principle for TrainingPeaks (OAuth approach tolerated but not guaranteed) and TrainerRoad (community export tool, fragile). For TrainerRoad specifically: the workout name is already embedded in the Garmin FIT file — one-time library export, then match FIT names to full interval structures locally. No ongoing API dependency.

### Full Stack

| Layer | Tool / Approach | Role |
|---|---|---|
| Garmin data ingestion | Garmindb + python-garminconnect | FIT files, HRV, sleep, activity data; workout push to Garmin calendar |
| Garmin fallback | FIT file watch folder + USB sync | API-independent path — always available |
| Planned sessions — TP | TrainingPeaks API + CSV export fallback | Multi-sport planned sessions with coaching text |
| Planned sessions — TR | One-time library export + FIT name lookup | TR name in FIT → local library → full interval structure |
| Planned sessions — Zwift | Local .zwo file watch | Already local — no API needed |
| Coach spreadsheets | MCR-layout parser + generic parser + LLM fallback | Coach plan spreadsheets; MCR multi-group format natively supported |
| Health data | Apple Health (iOS Shortcut) / Google Health Connect (Tasker) | Cycle phase, medications — phone-side, POSTed to server via Tailscale |
| Weather | Open-Meteo (free, self-hostable) | 7-day forecast for weekly review; current conditions for morning session notes |
| Time-series storage | InfluxDB | HR, HRV, pace, power, sleep staging |
| Relational storage | PostgreSQL | Plan/actual pairs, profiles, nutrition, gear, injury log, race results, signal weights |
| Analysis & modeling | JupyterLab + Python + scikit-learn | CTL/ATL/TSB, signal importance learning, CSS extraction, injury pattern analysis |
| Vector storage | Chroma or Qdrant | Training blocks + race results for RAG retrieval |
| LLM inference | Ollama (70B Q4) | ~6 calls/week — plan, review, morning, meals, race fueling, spreadsheet fallback |
| Orchestration | Python + systemd timers | Nightly/weekly/monthly pipeline jobs |
| Output — Zwift | .zwo generation | Bike sessions dropped to Zwift workouts folder via SMB / Syncthing |
| Notifications | ntfy.sh (self-hosted) | Pipeline failures, NFOR alerts, gear warnings, weekly summary |
| Dashboards | Grafana | Fitness metrics, plan vs actual, HRV trend, signal importance |
| Web UI | FastAPI + React | Season builder, morning readout, nutrition planner, data source manager |

---

## Operation Loop

**Monthly — 1st of month or block transition**

Pull race calendar → pull fitness state (CTL/ATL/TSB, HRV trend, injury flags, nutrition baseline) → LLM generates full month (sessions + load arc + conditional alts + weekly meal structure) → store to PostgreSQL → push week 1 to Garmin and Zwift, hold weeks 2–4 in store.

**Weekly — Sunday at 3am**

Score prior week (TSS ratio, IF delta, set completion, nutrition compliance, RPE) → check fitness drift → check 7-day weather → LLM reviews and adjusts coming week → push revised week to Garmin and Zwift.

**Morning — Daily at 3am**

Sync Garmin overnight data → score yesterday → evaluate signals with learned weights → surface conditional alt if conflict → build readout (primary + alt + signal summary + fueling targets) → I choose → log selection.

---

## UI Layer

Lightweight web UI on the Steiger box, accessible locally or via Tailscale. Automation runs headless — the UI is for things that need human input.

| Module | Purpose |
|---|---|
| **Season Builder** | Drop event URLs, set A/B/C priority, view TSS arc, trigger plan generation |
| **Morning Readout** | Primary + alt session cards, signal summary, one-tap choice logging |
| **Nutrition Planner** | Weekly meal plan, prep checklist, in-session product log, shopping list |
| **Plan Calendar** | Month view — sessions, alt indicators, executed/missed status |
| **Athlete Profile** | Thresholds, medications, cycle tracking, equipment registry, coach plan group column |
| **Data Source Manager** | Connection status, file import triggers, sync logs, error display |
| **Execution Dashboard** | Grafana-embedded: CTL/ATL/TSB, plan vs actual, HRV trend, signal importance |
| **Vacation Planner** | Travel window, equipment checklist, training intent, retreat mode |
| **Event Manager** | Race calendar — URL extraction, manual entry, taper/recovery window preview |
| **Gear Registry** | Shoe mileage, bike components, replacement alerts |
| **Signal Importance** | Learned weights, top predictors, per-sport breakdown |

FastAPI backend + React frontend. Tailscale for remote access. Grafana iframes in the execution dashboard.

---

## Hardware Plan

| Hardware | Role | LLM Capability |
|---|---|---|
| Current — i5-7600 + Quadro RTX 5000 (16GB) | Phase A–B dev and testing | 13B comfortable; 70B Q4 with CPU offload works for batch |
| Steiger — 9900X + 64GB DDR5 + 7800 XT (16GB) | Phase C–D primary | 70B Q4 hybrid — 16GB GPU + DDR5 overflow, 3–8 tok/s overnight |
| Future GPU — RTX A6000 Ada (48GB) | Phase E fine-tuning | 34B QLoRA on personal data — buy after Phase D, not before |

---

## Document Index

| Doc | Contents |
|---|---|
| **01 Vision & Architecture** (this doc) | Project overview, system design, LLM vs code, planning tiers, UI, hardware |
| **02 Planning & Roadmap** | Phase A–E timelines, dependencies, what gets built when |
| **03 Training & Coaching Logic** | Race formats, signal learning, NFOR, testing protocols, bricks, open water, vacation, retreats |
| **04 Data & Integrations** | Data sources, API fragility design, health platforms, plan vs actual, gear, HRV normalisation, multi-athlete, monitoring, export |
| **05 Nutrition** | Meal planning, meal prep, in-session fueling, product library, gut training, race day plans |
| **06 Code Scratchpad** | Implementation patterns, parsers, schemas, LLM prompts, all platform integrations |

---

*AI Coaching System — Personal Project · Started 2026*
