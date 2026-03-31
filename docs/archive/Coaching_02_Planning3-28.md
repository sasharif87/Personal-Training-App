**AI Coaching System**

Project Planning & Roadmap

Phase Sequence  •  Dependencies  •  Decision Points  •  Timeline

# **Project Status**

| Field | Detail |
| :---- | :---- |
| Priority | Back burner — behind race season, SME, TrueNAS infra, house projects |
| Status | Concept fully documented — infrastructure awareness mode only |
| Phase A start | Late 2026 — after core infra is stable and UPS installed |
| Full operational system | 2028 — refinement loop with RAG and fine-tuning |
| Hard dependencies | Stable TrueNAS, UPS, Ollama deployed, Garmin pipeline, JupyterLab |

  Do not start this project until TrueNAS infrastructure is fully stable. Building a data pipeline on an unstable system risks data corruption — particularly for InfluxDB and the Garmin historical archive. The UPS being unresolved is a real data integrity risk.

# **Why Build Order Matters**

The temptation is to jump to the LLM layer because it's the interesting part. That is the wrong order. The analysis layer cannot do useful work without clean data. The LLM cannot reason well without a working analysis layer feeding it structured inputs. The RAG layer cannot retrieve relevant history without embeddings built from clean historical data. Each phase is a genuine prerequisite for the next.

The system is the hard part. Model quality improves automatically when you upgrade hardware or models improve. The pipeline architecture — data cleaning, analysis notebooks, prompt structure, output format, retrieval logic — is the investment that does not become obsolete.

# **Phase A — Data Foundation**

## **Target: Late 2026**

Prerequisites: stable TrueNAS, UPS installed and verified, core services running without issues.

**Garmin Data Pipeline**

* Deploy Garmindb — connect to Garmin Connect, pull 10 years of historical FIT files

* Establish ongoing sync — new activities pull automatically as they complete

* Connect Garmindb output to InfluxDB — time-series storage for all metrics

* Verify data quality — 10 years across multiple Garmin device generations will have gaps, format differences, device change artifacts to clean

* Pull planned workout definitions alongside completed activities — need both sides of the plan/actual pair

**Trainer Road Historical Export**

* Run trainerroad-export to pull full workout library and calendar history as structured data

* Capture workout description text — the coaching intent, not just the power numbers

* This is a one-time historical pull — ongoing bike workout data comes via Garmin sync

* Store workout definitions locally with their Garmin-matched execution data

**LLM Familiarisation**

* Deploy Ollama and Open WebUI on current server

* Run 13B model — understand what it produces for training plan prompts before building around it

* Identify where model reasoning falls short at this size — informs Phase C prompt design

* Deploy JupyterLab — development environment for all subsequent analysis work

  Phase A output: clean, queryable 10-year dataset in InfluxDB and a working Ollama install. This alone is a meaningful project — probably 2-3 months of part-time work to clean and verify the historical data properly.

# **Phase B — Analysis Layer**

## **Target: Early 2027**

Pure data science — no LLM involved yet. The goal is to understand what your data actually says about your physiology before asking a model to reason over it. These notebooks become the analysis layer that feeds structured context into the LLM in Phase C.

**Fitness Modeling**

* CTL/ATL/TSB curves across all three sports — combined load and per-sport

* Verify CTL curves against known training blocks — do they reflect what you remember?

* Identify gaps and anomalies — illness periods, detraining, injury history

**Swim-Specific Analysis**

* Extract CSS from historical swim data — identify threshold pace from test efforts and race data

* Build CSS-relative stress scoring — comparable to TSS for run and bike

* Stroke rate and DPS trends where Garmin has captured them

**Physiological Correlations**

* HRV correlation analysis — does morning HRV trend predict subsequent performance degradation for you specifically?

* Sleep quality correlation — which sleep metrics most reliably predict training execution quality?

* Environmental impact analysis — how much does heat suppress your power? Your run pace? Are swim and bike affected differently?

* Recovery curve modeling — how long does your run recovery actually take after different session intensities and volumes?

**FTP History**

* Reconstruct FTP history from power curve analysis across 10 years

* Correlate FTP changes to training blocks — what actually moved the needle for you?

* Identify seasonal FTP patterns — when does your FTP peak in a typical year?

  Phase B output: a set of personal physiological parameters — your numbers, not population averages. These become the structured inputs the LLM receives in Phase C rather than raw data.

# **Phase C — Structured Prompt Pipeline**

## **Target: Mid 2027 — Steiger build available**

Connect analysis outputs to the LLM. Start simple — direct prompting with structured inputs, no RAG yet. This phase is about finding out what the model does well and where it fails for your specific use case.

* Build structured fitness state summary — current CTL/ATL/TSB, HRV trend, sleep quality, FTP, block position, weeks to A-race

* Feed summary to LLM, ask for a single week of workouts — assess quality

* Establish JSON output format from day one — session type, duration, intensity targets, set breakdown, rationale

* Iterate on prompt structure — this is where the real prompt engineering happens

* Add race calendar context — A-race format and date, B-race treatment classification

* Test Zwift .zwo output generation — validate power targets against FTP fractions

* Test Garmin workout push via garth — verify sessions appear on watch correctly

* Run 70B Q4 via CPU offload — validate overnight batch generation is practical

  Phase C output: a working end-to-end pipeline that generates a week of workouts, pushes them to Garmin and Zwift, and produces structured JSON. Quality will be imperfect — that is expected. The architecture is the deliverable here, not perfect plans.

# **Phase D — RAG Integration**

## **Target: Late 2027**

Only build the retrieval layer when Phase C is working and you have directly observed that context window limits are causing problems. Building RAG before you need it adds complexity without benefit.

* Deploy Chroma or Qdrant vector database — self-hosted, lightweight, runs on current server

* Embed historical training blocks and physiological responses as vectors

* Build retrieval queries — find similar physiological states in history

* Example: last 3 times in similar heat with suppressed HRV mid-build block — what happened and what worked?

* Inject retrieved context into LLM prompt alongside current state

* Validate that retrieved context actually improves output quality — measure before and after

  Phase D output: the system now has access to your full training history as a searchable knowledge base. The LLM can reason about your historical patterns, not just your current state.

# **Phase E — Full Refinement Loop**

## **Target: 2028**

The daily autonomous loop. This is the complete system — data ingests overnight, LLM reviews and adjusts, workouts push to devices, you train, repeat.

* Automated daily data ingestion pipeline — no manual triggers

* Plan state management — system tracks current week, block, and year position

* Comparison engine — actual vs planned with drift detection and fatigue accumulation

* Workout substitution logic — not just harder/easier, but sport substitution when warranted

* FTP prediction advisory surfaced in daily readout

* Season planning interface — set A/B/C race classifications, format, dates at start of year

# **Key Decision Points**

| Decision | When | Criteria |
| :---- | :---- | :---- |
| Start Phase A | Late 2026 | TrueNAS stable, UPS installed, no pending infra work that risks data integrity |
| Move to Phase B | After Phase A | Clean data confirmed, InfluxDB verified, Garmindb pulling reliably |
| Move to Phase C | Steiger delivered | 7800 XT available as dedicated AI card, analysis notebooks complete |
| Add RAG (Phase D) | After Phase C | Have directly observed context window limits causing output quality problems |
| Buy workstation card | After Phase D | Have validated fine-tuning dataset of plan/response pairs, not before |
| Start fine-tuning | 2028+ | Phase D complete, 2+ years of plan/actual pairs collected and validated |

AI Coaching System — Project Planning  •  March 2026  •  Back burner, Priority 5