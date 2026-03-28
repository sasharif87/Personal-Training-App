**AI Coaching System**

Architecture Reference

Self-Hosted  •  Multi-Sport  •  HRV-Informed  •  Physiologically Personal

# **Vision & Purpose**

A self-hosted AI coaching system that generates, delivers, and continuously refines triathlon and endurance training plans across swim, bike, and run — informed by 10 years of personal physiological data, HRV, sleep, environmental variables, and race format context. Not a commercial product. Not a generic plan. A system trained on your data that knows your physiology.

The core capability commercial tools lack: cross-sport load accounting, HRV as a leading indicator rather than lagging response, environmental modeling, and genuine workout authoring — not intensity adjustment of pre-built sessions.

# **Why This Exceeds Commercial Tools**

## **What Trainer Road AI Actually Does**

Trainer Road Adaptive Training is a rule-based system with ML on top. It watches workout compliance, compares power output to targets, and nudges intensity up or down. Reactive, not predictive. Bike only. No swim stress. No HRV prediction. No environmental modeling.

| Capability | Commercial Tools | This System |
| :---- | :---- | :---- |
| Multi-sport load accounting | Bike only (Trainer Road) | Swim \+ Run \+ Bike combined TRIMP stress |
| HRV integration | Lagging — adjusts after failure | Leading — adjusts before you dig a hole |
| Environmental factors | Not modeled | Wind, heat, altitude inform session targets |
| Personalisation basis | Population averages | 10 years of your specific physiology |
| Workout authoring | Adjusts pre-built sessions | Writes sessions from scratch per context |
| Sleep integration | Manual input only | Automated via Garmin overnight data |
| Swim specificity | None | CSS-based zones, set-level prescription |
| Race format awareness | Generic plans | Olympic, IM, endurance run, Triple Bypass models |

## **The Swim Gap**

Every commercial tool underestimates swim stress. Proper swim load modeling requires CSS (Critical Swim Speed) as the functional threshold equivalent, pace zones derived from CSS not HR, stroke rate and DPS where Garmin captures it, and recognition that swim fatigue has a different recovery curve — upper body dominant, different systemic load profile to running.

# **System Architecture**

## **The Context Window Problem**

A full year plan — 9 workouts x 6 days x 52 weeks — plus 10 years of historical data cannot fit in any LLM context window. The system needs a retrieval layer that pulls relevant historical data into context intelligently rather than dumping everything. This is RAG: Retrieval Augmented Generation.

  The retrieval layer is what makes this a system rather than a prompt. It finds the moments in your history that are actually similar to right now — same block phase, similar HRV state, similar environmental conditions — and injects those as context.

## **Full Stack**

| Layer | Tool | Role |
| :---- | :---- | :---- |
| Data ingestion | Garmindb | Pulls FIT files, HRV, sleep, activity data from Garmin Connect into local database |
| Time-series storage | InfluxDB | HR, HRV, pace, power, sleep metrics over time — already in planned stack |
| Analysis & modeling | JupyterLab \+ Python | CTL/ATL/TSB curves, HRV correlation, CSS extraction, environmental analysis |
| Vector storage | Chroma or Qdrant | Embeds historical training blocks and physiological responses for similarity search |
| LLM inference | Ollama (70B Q4) | Synthesis, planning, workout authoring — local with CPU offload for batch jobs |
| Orchestration | Python scripts | Connects layers — retrieves history, builds context, calls LLM, parses output |
| Output — Garmin | garth library | Pushes structured workouts to Garmin Connect — appears on watch overnight |
| Output — Zwift | .zwo file generation | Power-based indoor bike sessions dropped to Zwift workouts folder via network share |
| Visualisation | Grafana | Fitness metrics dashboard, plan vs actual, HRV trends, FTP prediction advisory |

## **Daily Operation Loop**

| Time | Event |
| :---- | :---- |
| Overnight | Garmindb pulls previous day completed workouts, HRV, sleep data from Garmin Connect |
| Early morning | Analysis layer calculates current fitness state — CTL/ATL/TSB, HRV 7-day trend, fatigue score |
| Morning | LLM reviews plan vs actual, checks block position, adjusts forward, generates sessions |
| Morning | Python pushes run/swim/brick sessions to Garmin Connect via garth — on watch by wake-up |
| Morning | Python writes bike session as .zwo to Zwift workouts folder via network share or Syncthing |
| Training | Watch guides run/swim with live targets; Zwift loads structured bike workout |
| Post-session | Completed activities auto-sync to Garmin Connect |
| Next morning | Cycle repeats — system reviews execution and adjusts forward |

## **Why Model Size Matters**

The synthesis task — holding the full plan in context, reasoning across all physiological variables simultaneously, catching conflicts like scheduling a long run the day after a hard swim when HRV trend is already suppressed — is where model size earns its place. A 13B model produces something that looks like a training plan. A 70B model actually reasons across variables coherently.

With the Steiger build (9900X \+ 64GB DDR5 \+ 7800 XT 16GB), a 70B Q4 model runs hybrid — 16GB on GPU, remainder in DDR5. Generation at 3-8 tokens/second is slow for chat but entirely fine for an overnight batch job generating a week of workouts.

# **Data Sources**

## **Primary — Garmin Connect**

Garmin is the backbone. Captures HR, HRV (morning readiness), sleep, stress, body battery, GPS, pace, power, swim metrics, and syncs from all devices including Wahoo. FTP stored in Garmin Connect and pulled directly — no manual input. Everything else is either a subset or a duplicate.

| Source | Value | Decision |
| :---- | :---- | :---- |
| Garmin Connect | Primary — complete physiological record across all sports | Core pipeline via Garmindb |
| Trainer Road | Bike workout library — planned intent plus coaching text | trainerroad-export for history; ongoing sync via Garmin |
| Garmin FIT run workouts | Plan/actual pairing for coach-prescribed run sessions | Pulled automatically via Garmindb |
| TrainingPeaks | High value if coached history with plan/actual annotations exists | One-time export if relevant history there |
| Wahoo (ELEMNT/KICKR) | Low — data already in Garmin via auto-sync | Skip as live source |
| Strava | Low — subset of Garmin with social layer | Skip, adds complexity without signal |
| Zwift | Completed rides sync to Garmin automatically | Output target only, not an input source |

## **Output — Writing Back to Devices**

**Garmin Connect (Run, Swim, Brick, Strength)**

Garmin accepts structured workout definitions via Connect API — a JSON payload that appears in the calendar and syncs to the watch. The garth library handles authenticated API access. Sessions arrive on the watch overnight with guided targets: pace zones, HR zones, interval countdowns. Risk: Garmin Connect API is unofficial and has broken periodically with authentication changes. Maintainable but worth monitoring.

**Zwift (Indoor Bike)**

Zwift uses .zwo XML files with power targets as FTP fractions. Simple format, well documented. No import API — files are dropped into the local Zwift workouts folder and appear on next launch. Server writes directly to the Zwift machine via SMB network share or Syncthing. With Tailscale in the stack, this works across any network.

Warmup → IntervalsT (Repeat, OnDuration/OffDuration, OnPower/OffPower) → Cooldown

# **Race Format Library**

The system maintains a race format library that drives fundamentally different periodisation models. Format determines session type distribution, intensity emphasis, taper protocol, and how B-races are treated within a build.

| Format | Status | Primary Demand | Typical Build Length |
| :---- | :---- | :---- | :---- |
| Olympic Triathlon | Current primary | High intensity, lactate tolerance, brick execution, \~2hr race effort | 12-16 weeks |
| Endurance Running | Current | Aerobic base, race pace economy, fueling, fatigue resistance | 16-20 weeks |
| Triple Bypass Ride | Planned | Sustained climbing power, 120+ miles, \~10,000ft gain, fueling over 6-9hrs | Specific 8-10wk bike block |
| 70.3 Half Ironman | Future — natural step | Bridge format — Olympic intensity with IM volume introduction | 16 weeks |
| Ironman | Future goal | All-day pacing discipline, fueling execution, swim-bike-run durability, 10-12hrs | 20-24 weeks |

## **Olympic Racing Within an Ironman Build**

Olympic distance races during an IM build are not conflicts — they are controlled intensity injections. When deep in IM volume accumulation at predominantly Z2, an Olympic race delivers a genuine 2-hour lactate effort impossible to replicate in training. The race does the intensity work without requiring a dedicated block.

  The system distinguishes A-race (plan around it — full taper, full recovery) from B-race workout (plan through it — shorter taper, accept racing fatigued, absorb and continue). This classification is set at season planning and drives fundamentally different behaviour around every race date.

| Race Treatment | Taper | Execution Target | Recovery After |
| :---- | :---- | :---- | :---- |
| A-race — peak event | 10-14 days, full unload | Peak performance | Full protocol — 1-2 weeks easy |
| B-race — training stimulus | 5-7 days, protect the build | Hard training effort, not peak | 3-5 days easy, back into build |
| C-race — fitness check | 2-3 days rest only | Data point — do not race to limits | 1-2 days, normal training resumes |

## **Multi-Format Year Scenarios**

| Scenario | Planning Approach |
| :---- | :---- |
| Olympic tri season \+ fall marathon | Olympic build Jan-May, 4wk transition dropping bike intensity, marathon build Aug-Oct |
| Olympic tri season \+ Triple Bypass (July) | Tri base \+ climbing specificity May-June, bypass taper July, return to tri Aug |
| IM build year \+ Olympic B-races | IM volume as backbone, 1-2 Olympics as controlled intensity injections, short taper, race through |
| 70.3 as IM stepping stone | Olympic fitness base \+ IM volume introduction — fueling and pacing discipline test |
| IM year \+ endurance run B-race | Hard training race, no full taper, feeds run durability data into analysis layer |

# **FTP Prediction Layer**

  Garmin holds FTP as source of truth. This layer watches power data and flags when FTP has likely moved — predictive signal surfaced as an advisory note in the daily readout alongside workout adjustments. You confirm any change in Garmin.

| Signal | What It Means | System Action |
| :---- | :---- | :---- |
| 20min power PR in training | Functional threshold likely higher | Flag: suggest ramp test |
| Consistent threshold underperformance | FTP may be set too high | Flag: adjust targets down conservatively |
| 3+ week training gap | FTP decay likely | Flag: note optimistic estimate, reduce targets |
| Build block week 6-8, good compliance | Historical FTP gain window | Flag: prime time for test or hard effort |
| Heat-adjusted power below target | Environmental suppression, not fitness loss | No flag — context-aware, suppress alert |

# **Hardware Alignment**

| Hardware | Role | Capability |
| :---- | :---- | :---- |
| Current server — i5-7600 \+ Quadro RTX 5000 (16GB) | Phase A-B work | 13B comfortable, 70B Q4 possible with CPU offload — slow but workable for batch |
| Steiger — 9900X \+ 64GB DDR5 \+ 7800 XT (16GB) | Phase C-D primary | 70B Q4 hybrid — 16GB GPU \+ DDR5 overflow, 3-8 tok/s overnight batch |
| Workstation card — RTX A6000 Ada (48GB, future) | Fine-tuning | 34B QLoRA fine-tune on personal data — buy when Phase D complete, not before |

## **The Fine-Tuning Opportunity**

The most powerful eventual step is fine-tuning on your own historical plan/response pairs — teaching the model what worked for your specific physiology when you were in specific states. That dataset does not exist anywhere commercially. It is your edge.

| Scenario | VRAM | Hardware |
| :---- | :---- | :---- |
| 7B QLoRA fine-tune | \~20GB | Tight on 7800 XT — workable with small batch |
| 13B QLoRA fine-tune | \~32GB | Needs workstation card |
| 34B QLoRA fine-tune | \~60GB | RTX A6000 Ada 48GB |
| 70B full fine-tune | 160GB+ | Multi-GPU enterprise — not locally practical |

AI Coaching System — Architecture Reference  •  March 2026  •  Back burner project, Priority 5