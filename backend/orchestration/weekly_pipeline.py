# backend/orchestration/weekly_pipeline.py
"""
WeeklyPipeline — reviews and adjusts the coming week each Sunday at 3am.

Does NOT regenerate the full month. Takes the coming week from the stored
monthly plan and adjusts it against prior week execution drift.

Steps:
  1. Load active monthly plan from PostgreSQL
  2. Score prior week execution (planned vs actual)
  3. Pull current fitness state
  4. Call Ollama weekly review prompt
  5. Store revised week back into the monthly plan
  6. Push revised sessions to Garmin + Zwift
"""

import logging
import os
from datetime import date, timedelta
from typing import Optional

from backend.config_manager import ConfigManager
from backend.storage.influx_client import InfluxClient
from backend.storage.postgres_client import PostgresClient
from backend.orchestration.llm_client import OllamaClient, build_weekly_review_context
from backend.orchestration.notifier import Notifier
from backend.analysis.fitness_models import calculate_ctl_atl_tsb
from backend.analysis.execution_scoring import summarise_week, score_execution, score_missed_session
from backend.analysis.nutrition_engine import generate_fueling_targets
from backend.data_ingestion.weather_service import WeatherService
from backend.schemas.workout import WeekPlan
from backend.output.garmin_push import GarminPush
from backend.output.zwift_writer import ZwiftWriter

logger = logging.getLogger(__name__)


class WeeklyPipeline:
    def __init__(
        self,
        influx: Optional[InfluxClient] = None,
        postgres: Optional[PostgresClient] = None,
        llm: Optional[OllamaClient] = None,
        garmin_push: Optional[GarminPush] = None,
        zwift: Optional[ZwiftWriter] = None,
        notifier: Optional[Notifier] = None,
        config: Optional[ConfigManager] = None,
    ):
        self.influx = influx or InfluxClient()
        self.postgres = postgres or PostgresClient()
        self.llm = llm or OllamaClient()
        self.garmin_push = garmin_push or GarminPush()
        self.zwift = zwift or ZwiftWriter()
        self.notifier = notifier or Notifier()
        self.cfg = config or ConfigManager()

    def run(self, dry_run: bool = False) -> WeekPlan:
        logger.info("=== Weekly review starting — %s ===", date.today().isoformat())

        # --- Load active monthly plan ---
        monthly_plan = self.postgres.get_active_monthly_plan()
        if not monthly_plan:
            raise RuntimeError("No active monthly plan in PostgreSQL — run monthly generation first")

        week_number = self.cfg.block_week()
        weeks = monthly_plan.get("weeks", [])
        # Find the coming week (week_number - 1 as index, or first if not found)
        coming_week_idx = min(week_number - 1, len(weeks) - 1)
        coming_week = weeks[coming_week_idx] if weeks else {}

        # --- Score prior week ---
        prior_week_end = date.today() - timedelta(days=1)
        prior_week_start = prior_week_end - timedelta(days=6)
        planned = self.postgres.get_planned_sessions(
            prior_week_start.isoformat(), prior_week_end.isoformat()
        )
        actual_activities = self.influx.get_yesterday_activities(days=8)
        prior_scores = _match_and_score(planned, actual_activities)
        prior_summary = summarise_week(prior_scores)
        logger.info("Prior week: %s", prior_summary)

        # --- Fitness state ---
        tss = self.influx.get_daily_tss(days=60)
        hrv = self.influx.get_hrv_trend(days=14)
        if tss.empty:
            ctl, atl, tsb = 0.0, 0.0, 0.0
        else:
            c, a, t = calculate_ctl_atl_tsb(tss)
            ctl, atl, tsb = float(c.iloc[-1]), float(a.iloc[-1]), float(t.iloc[-1])

        fitness = {"ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(tsb, 1), "hrv_trend": hrv}

        # --- Weather context for next 7 days ---
        weather_ctx = None
        try:
            lat = float(os.environ.get("ATHLETE_LATITUDE", "0") or 0)
            lon = float(os.environ.get("ATHLETE_LONGITUDE", "0") or 0)
            if lat != 0 or lon != 0:
                weather_ctx = WeatherService(latitude=lat, longitude=lon).get_weekly_weather_context()
        except Exception as exc:
            logger.warning("Weather fetch failed (non-fatal): %s", exc)

        context = build_weekly_review_context(
            coming_week=coming_week,
            prior_week_execution=prior_summary,
            fitness_state=fitness,
            weather=weather_ctx,
        )

        # --- LLM call ---
        logger.info("Calling Ollama weekly review (model: %s)", self.llm.model)
        try:
            raw = self.llm.generate_weekly_review(context)
            revised_week = WeekPlan.model_validate(raw)
        except Exception as exc:
            logger.error("Weekly review LLM/validation failed: %s — returning original week unchanged", exc)
            if not dry_run:
                self.notifier.pipeline_failure("Weekly review", f"LLM failed ({exc}) — original week kept")
            # Return the original week as a WeekPlan so callers don't crash
            try:
                revised_week = WeekPlan.model_validate(coming_week)
            except Exception:
                revised_week = WeekPlan(
                    week_number=coming_week.get("week_number", week_number),
                    block_phase=coming_week.get("block_phase", self.cfg.block_phase()),
                    target_tss=coming_week.get("target_tss", 0),
                    days=coming_week.get("days", []),
                    sessions=coming_week.get("sessions", []),
                )
            return revised_week

        logger.info(
            "Weekly review complete — %s changes: %s",
            revised_week.week_number,
            raw.get("changes_rationale", "none")[:120],
        )

        # --- Fueling targets for long sessions ---
        _annotate_fueling_targets(revised_week)

        if not dry_run:
            _push_week(revised_week, self.garmin_push, self.zwift, self.cfg)
            self.notifier.weekly_summary({
                "sessions_completed": prior_summary.get("sessions_completed", 0),
                "sessions_missed": prior_summary.get("sessions_missed", 0),
                "week_tss_ratio": prior_summary.get("week_tss_ratio", 0),
                "total_actual_tss": prior_summary.get("total_actual_tss", 0),
                "flag_summary": prior_summary.get("flag_summary", {}),
            })

        return revised_week


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _match_and_score(planned_sessions, actual_activities):
    """Simple date+sport matching between planned sessions and actual activities."""
    from backend.schemas.workout import ExecutionScore

    scores = []
    actual_by_date_sport = {}
    for act in actual_activities:
        key = (act.get("time", "")[:10], act.get("sport", ""))
        actual_by_date_sport[key] = act

    for planned in planned_sessions:
        key = (str(planned.get("planned_date", ""))[:10], planned.get("sport", ""))
        actual = actual_by_date_sport.get(key)
        if actual:
            scores.append(score_execution(planned, actual))
        else:
            scores.append(score_missed_session(planned))

    return scores


def _annotate_fueling_targets(week: WeekPlan) -> None:
    """
    Attach fueling notes to the rationale of sessions over 90 minutes.
    Only annotates — does not modify training targets.
    """
    sessions = week.sessions or [day.primary for day in (week.days or []) if day.primary]
    for session in sessions:
        if not session:
            continue
        duration_min = sum(
            (step.duration_sec or 0) for step in session.steps
        ) / 60.0
        if duration_min >= 90:
            targets = generate_fueling_targets(
                duration_min=duration_min,
                sport=session.sport,
                intensity="moderate",
            )
            fueling_note = (
                f"Fueling: {targets.carb_target_g_per_hr:.0f}g carbs/hr, "
                f"{targets.fluid_target_ml_per_hr:.0f}ml fluid/hr, "
                f"{targets.sodium_target_mg_per_hr:.0f}mg sodium/hr. {targets.notes}"
            )
            session.rationale = f"{session.rationale}\n\n{fueling_note}"


def _push_week(week: WeekPlan, garmin: GarminPush, zwift: ZwiftWriter, cfg: ConfigManager):
    """Push revised week sessions to Garmin and Zwift."""
    from datetime import timedelta
    from backend.analysis.tss_calculators import css_str_to_sec

    ftp = cfg.athlete_ftp()
    css_str = cfg.athlete_css()
    css_mps = 100.0 / css_str_to_sec(css_str)

    push_date = date.today() + timedelta(days=1)  # start Monday
    sessions = week.sessions or [day.primary for day in (week.days or []) if day.primary]

    for session in sessions:
        if not session:
            continue
        try:
            if session.sport in ("bike", "brick"):
                try:
                    zwift.write(session)
                except Exception as exc:
                    logger.error("Zwift write failed for '%s': %s", session.title, exc)
            wid = garmin.push_workout(session, athlete_ftp=ftp, athlete_css_mps=css_mps)
            garmin.schedule_workout(wid, push_date.isoformat())
            push_date += timedelta(days=1)
        except Exception as exc:
            logger.error("Push failed for '%s': %s", session.title, exc)
