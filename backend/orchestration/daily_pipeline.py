# backend/orchestration/daily_pipeline.py
"""
DailyPipeline — the "3 AM clock".

Coordinates the full overnight cycle:
  1. Garmin sync   — pull yesterday's completed activities + HRV from Garmin Connect
  2. Influx write  — store activity TSS and HRV readings
  3. Analysis      — calculate current CTL/ATL/TSB + HRV trend
  4. Context build — assemble structured LLM prompt with RAG history injection
  5. LLM generate  — call Ollama to produce a WeekPlan
  6. Push outputs  — Garmin Connect (run/swim) + .zwo files (bike)
  7. Log           — write run summary to /data/logs

On failure, errors are logged and the pipeline exits non-zero so the systemd
timer or cron job can alert. Partial failures (e.g. Garmin push fails but
plan was generated) are logged but do not block logging the plan itself.
"""

import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from backend.config_manager import ConfigManager
from backend.data_ingestion.garmin_sync import GarminSyncManager
from backend.storage.influx_client import InfluxClient
from backend.analysis.fitness_models import calculate_ctl_atl_tsb
from backend.rag.vector_db import VectorDB
from backend.orchestration.llm_client import OllamaClient
from backend.schemas.context import AthleteState, RaceEvent, TrainingBlock, ContextAssembler
from backend.schemas.workout import WeekPlan
from backend.output.zwift_writer import ZwiftWriter
from backend.output.garmin_push import GarminPush

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DailyPipeline
# ---------------------------------------------------------------------------
class DailyPipeline:
    def __init__(
        self,
        garmin_sync: Optional[GarminSyncManager] = None,
        influx: Optional[InfluxClient] = None,
        vector_db: Optional[VectorDB] = None,
        llm: Optional[OllamaClient] = None,
        zwift: Optional[ZwiftWriter] = None,
        garmin_push: Optional[GarminPush] = None,
        log_dir: Optional[str] = None,
    ):
        self.garmin_sync = garmin_sync or GarminSyncManager()
        self.influx = influx or InfluxClient()
        self.vector_db = vector_db or VectorDB()
        self.llm = llm or OllamaClient(
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://192.168.50.46:11434"),
            model=os.environ.get("OLLAMA_MODEL", "llama3.1:70b"),
        )
        self.zwift = zwift or ZwiftWriter()
        self.garmin_push = garmin_push or GarminPush()
        self.log_dir = Path(log_dir or os.environ.get("LOG_DIR", "/data/logs"))
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.ctl_lookback = int(os.environ.get("CTL_LOOKBACK_DAYS", "120"))
        self.rag_results = int(os.environ.get("RAG_RESULTS", "3"))

    # -----------------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------------
    def run(self, skip_sync: bool = False, dry_run: bool = False) -> WeekPlan:
        """
        Execute the full daily pipeline.

        skip_sync: skip the Garmin sync step (useful for testing/re-runs)
        dry_run:   generate the plan but do not push to Garmin or write .zwo files
        """
        run_start = datetime.utcnow()
        logger.info("=== Daily pipeline starting — %s ===", run_start.isoformat())

        # ------------------------------------------------------------------
        # Step 1: Garmin sync
        # ------------------------------------------------------------------
        if not skip_sync:
            logger.info("[1/6] Syncing Garmin Connect data")
            try:
                self.garmin_sync.sync_garmindb()
            except Exception as exc:
                logger.error("Garmin sync failed: %s", exc)
                # Non-fatal if we already have recent data in Influx
                logger.warning("Continuing pipeline with existing InfluxDB data")
        else:
            logger.info("[1/6] Skipping Garmin sync (skip_sync=True)")

        # ------------------------------------------------------------------
        # Step 2: Write yesterday's activities to InfluxDB
        # ------------------------------------------------------------------
        logger.info("[2/6] Writing recent activities to InfluxDB")
        yesterday_summary = self.garmin_sync.get_yesterday_summary()
        for activity in yesterday_summary.get("activities", []):
            try:
                self.influx.write_activity(
                    activity_time=datetime.fromisoformat(activity["time"]),
                    sport=activity["sport"],
                    duration_sec=activity.get("duration_sec") or 0,
                    tss=activity.get("tss") or 0,
                    hr_avg=activity.get("hr_avg"),
                    power_avg=activity.get("power_avg"),
                    pace_avg=activity.get("pace_avg"),
                )
                if activity.get("tss"):
                    self.influx.write_daily_tss(
                        date=datetime.fromisoformat(activity["time"]),
                        sport=activity["sport"],
                        tss=activity["tss"],
                    )
            except Exception as exc:
                logger.error("Failed to write activity to InfluxDB: %s", exc)

        hrv_readings = self.garmin_sync.get_hrv_readings(days=2)
        for reading in hrv_readings:
            try:
                if reading.get("rmssd"):
                    self.influx.write_hrv(
                        date=datetime.fromisoformat(reading["date"]),
                        rmssd=reading["rmssd"],
                        hrv_score=reading.get("hrv_score"),
                    )
            except Exception as exc:
                logger.error("Failed to write HRV to InfluxDB: %s", exc)

        # ------------------------------------------------------------------
        # Step 3: Calculate fitness state
        # ------------------------------------------------------------------
        logger.info("[3/6] Calculating CTL/ATL/TSB")
        tss_series = self.influx.get_daily_tss(days=self.ctl_lookback)
        hrv_trend = self.influx.get_hrv_trend(days=14)

        if tss_series.empty:
            logger.warning("No TSS data in InfluxDB — CTL/ATL/TSB will be zero")
            ctl_val, atl_val, tsb_val = 0.0, 0.0, 0.0
        else:
            ctl, atl, tsb = calculate_ctl_atl_tsb(tss_series)
            ctl_val = float(ctl.iloc[-1])
            atl_val = float(atl.iloc[-1])
            tsb_val = float(tsb.iloc[-1])

        logger.info("CTL=%.1f  ATL=%.1f  TSB=%.1f  HRV=%s", ctl_val, atl_val, tsb_val, hrv_trend)

        # ------------------------------------------------------------------
        # Step 4: Assemble LLM context
        # ------------------------------------------------------------------
        logger.info("[4/6] Assembling LLM context")
        athlete_state = _load_athlete_state(ctl_val, atl_val, tsb_val, hrv_trend)
        training_block = _load_training_block()

        # RAG retrieval
        rag_query = (
            f"Block phase {training_block.phase}, "
            f"week {training_block.week_in_block}, "
            f"CTL {ctl_val:.0f} ATL {atl_val:.0f} TSB {tsb_val:.0f} HRV {hrv_trend}"
        )
        retrieved = self.vector_db.retrieve_similar_blocks(rag_query, n_results=self.rag_results)

        ftp_advisory = _ftp_advisory(tss_series, athlete_state.ftp)

        context = ContextAssembler(
            athlete=athlete_state,
            block=training_block,
            yesterday_actual=yesterday_summary,
            retrieved_history=retrieved,
            ftp_advisory=ftp_advisory,
        )

        # ------------------------------------------------------------------
        # Step 5: LLM workout generation
        # ------------------------------------------------------------------
        logger.info("[5/6] Generating week plan via Ollama (%s)", self.llm.model)
        raw_plan = self.llm.generate_workout_plan(context.model_dump())
        try:
            week_plan = WeekPlan.model_validate(raw_plan)
        except Exception as exc:
            logger.error("WeekPlan validation failed: %s\nRaw: %s", exc, raw_plan)
            raise

        logger.info(
            "Generated week %d — %s — %d sessions",
            week_plan.week_number, week_plan.block_phase, len(week_plan.sessions)
        )

        # ------------------------------------------------------------------
        # Step 6: Push outputs
        # ------------------------------------------------------------------
        if dry_run:
            logger.info("[6/6] DRY RUN — skipping Garmin push and .zwo write")
        else:
            logger.info("[6/6] Pushing workouts to Garmin Connect and Zwift")
            _push_sessions(week_plan, self.garmin_push, self.zwift, athlete_state)

        # ------------------------------------------------------------------
        # Log plan to file
        # ------------------------------------------------------------------
        self._save_plan_log(week_plan, run_start)
        logger.info("=== Pipeline complete in %.1fs ===", (datetime.utcnow() - run_start).total_seconds())
        return week_plan

    # -----------------------------------------------------------------------
    # Save plan JSON log
    # -----------------------------------------------------------------------
    def _save_plan_log(self, plan: WeekPlan, run_time: datetime) -> None:
        log_file = self.log_dir / f"plan_{run_time.strftime('%Y%m%d_%H%M%S')}.json"
        try:
            log_file.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
            logger.info("Plan saved to %s", log_file)
        except OSError as exc:
            logger.error("Failed to write plan log: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_athlete_state(ctl: float, atl: float, tsb: float, hrv_trend: str) -> AthleteState:
    """Loads athlete parameters from season config (set once at season start)."""
    c = ConfigManager()
    return AthleteState(
        ftp=c.athlete_ftp(),
        css=c.athlete_css(),
        lthr_run=c.athlete_lthr_run(),
        ctl=round(ctl, 1),
        atl=round(atl, 1),
        tsb=round(tsb, 1),
        hrv_trend=hrv_trend,
    )


def _load_training_block() -> TrainingBlock:
    """Loads current training block config from season config."""
    c = ConfigManager()
    race_a = c.race_a()
    race_date = race_a.get("date") or "2026-12-01"
    weeks_to_race = max(0, (date.fromisoformat(race_date) - date.today()).days // 7)

    race = RaceEvent(
        date=race_date,
        format=race_a.get("format", "Olympic"),
        priority=race_a.get("priority", "A"),
    )
    return TrainingBlock(
        phase=c.block_phase(),
        week_in_block=c.block_week(),
        weeks_to_race=weeks_to_race,
        target_race=race,
    )


def _ftp_advisory(tss_series, current_ftp: int) -> Optional[str]:
    """
    Simple FTP advisory signal based on training load pattern.
    Returns a short advisory string or None.
    """
    if tss_series.empty or len(tss_series) < 42:
        return None

    recent_avg = float(tss_series.iloc[-7:].mean())
    prior_avg = float(tss_series.iloc[-42:-7].mean())

    if recent_avg < prior_avg * 0.5:
        return f"3+ week training gap detected — FTP {current_ftp}W may be optimistic, consider reducing targets by 5-10%"
    if len(tss_series) > 55 and float(tss_series.iloc[-56:-42].mean()) < prior_avg * 0.8:
        return f"Currently in week 6-8 of build with good compliance — prime window for FTP test effort"
    return None


def _push_sessions(plan: WeekPlan, garmin: GarminPush, zwift: ZwiftWriter, athlete: AthleteState) -> None:
    """
    Pushes each session to the appropriate output.
    Bike sessions → .zwo + Garmin
    Run/swim/brick sessions → Garmin only
    """
    css_mps = _parse_css(athlete.css)

    # Sessions are pushed starting from tomorrow
    push_date = date.today() + timedelta(days=1)

    for session in plan.sessions:
        try:
            if session.sport in ("bike", "brick"):
                try:
                    zwift.write(session)
                except Exception as exc:
                    logger.error("Zwift .zwo write failed for '%s': %s", session.title, exc)

            workout_id = garmin.push_workout(session, athlete_ftp=athlete.ftp, athlete_css_mps=css_mps)
            garmin.schedule_workout(workout_id, push_date.isoformat())
            push_date += timedelta(days=1)

        except Exception as exc:
            logger.error("Failed to push session '%s': %s", session.title, exc)


def _parse_css(css_str: str) -> float:
    """
    Parses CSS string like '1:45/100m' to metres/sec.
    Returns 1.4 as safe default if parsing fails.
    """
    try:
        parts = css_str.replace("/100m", "").strip().split(":")
        minutes, seconds = int(parts[0]), float(parts[1])
        total_sec = minutes * 60 + seconds
        return 100.0 / total_sec
    except Exception:
        return 1.4
