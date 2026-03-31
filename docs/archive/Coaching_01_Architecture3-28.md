# AI Coaching System — Architecture Reference

**Self-Hosted · Multi-Sport · HRV-Informed · Physiologically Personal**

---

## Vision & Purpose

A self-hosted AI coaching system that generates, delivers, and continuously refines triathlon and endurance training plans across swim, bike, and run — informed by 10 years of personal physiological data, HRV, sleep, environmental variables, and race format context. Not a commercial product. Not a generic plan. A system trained on your data that knows your physiology.

The core capability commercial tools lack: cross-sport load accounting, HRV as a leading indicator rather than lagging response, environmental modeling, genuine workout authoring — not intensity adjustment of pre-built sessions — and a true plan/actual comparison layer that evaluates execution across every session type including cross-training.

---

## Why This Exceeds Commercial Tools

### What Trainer Road AI Actually Does

Trainer Road Adaptive Training is a rule-based system with ML on top. It watches workout compliance, compares power output to targets, and nudges intensity up or down. Reactive, not predictive. Bike only. No swim stress. No HRV prediction. No environmental modeling. No planned workout retrieval from external sources.

| Capability | Commercial Tools | This System |
|---|---|---|
| Multi-sport load accounting | Bike only (Trainer Road) | Swim + Run + Bike + Cross-training combined TRIMP stress |
| HRV integration | Lagging — adjusts after failure | Leading — adjusts before you dig a hole |
| Environmental factors | Not modeled | Wind, heat, altitude inform session targets |
| Personalisation basis | Population averages | 10 years of your specific physiology |
| Workout authoring | Adjusts pre-built sessions | Writes sessions from scratch per context |
| Sleep integration | Manual input only | Automated via Garmin overnight data |
| Swim specificity | None | CSS-based zones, set-level prescription |
| Race format awareness | Generic plans | Olympic, IM, endurance run, Triple Bypass models |
| Plan vs actual comparison | Compliance % only | TSS, IF, duration, zone distribution, set completion |
| Planned workout retrieval | Platform-specific only | TrainingPeaks, TrainerRoad, Zwift, Garmin unified |
| Cross-training load | Not modeled | Strength, climbing, yoga, mobility — all scored |
| Season planning | Manual calendar entry | URL-based event extraction, auto race classification |
| Planning horizon | Week-by-week reactive | Month-at-a-time with weekly review layer |
| HRV adjustment | Hard swap — session replaced | Dual-option: primary + alt presented each morning, athlete chooses |
| Health platform integration | None | Apple Health + Google Health Connect — cycle data, medications, resting metrics |
| Hormonal periodisation | Not modeled | Menstrual cycle phase detection drives session emphasis and load targets |
| Medication-aware training | Not modeled | Beta blockers, cardiac meds — disables HR-based zones, shifts to RPE/power |
| Vacation & travel mode | Not modeled | Auto-detected or manual; athlete declares available equipment, plan adapts |
| Training retreats | Not modeled | High-volume structured blocks; altitude, heat, facility context modeled |
| UI | Platform app only | Web UI: season builder, data source manager, athlete profile, event calendar |

### The Swim Gap

Every commercial tool underestimates swim stress. Proper swim load modeling requires CSS (Critical Swim Speed) as the functional threshold equivalent, pace zones derived from CSS not HR, stroke rate and DPS where Garmin captures it, and recognition that swim fatigue has a different recovery curve — upper body dominant, different systemic load profile to running.

### The Planned Workout Gap

Most tools capture what you *did*. Very few capture what you were *supposed to do* with enough fidelity to evaluate the gap. This system retrieves the original planned session — intervals, targets, set structure, coaching intent text — from whatever platform authored it, and compares it systematically against execution data. That gap is the signal.

---

## System Architecture

### Planning Cycle — Three Tiers

The system operates across three time horizons simultaneously. These are not competing — they are nested. The month sets the structure, the week refines it, the morning finalises it.

| Tier | Frequency | What It Does |
|---|---|---|
| **Monthly generation** | Start of each month | LLM authors a full 4–5 week block — session types, load progression, intensity distribution, taper position — anchored to block phase and race calendar |
| **Weekly review** | Each Sunday overnight | LLM reviews the coming week against actual execution data from the week prior — adjusts session targets, reorders days, modifies volumes if fatigue has drifted from model |
| **Morning decision** | Daily at 3am | System checks overnight HRV, sleep, and body battery — generates an **alt workout** alongside the primary and surfaces both to the athlete. Athlete picks. No hard swap. |

The monthly plan is the scaffold. The weekly review keeps it calibrated. The morning decision is advisory — the athlete always has the final call.

### Why Monthly Rather Than Weekly

A purely reactive weekly loop produces plans that are locally optimal but structurally incoherent. A build block requires progressive overload across 4–6 weeks; a single-week generator cannot reason about that arc. The monthly generation layer lets the LLM author a proper mesocycle — it knows that week 3 should be the peak load week, that week 4 is a recovery week, that the final week before race taper should not introduce new session types. Generating week by week loses that structural intent.

The weekly review layer then keeps the monthly plan honest. If week 1 execution was significantly below plan — illness, travel, life — the week 2 sessions need to reflect that drift, not blindly execute the original week 2 as written.

### The Alt Workout — Why Not Just Swap

Hard swaps based on HRV have a fundamental problem: HRV is noisy. A suppressed reading might mean genuine fatigue, or it might mean a bad night's sleep from a hot room, an unusual meal, alcohol, or an artifact from the sensor. The athlete woke up, stretched, and feels good. Swapping their threshold run for an easy jog without asking insults their autonomy and wastes a training day.

The right model is: **when signals conflict, present both options and let the athlete decide.** The system surfaces why it generated the alt — "HRV 14% below 7-day baseline, sleep quality 0.61, body battery 52" — alongside both sessions. The athlete makes an informed choice. That choice also becomes a data point: did they take the primary and execute well? Did they take the alt and still underperform? Over time, those decisions teach the system how much weight to put on HRV for this specific athlete.

| Scenario | Primary Session | Alt Session |
|---|---|---|
| HRV suppressed, feel good | Threshold run as planned | Z2 run, same duration, reduced intensity |
| HRV suppressed, feel rough | Threshold run as planned | Rest or mobility only |
| HRV normal, feel rough | Planned session | Same session, first interval only — abort option |
| HRV elevated, feel great | Planned session | Extended version or bonus intensity if block phase allows |
| HRV missing / no reading | Planned session | Same session with HR ceiling — cap at Z3 and assess mid-session |

The no-reading case is important. If HRV data is absent — watch not worn, sync failure, sensor noise — the system does not default to treating it as a bad day. It treats it as a missing data point and presents the planned session with an optional HR ceiling as a conservative guardrail.

### The Context Window Problem

A full year plan — 9 workouts x 6 days x 52 weeks — plus 10 years of historical data cannot fit in any LLM context window. The system needs a retrieval layer that pulls relevant historical data into context intelligently rather than dumping everything. This is RAG: Retrieval Augmented Generation.

The retrieval layer is what makes this a system rather than a prompt. It finds the moments in your history that are actually similar to right now — same block phase, similar HRV state, similar environmental conditions — and injects those as context.

### Full Stack

| Layer | Tool | Role |
|---|---|---|
| Data ingestion — completed | Garmindb | Pulls FIT files, HRV, sleep, activity data from Garmin Connect into local database |
| Data ingestion — planned | TrainingPeaks API, TrainerRoad export, Zwift .zwo parser, Garmin workout API | Retrieves planned workout definitions across all platforms |
| Time-series storage | InfluxDB | HR, HRV, pace, power, sleep metrics over time |
| Plan/actual store | PostgreSQL | Structured plan vs actual pairs, execution scores, cross-training log |
| Analysis & modeling | JupyterLab + Python | CTL/ATL/TSB curves, HRV correlation, CSS extraction, environmental analysis |
| Vector storage | Chroma or Qdrant | Embeds historical training blocks and physiological responses for similarity search |
| LLM inference | Ollama (70B Q4) | Synthesis, planning, workout authoring — local with CPU offload for batch jobs |
| Orchestration | Python scripts | Connects layers — retrieves history, builds context, calls LLM, parses output |
| Output — Garmin | garth library | Pushes structured workouts to Garmin Connect — appears on watch overnight |
| Output — Zwift | .zwo file generation | Power-based indoor bike sessions dropped to Zwift workouts folder via network share |
| Season planner | Python + URL parser | Ingests event URLs, extracts dates and format, populates race calendar with A/B/C classification |
| Visualisation | Grafana | Fitness metrics dashboard, plan vs actual, HRV trends, FTP prediction advisory |

### Planning Operation Loop

**Monthly Generation — 1st of each month, or on block phase transition**

| Step | Action |
|---|---|
| Pull race calendar | Identify block phase, weeks to A-race, any B/C races in the window |
| Pull current fitness state | CTL/ATL/TSB, HRV trend, recent execution ratios |
| LLM generates full month | 4–5 weeks of sessions, day by day, with load progression arc, intensity distribution, taper positioning |
| Store as monthly plan | PostgreSQL — each session stored with planned TSS, IF, structure, and generation rationale |
| Push week 1 to devices | First week pushed to Garmin and Zwift immediately; subsequent weeks held in store |

**Weekly Review — Each Sunday at 3am**

| Step | Action |
|---|---|
| Score prior week execution | TSS ratio, IF delta, set completion across all sessions |
| Compare actual vs monthly plan | Did fatigue land where the model predicted? Any significant drift? |
| LLM reviews coming week | Adjusts session targets, reorders days if needed, modifies volumes |
| Push revised week to devices | Monday–Sunday sessions updated on Garmin and Zwift |
| Log review rationale | Why changes were made — builds explainability record |

**Morning Decision — Daily at 3am**

| Step | Action |
|---|---|
| Sync overnight Garmin data | HRV, sleep score, body battery, resting HR |
| Check today's planned session | Pull from monthly plan (as revised by weekly review) |
| Evaluate signals | HRV vs 7-day baseline, sleep quality, body battery, yesterday's execution |
| Generate alt if signals conflict | Alt workout written fresh — same sport, adjusted intensity or volume |
| Build morning readout | Primary session + alt + signal summary delivered to notification or dashboard |
| Athlete chooses | Selection logged — becomes a training data point for future weighting |
| Post-session | Completed activity auto-syncs; execution scored against whichever session was selected |

### Monthly Generation — Output Structure

The LLM generates the full month as a structured JSON document. Each session includes a primary and, for any session where fatigue signals might warrant it, a pre-authored alt. The alt is written at generation time — not computed reactively each morning — so it reflects the coaching intent for that point in the block, not just a generic intensity reduction.

At generation time the system does not yet know what HRV will look like on day 18. So the monthly generation writes a **conditional alt** for threshold and above sessions: what should this session look like if fatigue is elevated? The morning check then either surfaces or suppresses that alt based on actual signals.

```
Monthly Plan
├── Block rationale (why this phase, this load progression)
├── Week 1
│   ├── Monday: Swim threshold — primary + conditional alt
│   ├── Tuesday: Run Z2 — primary only (low intensity, alt rarely warranted)
│   ├── Wednesday: Bike threshold — primary + conditional alt
│   ├── Thursday: Strength + mobility — primary only
│   ├── Friday: Rest or easy swim
│   ├── Saturday: Long run — primary + conditional alt
│   └── Sunday: Long ride — primary + conditional alt
├── Week 2 (higher load)
├── Week 3 (peak load)
└── Week 4 (recovery — alts rarely needed, sessions already conservative)
```



### Why Model Size Matters

The synthesis task — holding the full plan in context, reasoning across all physiological variables simultaneously, catching conflicts like scheduling a long run the day after a hard swim when HRV trend is already suppressed — is where model size earns its place. A 13B model produces something that looks like a training plan. A 70B model actually reasons across variables coherently.

With the Steiger build (9900X + 64GB DDR5 + 7800 XT 16GB), a 70B Q4 model runs hybrid — 16GB on GPU, remainder in DDR5. Generation at 3–8 tokens/second is slow for chat but entirely fine for an overnight batch job generating a week of workouts.

---

## Planned Workout Retrieval

This is the layer that makes plan/actual comparison possible. Each platform stores planned sessions differently — the retrieval layer normalises them into a unified schema before analysis.

### Platform Sources

| Platform | What It Holds | Retrieval Method | Planned Session Coverage |
|---|---|---|---|
| TrainingPeaks | Full tri coaching plans — swim, bike, run, strength with coaching text | Official API (OAuth) or scrape | Best structured planned data available |
| TrainerRoad | Bike sessions with interval structure, power targets, TR coaching text | trainerroad-export (historical), Garmin sync (ongoing) | Bike only, excellent interval fidelity |
| Zwift | Power-based indoor bike sessions | .zwo XML from workouts folder | Bike only — parse FTP fractions back to watts |
| Garmin Connect | Planned workouts pushed by a coach or this system | garth GET /workout-service/workouts | All sports — used for system-authored sessions |
| Strava | Segment goals, event targets | Skip — low signal for planned sessions | Not worth the complexity |

### TrainingPeaks Planned Workout Retrieval

TrainingPeaks is the richest source of planned sessions for multi-sport athletes. It holds the coach-authored intent — not just power numbers but set structure, coaching cues, and session goals.

```python
# TrainingPeaks API — OAuth2 flow required
# Endpoint: GET /v1/workouts/{userId}?startDate=&endDate=

tp_session_schema = {
    "planned_date": "2027-06-10",
    "sport": "swim",
    "title": "CSS threshold set",
    "description": "...",          # coaching text — valuable
    "planned_duration_min": 60,
    "planned_tss": 65,
    "planned_if": 0.82,
    "structure": {
        "warmup": {"duration_min": 10, "intensity": "easy"},
        "sets": [
            {"repeat": 8, "distance_m": 100, "target_pace": "CSS", "rest_sec": 15}
        ],
        "cooldown": {"duration_min": 10}
    }
}
```

### Unified Planned Session Schema

All platform sources normalise to this schema before storage or comparison:

```python
planned_session = {
    "session_id": "uuid",
    "source_platform": "trainingpeaks | trainerroad | zwift | garmin | system",
    "planned_date": "2027-06-10",
    "sport": "swim | bike | run | strength | climb | yoga | mobility",
    "title": "...",
    "coaching_text": "...",          # original coaching intent text
    "planned_duration_min": 60,
    "planned_tss": 65,
    "planned_if": 0.82,             # null for non-power sports
    "planned_distance_m": None,
    "planned_elevation_m": None,    # for climbing sessions
    "structure": {
        "warmup": {...},
        "main_sets": [...],
        "cooldown": {...}
    },
    "targets": {
        "hr_zone": None,
        "power_zone": None,
        "pace_zone": None,
        "rpe_target": None
    }
}
```

---

## Plan vs Actual Comparison Engine

The comparison engine runs every morning against the previous day. It produces an execution score per session and an aggregate execution ratio for the day — both fed into the LLM context as structured inputs.

### Per-Session Metrics Compared

| Metric | How Measured | Significance |
|---|---|---|
| TSS delta | Actual TSS − Planned TSS | Positive = overcooked, negative = underdelivered |
| IF delta | Actual IF − Planned IF | Intensity accuracy — did you hit the right effort level |
| Duration delta | Actual duration − Planned duration | Volume compliance |
| Set completion | % of planned sets actually completed | Structural compliance — did you bail early |
| Zone distribution | Actual % time in each zone vs planned | Were you in the right zones or drifting |
| Pace accuracy (run) | Average pace vs target pace per interval | Run-specific execution quality |
| CSS accuracy (swim) | Average per-100m vs CSS target pace | Swim-specific execution quality |
| Power accuracy (bike) | Average power vs target watts per interval | Bike-specific — most precise measurement |
| Perceived vs planned RPE | Subjective effort vs intended effort | Where available, flags mismatch |

### Execution Score Calculation

```python
def calculate_execution_score(planned, actual):
    tss_ratio = actual["tss"] / planned["tss"] if planned["tss"] else None
    duration_ratio = actual["duration_min"] / planned["duration_min"]
    
    # Set completion from structured workout data
    planned_sets = sum(s["repeat"] for s in planned["structure"]["main_sets"])
    actual_sets = extract_actual_sets(actual["fit_data"])
    set_ratio = actual_sets / planned_sets if planned_sets else None
    
    execution_score = {
        "tss_ratio": tss_ratio,          # 0.94 = 94% of planned TSS
        "duration_ratio": duration_ratio,
        "set_completion": set_ratio,
        "if_delta": actual["if"] - planned["if"],
        "overall": weighted_average([tss_ratio, duration_ratio, set_ratio])
    }
    return execution_score
```

### Cross-Sport TSS Scoring

TSS is sport-specific and must be normalised before combining into daily load:

| Sport | TSS Basis | Formula Approach |
|---|---|---|
| Bike | Power vs FTP | Standard TSS = (duration_sec × NP × IF) / (FTP × 3600) × 100 |
| Run | Pace vs threshold pace via hrTSS | hrTSS using lactate threshold HR; or pace-based rTSS |
| Swim | Pace vs CSS | ssTSS (swim stress score) — CSS as threshold reference |
| Strength | Volume load proxy | Estimated sTSS: sets × reps × relative intensity — rough but trackable |
| Climbing | Duration + elevation + HR | ctTSS: hrTSS equivalent using sustained HR vs LTHR |
| Yoga / Mobility | Duration only | Low fixed coefficient — 20–30 TSS/hr cap, recovery modeled separately |

---

## Cross-Training Integration

Cross-training sessions are first-class citizens in the load model — not optional annotations. Strength training causes real fatigue. A hard climbing day before a long run matters. Yoga and mobility count as active recovery. The system models all of it.

### Session Types

| Type | Load Model | What Gets Tracked | Recovery Impact |
|---|---|---|---|
| Strength — gym | Volume load sTSS | Exercise log, sets, reps, perceived effort | Significant — 24–48hr muscle fatigue |
| Strength — body weight | Volume load sTSS (reduced) | As above, lower coefficient | Moderate |
| Climbing — outdoor | hrTSS + elevation gain | Duration, elevation, HR, grade | High — grip, upper body, sustained HR |
| Climbing — indoor | hrTSS | Duration, HR | Moderate — upper body dominant |
| Yoga — hot / vinyasa | Duration coefficient | Duration, session type | Low-moderate — counts as aerobic |
| Yoga — restorative | Near-zero load | Duration, session type | Positive recovery contribution |
| Mobility / stretching | Near-zero load | Duration | Positive recovery, not a load event |
| Swimming (recreational) | Reduced ssTSS | Duration, HR estimate | Low — flags to system as unstructured swim |

### Strength Session Logging Schema

```python
strength_session = {
    "date": "2027-06-10",
    "type": "strength",
    "subtype": "gym | bodyweight | climbing_gym | climbing_outdoor",
    "duration_min": 60,
    "planned_tss": 45,
    "actual_tss": 42,
    "exercises": [
        {
            "name": "Deadlift",
            "sets": 4,
            "reps": 5,
            "weight_kg": 100,
            "rpe": 8
        }
    ],
    "notes": "...",
    "recovery_flag": "standard | elevated | suppressed"
}
```

### How Cross-Training Affects Session Scheduling

The LLM receives cross-training load as part of the fatigue context. Scheduling logic must account for:

- Strength sessions the day before a hard bike or run → reduce intensity targets
- Climbing day before long run → flag elevated leg fatigue, consider swapping order or session type
- Yoga / mobility → positive modifier to recovery score, can reduce perceived ATL impact
- Consecutive strength + hard run/bike → system flags as high combined load, may substitute

---

## Season Planning

### Event URL Ingestion

Drop a race registration URL, event page, or results calendar link — the system extracts the event date, location, distance, and format. No manual calendar entry. The extracted data populates the race calendar and triggers classification prompts.

```python
def extract_event_from_url(url: str) -> dict:
    """
    Fetches URL content, passes to LLM to extract:
    - event name
    - event date
    - location
    - distance / format (Olympic, 70.3, marathon, etc.)
    - registration / cutoff dates if available
    """
    page_content = fetch_url(url)
    
    extraction_prompt = f"""
    Extract race event details from this page. Return JSON only.
    
    Required fields: name, date (ISO 8601), location, sport, format, distance_label
    Optional: elevation_gain_m, swim_distance_m, bike_distance_km, run_distance_km
    
    Page content:
    {page_content[:4000]}
    """
    
    return llm_extract(extraction_prompt)
```

Supported event sources include: World Triathlon, USA Triathlon, Ironman.com, HalfMarathons.net, RunSignUp, Ultrasignup, BikeReg, and any standard event page with structured dates. Unknown formats fall back to LLM text extraction.

### Race Calendar Schema

```python
race_event = {
    "event_id": "uuid",
    "name": "Boulder Ironman 70.3",
    "date": "2027-06-20",
    "location": "Boulder, CO",
    "sport": "triathlon",
    "format": "70.3",
    "priority": "A | B | C",          # set by athlete at classification
    "distances": {
        "swim_m": 1900,
        "bike_km": 90,
        "run_km": 21.1
    },
    "elevation_gain_m": 1200,         # relevant for climb / bike prep
    "source_url": "https://...",
    "extracted_at": "2026-10-01",
    "taper_start": "2027-06-06",      # calculated from priority and format
    "recovery_end": "2027-07-04"      # calculated from priority
}
```

### Priority Classification Logic

After URL extraction, the athlete sets A/B/C priority. The system then calculates taper and recovery windows automatically:

| Priority | Taper Length | Taper Type | Recovery After |
|---|---|---|---|
| A-race — peak event | 10–14 days | Full unload — volume and intensity reduced | Full protocol 1–2 weeks easy |
| B-race — training stimulus | 5–7 days | Protect the build — light volume, freshen legs | 3–5 days easy, back into block |
| C-race — fitness check | 2–3 days | Rest only — no structured taper | 1–2 days, normal training resumes |

### Multi-Format Year Scenarios

| Scenario | Planning Approach |
|---|---|
| Olympic tri season + fall marathon | Olympic build Jan–May, 4wk transition dropping bike intensity, marathon build Aug–Oct |
| Olympic tri season + Triple Bypass (July) | Tri base + climbing specificity May–June, bypass taper July, return to tri Aug |
| IM build year + Olympic B-races | IM volume as backbone, 1–2 Olympics as controlled intensity injections, short taper, race through |
| 70.3 as IM stepping stone | Olympic fitness base + IM volume introduction — fueling and pacing discipline test |
| IM year + endurance run B-race | Hard training race, no full taper, feeds run durability data into analysis layer |

---

## Race Format Library

The system maintains a race format library that drives fundamentally different periodisation models. Format determines session type distribution, intensity emphasis, taper protocol, and how B-races are treated within a build.

| Format | Status | Primary Demand | Typical Build Length |
|---|---|---|---|
| Olympic Triathlon | Current primary | High intensity, lactate tolerance, brick execution, ~2hr race effort | 12–16 weeks |
| Endurance Running | Current | Aerobic base, race pace economy, fueling, fatigue resistance | 16–20 weeks |
| Triple Bypass Ride | Planned | Sustained climbing power, 120+ miles, ~10,000ft gain, fueling over 6–9hrs | Specific 8–10wk bike block |
| 70.3 Half Ironman | Future — natural step | Bridge format — Olympic intensity with IM volume introduction | 16 weeks |
| Ironman | Future goal | All-day pacing discipline, fueling execution, swim-bike-run durability, 10–12hrs | 20–24 weeks |

### Olympic Racing Within an Ironman Build

Olympic distance races during an IM build are not conflicts — they are controlled intensity injections. When deep in IM volume accumulation at predominantly Z2, an Olympic race delivers a genuine 2-hour lactate effort impossible to replicate in training. The race does the intensity work without requiring a dedicated block.

The system distinguishes A-race (plan around it — full taper, full recovery) from B-race workout (plan through it — shorter taper, accept racing fatigued, absorb and continue). This classification is set at season planning and drives fundamentally different behaviour around every race date.

---

## Signal Importance Learning

### The Problem With Assuming HRV Is The Signal

HRV is the default readiness signal in endurance coaching because it has the strongest evidence base in population studies. But population averages mask enormous individual variation. For some athletes, HRV is a reliable daily performance predictor. For others, it is noisy, slow to respond, or dominated by non-training variables like alcohol, temperature, or chronically suppressed by medication or cycle phase — and some other signal does the actual predictive work.

A system that always weights HRV highest is making an assumption it should be testing. Once enough execution data exists, the system can answer the question empirically: **for this athlete, what morning signals actually predict how their sessions go?**

### What The System Learns

After approximately 60 sessions with matched morning biometrics and execution scores, the signal importance engine trains on the athlete's own data. It uses an ensemble of four methods — Pearson correlation, Spearman correlation, Random Forest permutation importance, and ElasticNet regularised regression — and averages their normalised outputs. Any single method is unreliable on a small dataset; four methods pointing the same direction is meaningful.

The output is a weight vector across every available signal. These weights replace the equal-weighted defaults in the morning conflict assessment. The morning readout then leads with whatever the data says matters most — not with HRV by default.

| Signal | What It Measures | Might Dominate For Athletes Who... |
|---|---|---|
| HRV vs 7-day baseline | Autonomic nervous system recovery | Respond clearly to training stress; no chronic HRV suppression |
| Sleep score | Garmin-assessed sleep quality | Are highly sleep-sensitive; sleep quality varies meaningfully |
| Sleep duration | Hours slept | Run a regular sleep debt; duration varies more than quality |
| Body battery | Garmin accumulated recovery estimate | Find body battery tracks subjective feel well |
| Resting HR vs baseline | Cardiovascular fatigue / illness | Experience elevated resting HR before poor sessions |
| Training Stress Balance | Cumulative fatigue (CTL − ATL) | Are load-sensitive; single-day signals matter less than trend |
| Prior day TSS ratio | How hard yesterday actually was | Carry yesterday's load into today's session noticeably |
| All-day stress score | Non-training stress load | Have stressful jobs or life periods that affect training |
| Cycle phase modifier | Hormonal variation | Experience consistent phase-linked performance variation |
| Respiration rate delta | Illness early indicator | Show elevated respiration before getting sick or underperforming |

### Per-Sport Weights

Signal importance is calculated separately by sport if enough per-sport data exists (minimum ~30 sessions per sport). HRV might predict swim performance well for an athlete but not bike performance. Sleep duration might be more predictive for long runs than short intervals. Where sport-specific weights exist, the system uses them — morning decision for a threshold run uses run weights, not the overall average.

### What Happens Before Enough Data Exists

Default weights based on published evidence are used until 60 sessions are available. The system is transparent about this — the morning readout and signal importance dashboard both show whether weights are learned or default. Defaults favour HRV and sleep because that is where the population evidence is strongest. As data accumulates, learned weights progressively replace defaults.

### Surprising Finding Surfacing

When the learned weights diverge significantly from defaults — HRV ranking 4th, TSB dominating, sleep duration outweighing sleep quality — the UI surfaces this explicitly as a finding with a plain-language explanation. The athlete should understand why the system stopped leading with HRV. That transparency is also what makes the athlete trust the adjusted behaviour.

### The Feedback Loop

Every morning readout choice is logged with the full conflict assessment snapshot — which signals drove the recommendation and at what intensity. When execution data arrives the next morning from Garmin, it is attached to that choice record. Over time this builds a dataset of: "the system flagged mild conflict driven by body battery and sleep, athlete chose primary, execution was 0.94." That dataset is exactly what the signal importance model trains on.

---

## FTP Prediction Layer

Garmin holds FTP as source of truth. This layer watches power data and flags when FTP has likely moved — predictive signal surfaced as an advisory note in the daily readout alongside workout adjustments. You confirm any change in Garmin.

| Signal | What It Means | System Action |
|---|---|---|
| 20min power PR in training | Functional threshold likely higher | Flag: suggest ramp test |
| Consistent threshold underperformance | FTP may be set too high | Flag: adjust targets down conservatively |
| 3+ week training gap | FTP decay likely | Flag: note optimistic estimate, reduce targets |
| Build block week 6–8, good compliance | Historical FTP gain window | Flag: prime time for test or hard effort |
| Heat-adjusted power below target | Environmental suppression, not fitness loss | No flag — context-aware, suppress alert |

---

## Hardware Alignment

| Hardware | Role | Capability |
|---|---|---|
| Current server — i5-7600 + Quadro RTX 5000 (16GB) | Phase A–B work | 13B comfortable, 70B Q4 possible with CPU offload — slow but workable for batch |
| Steiger — 9900X + 64GB DDR5 + 7800 XT (16GB) | Phase C–D primary | 70B Q4 hybrid — 16GB GPU + DDR5 overflow, 3–8 tok/s overnight batch |
| Workstation card — RTX A6000 Ada (48GB, future) | Fine-tuning | 34B QLoRA fine-tune on personal data — buy when Phase D complete, not before |

### The Fine-Tuning Opportunity

The most powerful eventual step is fine-tuning on your own historical plan/response pairs — teaching the model what worked for your specific physiology when you were in specific states. That dataset does not exist anywhere commercially. It is your edge.

---

*AI Coaching System — Architecture Reference · March 2026 · Back burner project, Priority 5*

---

## UI Layer

The system is self-hosted but not CLI-only. A lightweight web UI runs on the same server, accessible via browser on local network or through Tailscale remotely. It is the control surface for everything a human needs to touch — the pipeline itself stays headless and automated.

### UI Modules

| Module | Purpose | Key Interactions |
|---|---|---|
| **Season Builder** | Visual full-year planning canvas | Drag events onto calendar, set A/B/C priority, view generated block structure, adjust week count |
| **Athlete Profile** | Physiological parameters and health context | Thresholds (FTP, CSS, LTHR), medications, cycle tracking opt-in, injury notes |
| **Data Source Manager** | Connect and monitor all input platforms | OAuth flows for TrainingPeaks, Apple Health, Google Health; sync status; manual import |
| **Morning Readout** | Daily primary + alt session view | Signal summary, session cards, one-tap choice logging, notes field |
| **Plan Calendar** | Month view of generated plan | Primary sessions visible; alt indicator where one exists; executed/missed status |
| **Execution Dashboard** | Grafana-embedded plan vs actual | TSS curves, execution ratios by sport, HRV trend, FTP advisory |
| **Vacation Planner** | Declare travel windows and available equipment | Date range, location, equipment checklist, training intent (maintain/retreat/rest) |
| **Event Manager** | Race calendar — add, classify, edit events | URL drop for extraction, manual entry fallback, taper/recovery window preview |

### Tech Stack for UI

FastAPI backend with React frontend — no external cloud dependency, served from the same box as the coaching pipeline. Tailscale handles secure remote access without exposing ports.

```
Steiger Server
├── FastAPI backend — /api/* endpoints
│   ├── Reads from PostgreSQL (plan, athlete profile, race calendar)
│   ├── Reads from InfluxDB (fitness curves, HRV, sleep)
│   └── Triggers pipeline runs (monthly generation, weekly review, re-plan)
├── React frontend — served as static build
│   └── Accessible via browser on LAN or Tailscale
└── Grafana — embedded iframes for execution dashboard
```

### Season Builder Detail

The season builder is the most important UI surface. It translates what is currently a mental model — "I want to peak for this race, do that as a B, and have a recovery block after" — into the structured data object the pipeline acts on.

```
Season Builder View
┌─────────────────────────────────────────────────────────────┐
│  Jan    Feb    Mar    Apr    May    Jun    Jul    Aug    Sep  │
│                                                              │
│  [BASE BLOCK ──────────────] [BUILD ──────] [PEAK][T]        │
│                                      ▲               ▲       │
│                                  B-Race           A-Race     │
│                               (Olympic)           (70.3)     │
│                                                              │
│  Drag events · Set priority · View TSS arc · Generate Plan   │
└─────────────────────────────────────────────────────────────┘
```

Interactions:
- Drop a race URL or click **+ Add Event** → extraction flow → priority selection → taper windows auto-calculate
- Block structure generates from race calendar — athlete adjusts week count per phase
- TSS arc preview shows modeled CTL/ATL across season before committing
- **Generate Plan** triggers monthly generation for the first block; subsequent blocks queue

---

## Health Platform Integrations

### Why Apple Health and Google Health Connect

Garmin is the primary physiological record but it does not hold everything. Apple Health and Google Health Connect aggregate from sources Garmin cannot reach: menstrual cycle tracking apps, medication logs, CGM blood glucose, and cardiac device data. These platforms are the connective layer between the athlete's broader health ecosystem and this system.

| Data Type | Apple Health | Google Health Connect | Garmin |
|---|---|---|---|
| Menstrual cycle phase | ✓ HealthKit | ✓ Health Connect | Partial — Garmin Lily / manual only |
| Medication log | ✓ HealthKit | Partial | ✗ |
| HRV | ✓ Apple Watch | ✓ aggregated | ✓ primary source |
| Blood glucose / CGM | ✓ Dexcom, Libre | ✓ | ✗ |
| VO2max estimate | ✓ iPhone cardio | ✓ | ✓ primary source |
| Sleep | ✓ Apple Watch, Sleep Cycle | ✓ aggregated | ✓ primary source |
| Resting HR | ✓ | ✓ | ✓ primary source |

### Integration Architecture

Apple Health and Google Health Connect are phone-side APIs — they cannot be called directly from a server. A thin mobile companion reads from the health store and posts to the local server via Tailscale.

```
Phone (iOS or Android)
├── Apple Health / Google Health Connect
└── Companion (iOS Shortcut or Android Tasker profile)
    └── POST /api/health-data → Server via Tailscale
            ├── Menstrual cycle phase + predicted ovulation
            ├── Medication log entries
            └── Supplemental metrics not in Garmin
```

**iOS:** An iOS Shortcut with HealthKit read permission, scheduled daily. No App Store app required.
**Android:** Tasker profile reading Health Connect, posting to the server API.
**Privacy:** All health data posts to a self-hosted server the athlete controls. Nothing leaves the local network or Tailscale tunnel.

---

## Athlete Profile & Medical Context

The athlete profile is the persistent record of who this system is coaching. It holds physiological parameters the pipeline uses as inputs, plus medical and personal context that modifies how those inputs are interpreted.

### Profile Schema

```
Athlete Profile
├── Physiological parameters
│   ├── FTP (synced from Garmin — not manually set here)
│   ├── CSS (calculated quarterly from swim data)
│   ├── LTHR — run and bike separately
│   └── Weight, height, age
├── Health context (private, encrypted at rest)
│   ├── Menstrual cycle tracking — opted in / out
│   ├── Medications — name, class, known training effects
│   └── Medical notes — free text, athlete-authored
├── Equipment registry
│   └── Default equipment at home base (used to diff against vacation availability)
└── Training preferences
    ├── Preferred rest day
    ├── Morning / evening preference
    └── Max weekly hours cap
```

### Menstrual Cycle Integration

For athletes who experience a menstrual cycle, hormonal variation is a significant performance variable that every commercial tool ignores. Estrogen and progesterone fluctuate in ways that measurably affect perceived effort, thermoregulation, recovery rate, and HRV. Without cycle context, a suppressed HRV reading in the late luteal phase looks like overtraining. It is not.

| Phase | Approx Days | Hormonal State | Training Implications |
|---|---|---|---|
| Menstrual | 1–5 | Estrogen + progesterone low | Recovery emphasis; perceived effort elevated; soften intensity targets |
| Follicular | 6–13 | Estrogen rising | Increasing energy and recovery capacity; good window for progressive loading |
| Ovulation | ~14 | Estrogen peak, LH surge | Peak performance window; ideal for threshold tests, race simulations, key sessions |
| Early luteal | 15–21 | Progesterone rising | Maintain training load; core temp slightly elevated; increase hydration cues |
| Late luteal | 22–28 | Both hormones declining | HRV may suppress without fatigue cause; system annotates rather than flags |

The system does not hard-swap sessions based on cycle phase. It adjusts signal interpretation: a suppressed HRV in late luteal is annotated as expected hormonal context in the LLM prompt, not flagged as overtraining. The morning readout displays the cycle phase. Load targets soften slightly in menstrual and late luteal phases — the primary session remains available, the alt is there if needed.

**Data source:** Apple Health `HKCategoryTypeIdentifierMenstrualFlow` and `HKCategoryTypeIdentifierOvulationTestResult`, or Google Health Connect menstrual health categories. Clue, Flo, and Natural Cycles all write to these stores.

**Hormonal contraceptives:** Athletes on combined pill, implant, or hormonal IUD may have suppressed or absent natural hormonal variation. The profile captures contraceptive type and the cycle model is adjusted accordingly — no phase-based load variation applied.

### Medication-Aware Training

| Medication Class | Common Examples | Effect on Training | System Adjustment |
|---|---|---|---|
| Beta blockers | Metoprolol, Atenolol, Bisoprolol | Blunts HR — max HR suppressed 10–30bpm | Disable HR-zone targets; shift to RPE and power only |
| ACE inhibitors / ARBs | Lisinopril, Losartan | Mild effect; some reduced exercise capacity | Advisory flag only |
| Calcium channel blockers | Amlodipine, Diltiazem | Variable HR and BP suppression | Reduce HR ceiling targets; flag in LLM context |
| SSRIs / SNRIs | Sertraline, Venlafaxine | HRV often chronically suppressed | Calibrate HRV baseline with medication flag; suppress false overtraining alerts |
| Corticosteroids | Prednisone | Short course: elevated energy, appetite, BP; long course: tissue effects | Flag duration; load reduction if long course |
| Thyroid medications | Levothyroxine | Stable dose: minimal effect | Note if dose recently changed — performance may fluctuate during adjustment |
| Hormonal contraceptives | Combined pill, implant, hormonal IUD | Suppresses natural hormonal variation | Disable cycle phase model; use flat baseline |

**Implementation:** Medications entered in the Athlete Profile UI. Medication class maps to system flags injected into LLM context — primarily disabling HR-zone targets and annotating HRV baseline interpretation.

---

## Vacation & Travel Mode

Training does not stop during travel — it adapts. The system needs the travel window, the destination, and what equipment the athlete has access to. It generates a plan that is executable given those constraints without abandoning the block structure.

### Vacation Classification

| Type | Definition | System Behaviour |
|---|---|---|
| **Active vacation** | Travel but training continues — different equipment | Replans sessions to available equipment; preserves load where possible |
| **Rest vacation** | Deliberate deload — athlete is not training | Marks window as planned rest; models CTL decay as intentional |
| **Training retreat** | High-volume structured block at a specific facility | See Training Retreats section |

### Equipment Profiles

The athlete maintains a home equipment registry. When declaring a vacation, they select what is available at the destination. The plan generator constrains session types to available equipment.

**Vacation equipment checklist:**
- Road bike (travelling with it)
- Mountain bike (rented / at destination)
- Hotel gym — cardio machines only
- Hotel gym — weights available
- Pool access
- Open water access
- Running shoes (always — implicit)
- Resistance bands (packed)
- No equipment — running and bodyweight only

No KICKR and no pool means no structured swim or indoor bike — the plan shifts to running, hiking, outdoor cycling if the bike is there, and bodyweight strength.

### Environmental Adaptation During Travel

The destination's environment modifies session targets, not just session types:

- **Heat destination (>28°C):** Power targets on bike unchanged; run pace targets relaxed 5–10%; hydration cues added to session notes; morning sessions preferred
- **Altitude (>1,500m):** Intensity targets reduced 10–15% for days 1–3; HR will run high at equivalent effort — note this in session context; pace targets relaxed, power unchanged
- **Cold / wet:** No pace adjustment; layering and warm-up cues added; outdoor sessions swapped to indoor if temperature below threshold athlete sets in profile

---

## Training Retreats

A training retreat is a structured high-volume block at a specific facility — a cycling camp in Girona, a swim camp, an altitude block in Boulder, a tri resort in Lanzarote. The athlete is going somewhere specifically to train more and better than they can at home.

### Retreat Types

| Type | Examples | Key Variables |
|---|---|---|
| Cycling camp | Mallorca, Girona, Tenerife | Volume hrs/day, climbing specificity, group ride dynamics |
| Swim camp | Masters or club camp | Pool quality, coaching on-site, twice-daily sessions |
| Altitude camp | Boulder, Font Romeu, St Moritz | Altitude (m), acclimatisation protocol, reduced intensity days 1–3 |
| Triathlon resort | Lanzarote Club La Santa, Alpe d'Huez | Pool + bike + run; multi-sport daily structure |
| Running retreat | Trail camp, marathon group | Terrain, daily mileage cap, recovery facilities |

### How Retreats Affect the Monthly Plan

- **Before retreat:** slight taper into it — arrive fresh, not depleted from the prior week
- **During retreat:** monthly generator creates a retreat-specific block using daily structure, available sports, and target TSS. Higher daily volume; intensity adjusted for altitude and block role
- **After retreat:** post-camp ATL spike is real and planned. The week following a hard camp is modeled as a deliberate recovery week — system does not alarm at the fitness drop, it expected it
- **Coaching on-site flag:** if the retreat has a coach directing sessions, system marks those days as externally directed and does not push conflicting sessions to Garmin — it logs and scores whatever comes back from Garmin instead

---

