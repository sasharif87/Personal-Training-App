# AI Coaching System — Project Planning & Roadmap

**Phase Sequence · Dependencies · Decision Points · Timeline**

> See **Doc 01** for system architecture. **Doc 03** for training logic. **Doc 04** for data integrations. **Doc 05** for nutrition detail. **Doc 06** for code patterns.

---

## Project Status

| Field | Detail |
|---|---|
| Priority | Planning starts behind race season, SME, TrueNAS infra, house projects |
| Status | Concept fully documented — infrastructure awareness mode only |
| Phase A start | Late 2026 — after core infra is stable and UPS installed |
| Full operational system | 2028 — refinement loop with RAG and fine-tuning |
| Hard dependencies | Stable TrueNAS, UPS, Ollama deployed, Garmin pipeline, JupyterLab |

> **Do not start this project until TrueNAS infrastructure is fully stable.** Building a data pipeline on an unstable system risks data corruption — particularly for InfluxDB and the Garmin historical archive. The UPS being unresolved is a real data integrity risk.

---

## Why Build Order Matters

The temptation is to jump to the LLM layer because it is the interesting part. That is the wrong order. The analysis layer cannot do useful work without clean data. The LLM cannot reason well without a working analysis layer feeding it structured inputs. The RAG layer cannot retrieve relevant history without embeddings built from clean historical data. Each phase is a genuine prerequisite for the next.

The plan/actual comparison engine depends on having planned session data pulled from TrainingPeaks, TrainerRoad, and Garmin before it can evaluate execution. That retrieval layer must be established early — it is as foundational as the completed activity pipeline.

The system is the hard part. Model quality improves automatically when you upgrade hardware or models improve. The pipeline architecture — data cleaning, analysis notebooks, prompt structure, output format, retrieval logic, plan/actual scoring — is the investment that does not become obsolete.

---

## Phase A — Data Foundation

### Target: Late 2026

Prerequisites: stable TrueNAS, UPS installed and verified, core services running without issues.

### Garmin Data Pipeline — Completed Activities

- Deploy Garmindb — connect to Garmin Connect, pull 10 years of historical FIT files
- Establish ongoing sync — new activities pull automatically as they complete
- Connect Garmindb output to InfluxDB — time-series storage for all metrics
- Verify data quality — 10 years across multiple Garmin device generations will have gaps, format differences, device change artifacts to clean
- Pull planned workout definitions alongside completed activities — need both sides of the plan/actual pair

### Planned Workout Retrieval — All Platforms

This is new scope for Phase A and must be established before the analysis layer can function. Without planned session data, there is nothing to compare actual execution against.

**TrainingPeaks**

- Establish OAuth2 connection to TrainingPeaks API
- Pull full workout calendar history — all sports, all planned sessions
- Capture coaching text alongside structured data — the intent is as valuable as the numbers
- Store planned sessions in PostgreSQL with unified schema (see Architecture doc)
- Map to completed Garmin activities by date and sport — build plan/actual pairs
- Handle gaps where planned session has no corresponding completed activity — these are the missed workouts, which are data too

**TrainerRoad**

- One-time export of the full TR workout library using `trainerroad-export` (community tool — run it once, store the library locally, no ongoing dependency)
- Build local `tr_workout_library` table from the export — keyed by name, with interval structure, TSS, IF, and coaching text
- TR workout names are already embedded in Garmin FIT file metadata when TR sessions sync through Garmin — no separate ongoing pull needed
- Enrichment pipeline: FIT file arrives → extract `workout_name` field → look up in local library (exact match → base name match → multi-signal fuzzy match on name + IF + TSS + workout type) → attach full structure as the planned session
- See Doc 06 for full matching logic including hard-pass rules on IF and TSS delta

**Zwift**

- Parse existing .zwo files from workouts folder — extract power targets as FTP fractions
- Reconstruct absolute watt targets from FTP at time of session
- Build lookup table of completed Zwift rides (via Garmin sync) against planned .zwo sessions
- Establish ongoing capture: when the system writes a new .zwo, log the planned session simultaneously

**Garmin Planned Workouts**

- Pull all planned workout definitions via python-garminconnect workout API (with file-watch fallback)
- These capture coach-pushed sessions and system-authored sessions after Phase C
- Include step-by-step interval structure where available

**Coach Spreadsheets**

- Build MCR-layout parser to ingest multi-group coach plan spreadsheets
- Athlete's group column stored in profile — auto-applied on every import
- Drop .xlsx or .csv into /imports/spreadsheets/ — pipeline picks up and processes overnight
- Generic layout detection for non-MCR plans; LLM fallback for unrecognised layouts

### Trainer Road Library Build

- Run `trainerroad-export` once to pull the full TR workout library to disk
- Build `tr_workout_library` PostgreSQL table: name, description, TSS, IF, duration, workout_type, interval structure
- Classify each workout type (VO2max / threshold / sweet spot / tempo / endurance / recovery) from IF value
- Create trigram index on name field for fuzzy match performance
- Library stays on disk indefinitely — ongoing TR data arrives via Garmin FIT sync and is matched against it automatically

### Cross-Training Logging Setup

- Establish strength and cross-training log schema in PostgreSQL
- Create simple manual entry interface for gym sessions — exercise, sets, reps, weight, RPE
- Add Garmin activity type mapping for climbing, yoga, hiking — auto-import where Garmin captures them
- Define TSS coefficients for each cross-training type (see Architecture doc)
- Back-populate historical cross-training data where records exist

### Season Planning Tool — Initial Build

- Build URL ingestion script: fetch event page → LLM extraction → race_event schema
- Test against common sources: Ironman.com, World Triathlon, RunSignUp, BikeReg
- Store race calendar in PostgreSQL with A/B/C priority field
- Auto-calculate taper start and recovery end dates from priority and format
- Output to race_calendar.md on each update — human-readable reference file

### Nutrition Foundation

- Build nutrition product library in PostgreSQL — seed with common products (Maurten, SiS, Clif, etc.)
- Add nutrition profile fields to Athlete Profile UI — dietary approach, allergies, preferences, cooking time
- Build post-session nutrition log — what products were used, amount, GI response
- Establish in-session fueling target calculation and wire into session note generation for sessions > 90min
- Back-populate any existing nutrition logs from TrainingPeaks or manual records

### Gear Registry & Shoe Mileage

- Build gear registry UI — shoe models, bikes, components with initial mileage entries
- Wire shoe mileage to Garmin activity sync — auto-increment from run distance
- Wire bike distance to chain and tyre tracking
- Back-populate historical mileage from Garmin 10-year activity data where possible

### Pipeline Monitoring — Baseline

- Instrument the Garmindb sync job — log success/failure and row counts pulled
- Set up ntfy.sh (self-hosted) for push alerts on sync failure
- Basic health check endpoint on FastAPI: GET /api/health returns status of all pipeline components
- Disk space monitoring alert to TrueNAS and ntfy

### Athlete Profile & Data Source Manager UI — Initial Build

The first UI surfaces to build are the ones needed before any data pipeline can run. The profile and data source manager must exist before the coaching pipeline has anything to read.

- Deploy FastAPI backend on current server — lightweight, serves /api/* endpoints
- Build Athlete Profile UI — physiological parameters, medication entry, cycle tracking opt-in, equipment registry
- Build Data Source Manager UI — connection status for each platform, OAuth initiation buttons, manual sync triggers, error log display
- Health platform connection: establish iOS Shortcut or Android Tasker companion for Apple Health / Google Health Connect posting
- Validate health data ingestion — cycle phase, medication flags arriving at server and storing correctly

This does not need to be polished in Phase A — it needs to work. Polish comes in Phase C alongside the morning readout and season builder.

### LLM Familiarisation

- Deploy Ollama and Open WebUI on current server
- Run 13B model — understand what it produces for training plan prompts before building around it
- Identify where model reasoning falls short at this size — informs Phase C prompt design
- Deploy JupyterLab — development environment for all subsequent analysis work

> **Phase A output:** clean, queryable 10-year dataset in InfluxDB, planned sessions from all platforms in PostgreSQL, initial plan/actual pairs, cross-training log framework, working season planning tool, functional athlete profile and data source manager UI, and health platform ingestion running. Probably 4–5 months of part-time work to clean, retrieve, and verify properly.

---

## Phase B — Analysis Layer

### Target: Early 2027

Pure data science — no LLM involved yet. The goal is to understand what your data actually says about your physiology before asking a model to reason over it. These notebooks become the analysis layer that feeds structured context into the LLM in Phase C.

### Fitness Modeling

- CTL/ATL/TSB curves across all sports including cross-training — combined load and per-sport
- Verify CTL curves against known training blocks — do they reflect what you remember?
- Identify gaps and anomalies — illness periods, detraining, injury history
- Validate cross-training TSS coefficients against HR and perceived effort data

### Plan vs Actual Analysis

- Build execution scoring across all historical plan/actual pairs from Phase A
- Calculate execution ratios per sport, per session type, per block phase
- Identify systematic patterns: which session types do you consistently under/over deliver?
- Correlate execution quality to antecedent HRV, sleep, and fatigue state
- Build execution quality metric that the LLM can use as a signal

### Swim-Specific Analysis

- Extract CSS from historical swim data — identify threshold pace from test efforts and race data
- Build CSS-relative stress scoring — comparable to TSS for run and bike
- Stroke rate and DPS trends where Garmin has captured them
- Analyse swim set completion rates from TrainingPeaks history — do you finish prescribed sets?

### Cross-Training Impact Analysis

- Correlate strength session timing to subsequent run and bike performance
- Quantify climbing session impact on leg fatigue — how many days to return to baseline?
- Model yoga/mobility contribution to recovery — does it measurably accelerate HRV recovery?
- Build cross-training interference patterns: which combinations create problematic fatigue stacking?

### Physiological Correlations

- HRV correlation analysis — does morning HRV trend predict subsequent performance degradation for you specifically?
- Sleep quality correlation — which sleep metrics most reliably predict training execution quality?
- Environmental impact analysis — how much does heat suppress your power? Your run pace?
- Recovery curve modeling — how long does your run recovery actually take after different session intensities?

### FTP History

- Reconstruct FTP history from power curve analysis across 10 years
- Correlate FTP changes to training blocks — what actually moved the needle for you?
- Identify seasonal FTP patterns — when does your FTP peak in a typical year?

### Injury Pattern Analysis

- Review 10 years of activity data alongside any available injury records for load patterns preceding injuries
- Calculate acute:chronic workload ratio history — identify past spikes that correlated with injury
- Tag historical periods of reduced activity likely to be injury-related (long unexplained gaps or sharp volume drops)
- Build preliminary sport-specific injury risk thresholds from personal data

### HRV Device Normalisation

- Identify all HRV data sources in the historical record and tag by device
- Calculate per-device baselines independently — never mix raw values across devices
- Establish z-score normalisation as the standard for all HRV trend analysis going forward
- If device transitions exist in the historical data, calculate offset factors for the overlap periods

### Fueling Data Review

- Extract any existing Garmin nutrition logging
- Review historical long sessions for performance fade patterns that suggest fueling failures
- Establish personal sweat rate estimate from HR and conditions data where available
- Identify gut training sessions in TrainingPeaks history where logged

### Sleep Staging Baseline

- Pull deep sleep, REM, and wake time data from Garmindb alongside sleep score
- Add deep sleep hours as an independent variable in the signal importance baseline analysis
- Check whether deep sleep correlates differently to execution quality than total sleep score

> **Phase B output:** full physiological parameter set including personal injury risk profile, HRV device normalisation established, sleep staging added to signal analysis, and fueling baseline understood.

Before the learning engine can run in Phase C, Phase B does the groundwork: understanding whether the signals are even correlated in this dataset, and what the correlation structure looks like before any ML model is applied.

- Run Pearson and Spearman correlations between all available morning signals and execution quality across historical data
- Identify which signals have enough data to be meaningful vs which are too sparse to use (e.g. skin temp delta may not exist for years of Garmin data)
- Check for signal collinearity — HRV and resting HR are often correlated; understanding this prevents double-counting
- Identify any signals that are *negatively* correlated — if body battery is consistently *uncorrelated* with execution for this athlete, that is as useful to know as if it is highly correlated
- Document the preliminary signal ranking before Phase C trains the full model — this becomes the baseline to validate against

> **Phase B output:** a set of personal physiological parameters — your numbers, not population averages. These become the structured inputs the LLM receives in Phase C rather than raw data.

---

## Phase C — Structured Prompt Pipeline

### Target: Mid 2027 — Steiger build available

Connect analysis outputs to the LLM. Start simple — direct prompting with structured inputs, no RAG yet. This phase is about finding out what the model does well and where it fails for your specific use case.

Three prompt types need to work before Phase C is complete: the monthly generation prompt, the weekly review prompt, and the morning decision prompt. They have different contexts, different input shapes, and different output requirements.

**Monthly Generation Prompt**

- Build structured fitness state summary — CTL/ATL/TSB (all sports), cross-training load, HRV trend, sleep quality, FTP, block position, weeks to A-race
- Feed race calendar context — A-race format and date, B/C race treatment, taper windows
- Ask LLM to produce a full month of sessions as structured JSON — day by day, with load arc, intensity distribution, rationale
- Each threshold-or-above session must include a conditional alt alongside the primary — written at generation time, not reactively
- Log the full generation context and output — this is a training example from day one
- Assess monthly output quality: does the load progression make sense? Are recovery weeks actually easy? Is the alt meaningfully different or just a token intensity reduction?

**Weekly Review Prompt**

- Input: prior week execution scores (TSS ratio, IF delta, set completion per session), current fitness state
- Input: coming week sessions from monthly plan (as originally generated)
- Ask LLM to review and adjust — modified sessions, reordered days, volume changes if fatigue drifted
- Output: revised week with rationale for each change
- Do not regenerate the full month on weekly review — only the coming week; preserve the monthly arc

**Morning Decision Prompt**

- Input: today's planned session + conditional alt from monthly plan, overnight HRV, sleep score, body battery, yesterday's execution score
- Ask LLM to: (1) assess signal conflict level, (2) write final versions of primary and alt, (3) produce a one-line signal summary for the morning readout
- Output is presented to athlete — not acted on automatically
- Log my selection and subsequent execution — did they pick primary or alt, and how did it go?

**Other Phase C milestones**

- Test Zwift .zwo output generation — validate power targets against FTP fractions
- Test Garmin workout push via python-garminconnect — verify sessions appear on watch correctly
- Run 70B Q4 via CPU offload — validate overnight batch generation is practical
- Build morning readout format — notification or simple dashboard showing both options with signal context

**Weekly Meal Planning & Meal Prep**

- Integrate weekly meal plan generation into the Sunday weekly review LLM prompt
- Build Nutrition Planner UI module — weekly meal view, meal prep checklist, shopping list
- Build shopping list generator from weekly meal plan
- Test meal plan quality — does the load-anchored carb structure match the training week?
- Wire nutrition compliance log into weekly summary and execution scoring

**Gut Training Protocol**

- Implement carb target escalation logic in monthly generation for IM/70.3 build phases
- Progressive targets: 40–50g/hr weeks 1–2 → 80–90g/hr weeks 7–8
- Track gut training compliance in post-session log; slow escalation if GI issues logged
- Wire product tolerance data into session fueling plan product selection

**Race Day Fueling Plan Generation**

- Build race-day fueling plan generator — fires during A-race taper week
- Plan expressed in specific products from athlete's library, by discipline, by time/distance marker
- Include contingency protocol for GI distress
- Add race nutrition review to post-race result intake

- Build vacation planner UI — date range, location, equipment checklist, training intent selector
- Implement equipment constraint logic in monthly generation prompt — available_equipment drives allowed session types
- Environmental context (heat, altitude) passed to LLM for target adjustments
- Test with a known past travel window — does the generated plan look reasonable for those constraints?

**Training Retreat Mode**

- Build retreat entry in vacation planner UI — retreat type, facility, daily structure, altitude
- Implement pre-retreat taper logic — 3–5 day arrival freshness window
- Implement post-retreat recovery week — auto-inserted after retreat end date
- Altitude protocol: reduce intensity targets days 1–3 regardless of HRV readings

**Full UI Build**

- Season Builder — visual canvas, TSS arc preview, block structure from race calendar
- Morning Readout — primary + alt cards, signal summary, one-tap choice logging
- Plan Calendar — month view with session cards, alt indicators, executed/missed colouring
- Execution Dashboard — Grafana embed with plan vs actual, HRV trend, FTP advisory
- Athlete choice logging UI — minimal: tap Primary / tap Alt, optional notes field

**Testing Protocol Generation**

- Build FTP, CSS, and LTHR test session generators — produce Zwift .zwo and Garmin structured workout simultaneously
- Build test result intake: detect test protocol from FIT file, auto-calculate threshold, confirmation prompt before Garmin update
- Validate zone recalculation fires correctly after confirmed test result

**Injury & RPE Logging**

- Build post-session logging UI — RPE, leg feel, motivation, body map pain entry
- Wire RPE data into morning decision context — pattern of RPE higher than expected for TSS is a signal
- Build acute:chronic workload ratio monitoring — alert when ratio > 1.5
- Implement 10% weekly run volume cap in monthly generation logic

**Race Result Ingestion**

- Build race result intake form in Event Manager UI — splits, conditions, fueling, subjective feel
- Wire race result analysis: pacing fade detection, discipline vs fitness comparison, CTL correlation
- Add race results as high-value embeddings to vector database schema (ready for Phase D)

**NFOR Detection**

- Build multi-week signal monitor running alongside daily pipeline
- Wire NFOR alert to ntfy push notification and prominent UI banner
- Implement recovery block insertion logic — triggered by NFOR detection

**Nutrition Integration**

- Add fueling targets to session notes for all sessions > 90 minutes
- Build race-day fueling plan generator as part of A-race taper week output
- Add fueling compliance field to post-session log
- Wire fueling failure annotation into execution scoring

**Weather-Aware Weekly Review**

- Integrate Open-Meteo 7-day forecast into weekly review context
- Implement session rescheduling logic for weather conflicts
- Test against known past weather events — does it produce sensible substitutions?

**Open Water & Brick Specifics**

- Tag open water sessions separately from pool sessions in session type schema
- Implement brick run pace targeting logic — first 5 minutes vs body of run have different targets
- Add brick-specific execution scoring — combined session with discipline breakdown
- Add open water session types to monthly generation output schema

**Notification & Monitoring — Full Build**

- Build weekly summary report generator and email/ntfy delivery
- Instrument all pipeline stages with success/failure logging and timing
- Wire all alert conditions to ntfy with appropriate severity levels
- Build pipeline health dashboard in UI — last sync times, error log, job history

> **Phase C output:** complete pipeline with all session types, testing protocols, injury tracking, race result ingestion, NFOR detection, weather scheduling, nutrition targets, and full notification layer. This is the full production-capable system before RAG.



---

## Phase D — RAG Integration

### Target: Late 2027

Only build the retrieval layer when Phase C is working and you have directly observed that context window limits are causing problems. Building RAG before you need it adds complexity without benefit.

- Deploy Chroma or Qdrant vector database — self-hosted, lightweight, runs on current server
- Embed historical training blocks and physiological responses as vectors
- Embed cross-training blocks alongside sport-specific blocks — fatigue patterns are cross-sport
- Build retrieval queries — find similar physiological states in history
- Example: last 3 times in similar heat with suppressed HRV mid-build block — what happened and what worked?
- Inject retrieved context into LLM prompt alongside current state
- Validate that retrieved context actually improves output quality — measure before and after

> **Phase D output:** the system now has access to your full training history as a searchable knowledge base. The LLM can reason about your historical patterns, not just your current state.

---

## Phase E — Full Refinement Loop

### Target: 2028

The complete three-tier autonomous loop. Monthly generation authors the mesocycle. Weekly review keeps it calibrated. Morning decision surfaces dual options and I have the final call.

- Automated daily data ingestion pipeline — no manual triggers
- Monthly generation fires at block phase transitions and on the 1st of each month
- Planned workout fetch runs alongside completed activity sync — both sides always current
- Weekly review fires each Sunday overnight — adjusts coming week against prior week execution drift
- Morning decision generates final primary + conditional alt based on overnight biometrics; I choose
- Plan state management — system tracks day, week, block, and month position
- Athlete choice logging — primary vs alt selection tracked and correlated to execution outcomes over time
- Signal importance model retrains monthly as execution data accumulates — weights shift as patterns emerge
- UI signal importance dashboard shows current top predictors, per-sport breakdown, and surprising findings
- Gear mileage alerts integrated into morning readout — shoe warning appears alongside session card
- Injury history model actively informs monthly generation — personal risk zones respected in load planning
- Race results feed RAG retrieval — historical race lead-ups and outcomes are searchable context
- NFOR detection running continuously — recovery block insertion fully automated
- Weather rescheduling active in weekly review — outdoor sessions moved proactively on forecast conflicts
- Nutrition targets, gut training escalation, and race-day fueling plans fully automated in taper output
- Testing protocol generation fires automatically when FTP advisory crosses confirmation threshold
- Data export available on demand; nightly backups to TrueNAS running reliably
- Cross-training aware scheduling — strength and mobility placed intelligently within the monthly arc
- Workout substitution logic — sport substitution when warranted, not just intensity adjustment
- FTP prediction advisory surfaced in morning readout
- Season planning interface — URL-drop or manual entry, auto race classification, race_calendar.md export

---

## Key Decision Points

| Decision | When | Criteria |
|---|---|---|
| Start Phase A | Late 2026 | TrueNAS stable, UPS installed, no pending infra work that risks data integrity |
| Move to Phase B | After Phase A | Clean data confirmed, InfluxDB verified, planned session retrieval working for all platforms |
| Move to Phase C | Steiger delivered | 7800 XT available as dedicated AI card, analysis notebooks complete, execution scoring validated |
| Add RAG (Phase D) | After Phase C | Have directly observed context window limits causing output quality problems |
| Buy workstation card | After Phase D | Have validated fine-tuning dataset of plan/response pairs, not before |
| Start fine-tuning | 2028+ | Phase D complete, 2+ years of plan/actual pairs collected and validated |

---

*AI Coaching System — Project Planning · March 2026 · *
