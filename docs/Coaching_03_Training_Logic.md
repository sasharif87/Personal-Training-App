# AI Coaching System — Training & Coaching Logic

**Race Formats · Signal Intelligence · Session Types · Athlete Wellbeing**

---

## Race Format Library

Format determines everything downstream: session type distribution, intensity emphasis, taper protocol, and how B-races are treated within a build. The system maintains a format library that drives fundamentally different periodisation models per event type.

| Format | Status | Primary Demand | Typical Build Length |
|---|---|---|---|
| Olympic Triathlon | Current primary | High intensity, lactate tolerance, brick execution, ~2hr race effort | 12–16 weeks |
| Endurance Running | Current | Aerobic base, race pace economy, fueling, fatigue resistance | 16–20 weeks |
| Triple Bypass Ride | Planned | Sustained climbing power, 120+ miles, ~10,000ft gain, fueling over 6–9hrs | 8–10wk specific bike block |
| 70.3 Half Ironman | Future — natural step | Bridge format — Olympic intensity with IM volume introduction | 16 weeks |
| Ironman | Future goal | All-day pacing discipline, fueling execution, swim-bike-run durability, 10–12hrs | 20–24 weeks |

### A-Race vs B-Race Treatment

| Treatment | Taper | Execution Target | Recovery After |
|---|---|---|---|
| A-race — peak event | 10–14 days, full unload | Peak performance | Full protocol 1–2 weeks easy |
| B-race — training stimulus | 5–7 days, protect the build | Hard training effort, not peak | 3–5 days easy, back into build |
| C-race — fitness check | 2–3 days rest only | Data point — do not race to limits | 1–2 days, normal training resumes |

### Olympic Racing Within an Ironman Build

Olympic distance races during an IM build are not conflicts — they are controlled intensity injections. When deep in IM volume accumulation at predominantly Z2, an Olympic race delivers a genuine 2-hour lactate effort impossible to replicate in training. The race does the intensity work without requiring a dedicated block.

### Multi-Format Year Scenarios

| Scenario | Planning Approach |
|---|---|
| Olympic tri season + fall marathon | Olympic build Jan–May, 4wk transition, marathon build Aug–Oct |
| Olympic tri + Triple Bypass (July) | Tri base + climbing specificity May–June, bypass taper July, return to tri Aug |
| IM build + Olympic B-races | IM volume as backbone, Olympics as controlled intensity injections |
| IM year + endurance run B-race | Hard training race, no full taper, feeds run durability data into analysis |

---

## Season Planning

### Event URL Ingestion

Drop a race registration URL — the system extracts event date, location, distance, and format. No manual calendar entry. Supports Ironman.com, World Triathlon, USA Triathlon, RunSignUp, BikeReg, Ultrasignup. Unknown formats fall back to LLM text extraction.

### Priority Classification & Taper Windows

| Priority | Taper Days | Recovery Days |
|---|---|---|
| A + Ironman | 14 | 21 |
| A + 70.3 | 12 | 14 |
| A + Olympic | 10 | 7 |
| A + Marathon | 14 | 14 |
| B + any format | 5–7 | 3–5 |
| C + any | 2 | 1 |

Race calendar exports to `race_calendar.md` automatically on every add/update/reclassify.

---

## Signal Importance Learning

### The Problem With Assuming HRV Is The Signal

HRV gets default priority in endurance coaching tools because population evidence supports it. But population averages mask individual variation. For some athletes HRV is a reliable daily predictor. For others it is chronically suppressed by medication or cycle phase, or simply not the signal that tracks with how their sessions actually go.

The system tests this empirically rather than assuming it. After ~60 sessions with matched morning biometrics and execution scores, it trains a signal importance model on the athlete's own data and replaces default weightings with learned ones. The morning readout leads with whatever the data says matters most.

### Available Signals

| Signal | What It Measures | Might Dominate For Athletes Who... |
|---|---|---|
| HRV vs 7-day baseline | Autonomic nervous system recovery | Respond clearly to training stress; no chronic suppression |
| Sleep score | Garmin-assessed sleep quality | Are highly sleep-sensitive |
| Sleep duration | Hours slept | Run regular sleep debt |
| Deep sleep hours | Physical repair quality | Have variable sleep architecture despite normal total duration |
| Body battery | Garmin accumulated recovery | Find body battery tracks subjective feel well |
| Resting HR vs baseline | Cardiovascular fatigue / illness | Experience elevated resting HR before poor sessions |
| Training Stress Balance | Cumulative fatigue (CTL − ATL) | Are load-sensitive; single-day signals matter less than trend |
| Prior day TSS ratio | How hard yesterday actually was | Carry yesterday's load noticeably |
| Rolling 7-day TSS ratio | Execution trend this week | Accumulate fatigue gradually across the week |
| All-day stress score | Non-training stress | Have stressful work or life periods that affect training |
| Cycle phase modifier | Hormonal variation | Experience consistent phase-linked performance variation |
| Respiration rate delta | Illness early indicator | Show elevated respiration before getting sick |
| Skin temp delta | Fever / illness proxy | Garmin devices that capture skin temp |

### Learning Method

Ensemble of four approaches: Pearson correlation, Spearman correlation, Random Forest permutation importance, and ElasticNet regularised regression. Each normalised to sum = 1, then averaged. Any single method is unreliable on a small dataset — four methods pointing the same direction is meaningful.

### Per-Sport Weights

Calculated separately per sport where ≥30 sessions exist. HRV may predict swim execution well but not bike. Sleep duration may matter more for long runs than short intervals.

### Before Enough Data Exists

Default weights (HRV and sleep weighted highest, reflecting population evidence) used until 60 sessions are available. The UI shows whether weights are learned or default — transparency about the data source is what builds trust in the adjusted behaviour.

### Feedback Loop

Every morning readout choice logged with the full biometric snapshot. Next-day execution score attached the following morning after Garmin sync. This dataset is what the importance model trains on — passively, just from using the system.

---

## FTP Prediction Layer

Garmin holds FTP as source of truth. This layer watches power data and surfaces advisory flags when FTP has likely moved. The athlete confirms any change in Garmin — the system never updates FTP automatically.

| Signal | What It Means | System Action |
|---|---|---|
| 20min power PR in training | Threshold likely higher | Flag: suggest ramp test |
| Consistent threshold underperformance | FTP may be set too high | Flag: adjust targets down conservatively |
| 3+ week training gap | FTP decay likely | Flag: estimate may be optimistic |
| Build block week 6–8, good compliance | Historical FTP gain window | Flag: prime time for test or hard effort |
| Heat-adjusted power below target | Environmental suppression, not fitness loss | No flag — context-aware, suppress alert |

---

## Cross-Training Integration

Cross-training sessions are first-class citizens in the load model — not optional annotations. Strength training causes real fatigue. A hard climbing day before a long run matters. Yoga and mobility count as active recovery. The system models all of it.

### Session Types & TSS

| Type | TSS Basis | Recovery Impact |
|---|---|---|
| Strength — gym | Volume load proxy: sets × reps × relative intensity | Significant — 24–48hr muscle fatigue |
| Strength — bodyweight | Reduced volume load coefficient | Moderate |
| Climbing — outdoor | hrTSS + elevation bonus | High — grip, upper body, sustained HR |
| Climbing — indoor | hrTSS | Moderate — upper body dominant |
| Yoga — hot / vinyasa | Duration coefficient ~0.5 TSS/min | Low-moderate |
| Yoga — restorative | Near-zero coefficient | Positive recovery contribution |
| Mobility / stretching | ~0.02 TSS/min | Positive recovery — not a load event |

### How Cross-Training Affects Scheduling

Strength sessions the day before a hard bike or run → reduce intensity targets. Climbing day before long run → flag elevated leg fatigue, consider reordering. Yoga / mobility → positive modifier to recovery score. Consecutive hard strength + hard run/bike → system flags as high combined load, may substitute in monthly generation.

---

## Brick Session Specifics

The transition from cycling to running involves a neuromuscular challenge — shifting from hip-dominant movement to full kinetic chain recruitment while blood is still pooled in cycling-specific muscle groups. The first 1–5km of a run off the bike behaves differently from a standalone run at equivalent effort. The system models this explicitly in both prescription and scoring.

### Session Types

| Type | Structure | Target | Block Position |
|---|---|---|---|
| Short brick | 45–60min bike → 10–20min run at race pace | Neuromuscular adaptation; T2 practice | Early-mid build |
| Long brick | 2–3hr bike → 30–60min run at race pace | Race simulation; pacing discipline | Peak build |
| Race-sim brick | Full race-distance bike → full race-distance run | Confidence and pacing validation | 3–4 weeks from A-race |

### Brick Run Pace Targets

The opening 5-minute pace target is **explicitly slower** than steady state — this is correct coaching, not a failure. Expected leg heaviness modifier: ~6% slower in the opening 5 minutes for standard bricks; ~9–12% after very long bikes or high TSS. Session notes distinguish opening pace from body-of-run pace. Prescribing standalone run pace for the opening of a brick sets the athlete up to overcook and fade.

### Brick Execution Scoring

Bike segment (power vs target), T2 time, run opening 5min pace vs adjusted target, run steady-state pace, run fade percentage (final third vs middle third). A run fade >6% is flagged — suggests the run was started too fast.

---

## Open Water Swim Specifics

### Key Differences From Pool

| Variable | Pool | Open Water |
|---|---|---|
| Sighting effort | None | 4–8% energy overhead; disrupts stroke rhythm |
| Drafting | None (competition) | Pack swimming — significant energy saving |
| Wetsuit | Never (competition) | Buoyancy changes body position and stroke |
| Pacing reference | Clock + lane markers | GPS unreliable; effort-based pacing required |
| Anxiety load | Low | Elevated for many athletes — affects HR and pacing |

### Open Water Session Types

| Session | Purpose |
|---|---|
| Sighting drill | Reduce sighting energy cost; buoy navigation practice |
| Wetsuit acclimatisation | First few sessions of season; note HR and perceived effort vs pool |
| Race-sim open water | Full-intensity race-pace effort at approximate race distance |
| Pack swimming practice | Drafting efficiency and contact comfort — needs training partners |
| Cold water acclimatisation | Gradual exposure; note water temp and cold shock response |

### Open Water Logging

Water temperature, wetsuit used, sighting frequency, conditions (flat/choppy/rough) logged per session. Builds a personal open water performance model over time: how much does chop affect pace? How does the wetsuit change perceived effort vs pool?

---

## Injury Tracking & RPE / Wellness Logging

### Post-Session Log

After each session the athlete optionally fills in (30 seconds, low-friction):

```
RPE (1–10)
Leg feel (1–5: dead → great)
Motivation going in (1–5)
Any pain? yes/no
  → if yes: body map tap, type (sharp/dull/tight/sore), severity 1–10, onset timing
Notes (free text, optional)
Fueling actual: what did you take and how much
```

### Injury Risk Signals

| Signal | Indicator | System Action |
|---|---|---|
| Acute:chronic workload ratio > 1.5 | Rapid load spike | Flag; reduce coming week volume |
| Run volume increase > 10% week-on-week | Classical overuse progression | Cap at 10% in plan generation |
| Recurring niggle at same location 3+ sessions | Soft tissue injury developing | Alert; suggest sport substitution; flag for medical review |
| RPE consistently higher than expected for TSS | Hidden fatigue or illness | Elevate in morning signal context |
| Sudden RPE spike on easy session | Illness onset | Escalate HRV and resting HR monitoring |
| Asymmetric effort reports | Compensation pattern | Note in context; suggest mobility focus |

### Injury History Model

System builds a personal risk profile from history: which body parts have been injured, what load patterns preceded each injury (typically detectable 2–4 weeks prior), how long recovery took, whether seasonal or block-phase recurrence patterns exist. This is injected into monthly generation context — a history of left Achilles issues at high run volume in the build phase means that block is written more conservatively on run volume.

---

## Race Result Ingestion & Post-Race Analysis

### What Gets Captured

For every race: overall time, placement (optional), splits by discipline, bike power data, run pace data, HR across disciplines, actual fueling executed, conditions (temp, wind, water temp, wetsuit legal), post-race notes, subjective feel 1–10 per discipline.

### Post-Race Analysis

**Pacing analysis:** Did power/pace hold or fade? A 10% run fade in the second half means the run was started too fast — next build's pacing targets adjust accordingly.

**Discipline comparison:** Which segment underperformed relative to training fitness? Swim split slower than CSS-predicted? Bike power below FTP-predicted race power? Each flags a specific training or execution gap.

**CTL correlation:** Over multiple races the system builds the athlete's personal optimal CTL range per format — not population average, their number.

**Fueling post-mortem:** If a wall was hit, when did it happen relative to projected glycogen depletion? Was the fueling plan followed? GI issues recorded?

**Feeds RAG:** Race results become high-value embeddings in the vector database. Future planning can retrieve: "last two times you entered a 70.3 with CTL >75 and TSB between -5 and +5, bike split was within 3% of target."

---

## Overreaching & NFOR Detection

Single-day readiness covers acute signals. Non-functional overreaching (NFOR) builds over 2–4 weeks and does not resolve with one easy day. A separate monitoring layer watches the medium-term trend.

### Detection Signals

| Signal | Threshold | Window |
|---|---|---|
| HRV trend | 7-day mean > 10% below 28-day mean | 10+ consecutive days |
| Execution ratio | Rolling 7-day < 0.80 without planned deload | 1 week |
| RPE drift | Average RPE rising for equivalent TSS sessions | 2 weeks |
| Performance plateau | No improvement in key session metrics | 3+ weeks of build |
| Sleep quality | Persistent score below 0.60 | 10 days |
| Resting HR elevation | > 5% above 28-day mean | 7+ consecutive days |

Two or more signals simultaneously triggers a NFOR alert — surfaced prominently in UI and injected as high-priority flag in the next generation context.

### System Response

1. UI alert — explicit, not buried in morning readout
2. Monthly replan triggered — current block paused, 1–2 week recovery block inserted (50–60% volume, intensity almost entirely removed, daily mobility added)
3. Monitoring continues — watches for HRV and execution normalisation before resuming
4. Historical context — if athlete has experienced NFOR before, notes how long recovery took

### NFOR vs Life Stress

If TSS has been normal or low while signals are suppressed, the likely cause is external — work, illness, travel, poor sleep hygiene. Response is different: maintain training structure (often protective) rather than imposing a training recovery block. The system checks load context before acting.

---

## Testing Protocols

The system flags when a test is warranted, generates the protocol, and ingests the result.

### FTP Protocols

| Protocol | Structure | FTP Estimate |
|---|---|---|
| 20-minute test | Warmup → 5min maximal → 5min easy → 20min maximal → cooldown | 95% of 20min average power |
| Ramp test | 1min steps increasing ~20W until failure | 75% of peak 1min power |
| 8-minute test | Two 8min maximal efforts with 10min recovery | 90% of best 8min power |

Generated simultaneously as Zwift .zwo and Garmin structured workout. After completion, system reads power data, calculates FTP estimate, presents confirmation prompt before updating Garmin.

### CSS Protocol

```
400m warmup → 4×50m activation at race pace → 5min rest
→ 400m maximal effort (record time)
→ 10min rest  
→ 200m maximal effort (record time)

CSS = (400 − 200) / (T400 − T200)  →  expressed as sec/100m
```

### LTHR Protocol

30-minute maximal sustained run effort on flat course or treadmill. Average HR in final 20 minutes ≈ LTHR. Generated as Garmin structured workout with lap alert at 10 minutes.

---

## Vacation & Travel Mode

### Classification

| Type | Definition | System Behaviour |
|---|---|---|
| **Active vacation** | Travel, training continues with different equipment | Replans sessions to available equipment; preserves load where possible |
| **Rest vacation** | Deliberate deload — not training | Marks as planned rest; models CTL decay as intentional |
| **Training retreat** | High-volume block at specific facility | See Training Retreats below |

### Equipment Constraints

The athlete selects what is available at the destination. The plan generator constrains session types accordingly. No KICKR and no pool = no structured swim or indoor bike. Plan shifts to running, outdoor cycling, bodyweight strength.

**Equipment checklist:** road bike (travelling with) · mountain bike (rented) · hotel gym cardio only · hotel gym full weights · pool access · open water access · resistance bands · running shoes (always implicit)

### Environmental Target Adaptation

| Condition | Effect | Adaptation |
|---|---|---|
| > 28°C destination | Heat stress | Run pace relaxed 5–10%; morning sessions preferred; hydration cues in notes |
| > 35°C | Health risk | Substitute outdoor session with indoor equivalent or reschedule |
| Altitude > 1,500m | Reduced O₂ | Intensity targets reduced 10–15% days 1–3; HR elevated — note in context; power unchanged |
| Cold / wet | Comfort risk | Warmup cues; outdoor swapped to indoor below athlete's set temperature threshold |

---

## Training Retreats

### Retreat Types

| Type | Examples | Key Variables |
|---|---|---|
| Cycling camp | Mallorca, Girona, Tenerife | Volume hrs/day, climbing specificity, group ride dynamics |
| Swim camp | Masters or club camp | Pool quality, coaching on-site, twice-daily sessions |
| Altitude camp | Boulder, Font Romeu, St Moritz | Altitude (m), acclimatisation protocol, days 1–3 reduced intensity |
| Triathlon resort | Lanzarote Club La Santa, Alpe d'Huez | Full facility — pool, bike, run; multi-sport daily structure |
| Running retreat | Trail running camp, marathon group | Terrain, daily mileage, recovery facilities |

### How Retreats Affect the Plan

- **Before:** 3-day arrival taper — arrive fresh, not depleted
- **During:** retreat-specific block using daily structure, available sports, target TSS; altitude protocol if altitude ≥ 1,500m
- **After:** post-camp ATL spike is planned; the following week is a deliberate recovery week — system does not alarm at the fitness drop
- **Coached on-site:** if a coach is directing sessions, system suppresses Garmin pushes for those days and logs/scores whatever comes back from Garmin instead

---

## Sleep Staging Integration

Beyond sleep score, staging data is more informative for training recovery. Deep sleep is where physical repair occurs (GH secretion, tissue repair, glycogen resynthesis). REM is where motor learning consolidation happens — relevant for technique-focused sessions.

| Stage | Recovery Role | Flag If |
|---|---|---|
| Deep sleep | Physical repair, GH secretion, immune function | < 1hr/night for 3+ consecutive nights |
| REM sleep | Cognitive function, motor learning (swim technique) | < 90min/night |
| Wake time | Sleep fragmentation | > 30min total wake time |

Deep sleep hours are tracked as an independent signal in the signal importance model — separate from total sleep score and duration, since they can diverge meaningfully.

---

*AI Coaching System — Training & Coaching Logic · March 2026 *
