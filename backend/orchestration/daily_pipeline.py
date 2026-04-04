# backend/orchestration/daily_pipeline.py
"""
DailyPipeline — the "3 AM clock".

Coordinates the full overnight morning-decision cycle:
  1. Garmin sync      — pull overnight activities + HRV from Garmin Connect
  2. Influx write     — store activity TSS and HRV readings
  3. Fitness state    — calculate current CTL/ATL/TSB
  4. Biometrics       — collect sleep score, body battery, resting HR, HRV
  5. Signal conflict  — assess readiness signals with learned weights
  6. Today's session  — pull primary + conditional_alt from active monthly plan
  7. Morning decision — call Ollama only when signals conflict; else use plan as-is
  8. Log choice       — store biometric snapshot + selection to PostgreSQL
  9. Notify           — send morning readout via ntfy
  10. NFOR check      — assess 2-4 week overreaching trend; alert if triggered
  11. Log             — write decision JSON to /data/logs

On failure, errors are logged and the pipeline exits non-zero so the systemd
timer or cron job can alert. Partial failures (e.g. LLM down) degrade
gracefully — the plan session is still surfaced without LLM refinement.
"""

import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config_manager import ConfigManager
from backend.data_ingestion.garmin_sync import GarminSyncManager
from backend.storage.influx_client import InfluxClient
from backend.storage.postgres_client import PostgresClient
from backend.analysis.fitness_models import calculate_ctl_atl_tsb
from backend.analysis.signal_importance import assess_signal_conflict
from backend.analysis.nfor_detector import NFORDetector
from backend.analysis.injury_tracker import InjuryTracker
from backend.analysis.hrv_normaliser import HRVNormaliser
from backend.planning.profile_manager import ProfileManager
from backend.data_ingestion.weather_service import WeatherService
from backend.rag.vector_db import VectorDB
from backend.orchestration.llm_client import OllamaClient, build_morning_decision_context
from backend.orchestration.notifier import Notifier
from backend.schemas.context import AthleteState, RaceEvent, TrainingBlock
from backend.schemas.nfor import NFORSignalSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DailyPipeline
# ---------------------------------------------------------------------------
class DailyPipeline:
    def __init__(
        self,
        garmin_sync: Optional[GarminSyncManager] = None,
        influx: Optional[InfluxClient] = None,
        postgres: Optional[PostgresClient] = None,
        vector_db: Optional[VectorDB] = None,
        llm: Optional[OllamaClient] = None,
        notifier: Optional[Notifier] = None,
        log_dir: Optional[str] = None,
    ):
        self.garmin_sync = garmin_sync or GarminSyncManager()
        self.influx = influx or InfluxClient()
        self.postgres = postgres or PostgresClient()
        self.vector_db = vector_db or VectorDB()
        self.llm = llm or OllamaClient(
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://192.168.50.46:11434"),
            model=os.environ.get("OLLAMA_MODEL", "llama3.1:70b"),
        )
        self.notifier = notifier or Notifier()
        self.log_dir = Path(log_dir or os.environ.get("LOG_DIR", "/data/logs"))
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.ctl_lookback = int(os.environ.get("CTL_LOOKBACK_DAYS", "120"))

    # -----------------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------------
    def run(self, skip_sync: bool = False, dry_run: bool = False) -> Dict[str, Any]:
        """
        Execute the full morning decision pipeline.

        Returns a dict describing the morning decision result.
        skip_sync: skip the Garmin sync step
        dry_run:   run everything but skip logging the choice and sending notifications
        """
        run_start = datetime.now(timezone.utc)
        logger.info("=== Daily pipeline starting — %s ===", run_start.isoformat())

        # ------------------------------------------------------------------
        # Step 1: Garmin sync
        # ------------------------------------------------------------------
        if not skip_sync:
            logger.info("[1/10] Syncing Garmin Connect data")
            try:
                self.garmin_sync.sync_garmindb()
            except Exception as exc:
                logger.error("Garmin sync failed: %s", exc)
                logger.warning("Continuing with existing InfluxDB data")
                if not dry_run:
                    self.notifier.pipeline_failure("Garmin sync", str(exc))
        else:
            logger.info("[1/10] Skipping Garmin sync (skip_sync=True)")

        # ------------------------------------------------------------------
        # Step 2: Write yesterday's activities to InfluxDB
        # ------------------------------------------------------------------
        logger.info("[2/10] Writing recent activities to InfluxDB")
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
        logger.info("[3/10] Calculating CTL/ATL/TSB")
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
        # Step 4: Collect overnight biometrics
        # ------------------------------------------------------------------
        logger.info("[4/10] Collecting overnight biometrics")
        biometrics = self.garmin_sync.get_biometrics_snapshot()

        # Compute HRV baseline and percent delta from InfluxDB history
        hrv_values = self.influx.get_hrv_values(days=14)
        if hrv_values and len(hrv_values) >= 4:
            hrv_7d_avg = sum(hrv_values[-7:]) / min(len(hrv_values), 7)
            biometrics["hrv_7d_avg"] = round(hrv_7d_avg, 1)
            # Today's HRV — most recent reading
            today_hrv = hrv_readings[-1].get("rmssd") if hrv_readings else None
            biometrics["hrv_this_morning"] = today_hrv
        else:
            biometrics["hrv_7d_avg"] = None
            biometrics["hrv_this_morning"] = None

        # Resting HR 7-day baseline for signal scoring
        if hrv_values and len(hrv_values) >= 7:
            biometrics["resting_hr_7d_avg"] = biometrics.get("resting_hr")  # best available

        # Prior day TSS ratio for carry-forward fatigue signal
        yesterday_tss_ratio = _compute_yesterday_tss_ratio(
            self.postgres, yesterday_summary.get("total_tss", 0)
        )
        biometrics["prior_day_tss_ratio"] = yesterday_tss_ratio

        logger.info(
            "Biometrics — HRV: %s (7d avg: %s), sleep: %s hr / score %s, battery: %s",
            biometrics.get("hrv_this_morning"),
            biometrics.get("hrv_7d_avg"),
            biometrics.get("sleep_duration_hr"),
            biometrics.get("sleep_score"),
            biometrics.get("body_battery"),
        )

        # ------------------------------------------------------------------
        # Step 5: Assess signal conflict
        # ------------------------------------------------------------------
        logger.info("[5/10] Assessing signal conflict")
        fitness_state = {"tsb": round(tsb_val, 1), "prior_day_tss_ratio": yesterday_tss_ratio}
        conflict = assess_signal_conflict(biometrics, fitness_state)
        logger.info(
            "Signal conflict: %s (score=%.3f, drivers=%s)",
            conflict["level"], conflict["composite_score"], conflict["top_drivers"],
        )

        # ------------------------------------------------------------------
        # Step 6: Pull today's planned session from active monthly plan
        # ------------------------------------------------------------------
        logger.info("[6/10] Loading today's session from monthly plan")
        today_day_plan = self.postgres.get_today_session()

        if not today_day_plan:
            logger.warning(
                "No active monthly plan or no session scheduled for today (%s). "
                "Run the monthly pipeline first.",
                date.today().isoformat(),
            )
            if not dry_run:
                self.notifier.pipeline_failure(
                    "Daily pipeline",
                    "No active monthly plan found — run monthly generation first.",
                )
            return {"status": "no_plan", "date": date.today().isoformat()}

        if today_day_plan.get("rest_day"):
            logger.info("Today is a scheduled rest day — %s", today_day_plan.get("rest_rationale", ""))
            result = {"status": "rest_day", "date": date.today().isoformat()}
            if not dry_run:
                self.notifier.morning_readout({
                    "conflict_level": "clear",
                    "recommendation": "rest",
                    "signal_summary": "Scheduled rest day — no session today.",
                })
            return result

        primary = today_day_plan.get("primary")
        conditional_alt = today_day_plan.get("conditional_alt")

        # ------------------------------------------------------------------
        # Step 7: Morning decision — LLM only when signals warrant it
        # ------------------------------------------------------------------
        logger.info("[7/10] Morning decision (conflict=%s, show_alt=%s)", conflict["level"], conflict["show_alt"])

        morning_result = _make_morning_decision(
            llm=self.llm,
            primary=primary,
            conditional_alt=conditional_alt,
            biometrics=biometrics,
            yesterday_summary=yesterday_summary,
            conflict=conflict,
        )

        logger.info(
            "Decision: %s — %s",
            morning_result["recommendation"],
            morning_result["signal_summary"],
        )

        # ------------------------------------------------------------------
        # Step 8: Load enriched context (weather, injury, profile)
        # ------------------------------------------------------------------
        logger.info("[8/10] Enriching context")
        cfg = ConfigManager()
        profile_mgr = ProfileManager(self.postgres)
        profile = profile_mgr.load_profile()

        weather_ctx = _safe_get_weather()
        injury_ctx = _safe_get_injury_flags(self.postgres, tss_series.tolist() if not tss_series.empty else [])
        cycle_notes = profile_mgr.get_cycle_training_notes(profile)
        medication_annotations = profile_mgr.annotate_context_for_medications(profile, {}).get(
            "medication_annotations"
        )
        ftp_advisory = _ftp_advisory(tss_series, cfg.athlete_ftp())

        # Attach enrichment context to morning_result for logging and return
        morning_result["weather"] = weather_ctx
        morning_result["injury_flags"] = injury_ctx
        morning_result["cycle_notes"] = cycle_notes
        morning_result["medication_annotations"] = medication_annotations

        # Log enrichments but don't let failures block the pipeline
        if weather_ctx:
            logger.info("Weather: %s", weather_ctx.get("summary", ""))
        if injury_ctx and injury_ctx.get("risk_level") != "low":
            logger.warning("Injury risk: %s — %s", injury_ctx["risk_level"], injury_ctx.get("summary", ""))

        # ------------------------------------------------------------------
        # Step 9: Log choice + send notification
        # ------------------------------------------------------------------
        if not dry_run:
            chose_primary = morning_result["recommendation"] != "alt"
            try:
                self.postgres.log_morning_choice({
                    "choice_date": date.today().isoformat(),
                    "sport": primary.get("sport") if primary else None,
                    "chose_primary": chose_primary,
                    "conflict_level": conflict["level"],
                    "composite_score": conflict["composite_score"],
                    "top_drivers": conflict["top_drivers"],
                    "biometrics_snap": biometrics,
                    "notes": morning_result.get("signal_summary", ""),
                })
            except Exception as exc:
                logger.error("Failed to log morning choice: %s", exc)

            notif_payload = {
                **morning_result,
                "gear_alerts": _get_gear_alerts(profile),
                "cycle_notes": cycle_notes,
                "medication_annotations": medication_annotations,
            }
            if ftp_advisory:
                notif_payload["signal_summary"] = (
                    morning_result["signal_summary"] + f"\n\n💡 FTP Advisory: {ftp_advisory}"
                )
            self.notifier.morning_readout(notif_payload)
        else:
            logger.info("[9/10] DRY RUN — skipping choice log and notification")

        # ------------------------------------------------------------------
        # Step 10: NFOR check
        # ------------------------------------------------------------------
        logger.info("[10/10] Checking NFOR (overreaching) status")
        nfor_alert = _check_nfor(
            postgres=self.postgres,
            influx=self.influx,
            hrv_values=hrv_values,
            daily_tss=tss_series.tolist() if not tss_series.empty else [],
        )
        if nfor_alert and not dry_run:
            logger.warning("NFOR alert: %s", nfor_alert.severity.value)
            try:
                self.postgres.store_nfor_alert(
                    alert_date=nfor_alert.alert_date,
                    severity=nfor_alert.severity.value,
                    alert_json=nfor_alert.model_dump(),
                )
            except Exception as exc:
                logger.error("Failed to store NFOR alert: %s", exc)
            self.notifier.nfor_alert(nfor_alert.model_dump())

        # ------------------------------------------------------------------
        # Save decision log
        # ------------------------------------------------------------------
        self._save_decision_log(morning_result, conflict, run_start)
        logger.info(
            "=== Pipeline complete in %.1fs ===",
            (datetime.now(timezone.utc) - run_start).total_seconds(),
        )
        return morning_result

    # -----------------------------------------------------------------------
    # Save decision JSON log
    # -----------------------------------------------------------------------
    def _save_decision_log(
        self, decision: Dict, conflict: Dict, run_time: datetime
    ) -> None:
        log_file = self.log_dir / f"morning_{run_time.strftime('%Y%m%d_%H%M%S')}.json"
        import json
        try:
            log_file.write_text(
                json.dumps({"decision": decision, "conflict": conflict}, indent=2),
                encoding="utf-8",
            )
            logger.info("Decision log saved to %s", log_file)
        except OSError as exc:
            logger.error("Failed to write decision log: %s", exc)


# ---------------------------------------------------------------------------
# Morning decision logic
# ---------------------------------------------------------------------------
def _make_morning_decision(
    llm: OllamaClient,
    primary: Optional[Dict],
    conditional_alt: Optional[Dict],
    biometrics: Dict,
    yesterday_summary: Dict,
    conflict: Dict,
) -> Dict[str, Any]:
    """
    Decide primary vs alt based on signal conflict level.

    - clear / mild + HRV available → use plan as-is, skip LLM
    - significant / high OR HRV missing → call LLM for refined decision
    """
    readout_line = conflict.get("readout_line", "")

    # Skip LLM when signals are clear — saves ~2min of Ollama latency
    if conflict["level"] in ("clear", "mild") and conflict.get("hrv_available"):
        return {
            "recommendation": "primary",
            "conflict_level": conflict["level"],
            "signal_summary": readout_line,
            "primary": primary,
            "alt": conditional_alt,
        }

    # Signal conflict or missing HRV → call LLM for refined wording and recommendation
    if not primary:
        return {
            "recommendation": "primary",
            "conflict_level": conflict["level"],
            "signal_summary": readout_line,
            "primary": None,
            "alt": None,
        }

    try:
        yesterday_exec = {
            "sport": yesterday_summary.get("activities", [{}])[0].get("sport"),
            "total_tss": yesterday_summary.get("total_tss"),
            "flags": [],
        }
        context = build_morning_decision_context(
            today_session={"primary": primary, "conditional_alt": conditional_alt},
            biometrics=biometrics,
            yesterday_execution=yesterday_exec,
            conflict_assessment=conflict,
        )
        result = llm.generate_morning_decision(context)
        # Ensure required keys are present; fall back gracefully
        return {
            "recommendation": result.get("recommendation", "athlete_call"),
            "conflict_level": result.get("conflict_level", conflict["level"]),
            "signal_summary": result.get("signal_summary", readout_line),
            "primary": result.get("primary", primary),
            "alt": result.get("alt", conditional_alt),
        }
    except Exception as exc:
        logger.error("Morning decision LLM call failed: %s — using plan as-is", exc)
        return {
            "recommendation": "athlete_call",
            "conflict_level": conflict["level"],
            "signal_summary": f"{readout_line} (LLM unavailable — review both options)",
            "primary": primary,
            "alt": conditional_alt,
        }


# ---------------------------------------------------------------------------
# NFOR snapshot builder and check
# ---------------------------------------------------------------------------
def _check_nfor(
    postgres: PostgresClient,
    influx: InfluxClient,
    hrv_values: List[float],
    daily_tss: List[float],
) -> Optional[Any]:
    """
    Build 28 days of NFORSignalSnapshot objects and run NFORDetector.assess().
    Returns NFORAlert if threshold met, None if clear.
    """
    try:
        # Execution scores for the last 28 days
        start = (date.today() - timedelta(days=28)).isoformat()
        end = date.today().isoformat()
        exec_scores = postgres.get_execution_scores(start, end)
        exec_by_date: Dict[str, float] = {}
        for row in exec_scores:
            d = str(row.get("session_date", ""))[:10]
            ratio = row.get("tss_ratio")
            if d and ratio is not None:
                exec_by_date.setdefault(d, []).append(ratio)
        exec_avg_by_date = {d: sum(v) / len(v) for d, v in exec_by_date.items()}

        # HRV Z-scores using HRVNormaliser (device_id = "garmin" as default)
        normaliser = HRVNormaliser()
        hrv_z_by_idx: Dict[int, float] = {}
        if len(hrv_values) >= 14:
            for i, v in enumerate(hrv_values):
                d_str = (date.today() - timedelta(days=len(hrv_values) - 1 - i)).isoformat()
                normaliser.add_reading("garmin", d_str, v)
            for i, v in enumerate(hrv_values):
                z = normaliser.normalise("garmin", v)
                hrv_z_by_idx[i] = z

        # Post-session logs for RPE and sleep
        post_logs = postgres.get_recent_post_session_logs(days=28)
        rpe_by_date: Dict[str, int] = {
            str(row.get("session_date", ""))[:10]: row.get("rpe")
            for row in post_logs
            if row.get("rpe")
        }

        # Build snapshot list (most recent 28 days)
        snapshots = []
        for i in range(28):
            snap_date = (date.today() - timedelta(days=27 - i)).isoformat()
            hrv_idx = len(hrv_values) - 28 + i
            hrv_z = hrv_z_by_idx.get(hrv_idx) if hrv_idx >= 0 else None

            snapshots.append(NFORSignalSnapshot(
                date=snap_date,
                hrv_z_score=hrv_z,
                execution_ratio=exec_avg_by_date.get(snap_date),
                rpe_drift=_estimate_rpe_drift(rpe_by_date, snap_date),
                sleep_quality_trend=None,   # populated when sleep data flows from garmindb
                resting_hr_trend=None,
            ))

        detector = NFORDetector(postgres_client=postgres, influx_client=influx)
        return detector.assess(snapshots, recent_daily_tss=daily_tss[-28:] if len(daily_tss) >= 28 else daily_tss)

    except Exception as exc:
        logger.error("NFOR check failed (non-fatal): %s", exc)
        return None


def _estimate_rpe_drift(rpe_by_date: Dict[str, int], snap_date: str) -> Optional[float]:
    """
    Rough RPE drift: difference between today's RPE and the 7-day prior average.
    Returns positive value = RPE rising. None if insufficient data.
    """
    today_rpe = rpe_by_date.get(snap_date)
    if today_rpe is None:
        return None
    prior_dates = sorted(rpe_by_date.keys())
    prior_window = [rpe_by_date[d] for d in prior_dates if d < snap_date][-7:]
    if not prior_window:
        return None
    return round(today_rpe - (sum(prior_window) / len(prior_window)), 2)


# ---------------------------------------------------------------------------
# Context enrichment helpers
# ---------------------------------------------------------------------------
def _safe_get_weather() -> Optional[Dict]:
    try:
        lat = float(os.environ.get("HOME_LATITUDE", "0") or 0)
        lon = float(os.environ.get("HOME_LONGITUDE", "0") or 0)
        if lat == 0 and lon == 0:
            return None
        ws = WeatherService(latitude=lat, longitude=lon)
        return ws.get_weekly_weather_context()
    except Exception as exc:
        logger.warning("Weather fetch failed (non-fatal): %s", exc)
        return None


def _safe_get_injury_flags(
    postgres: PostgresClient, daily_tss: List[float]
) -> Optional[Dict]:
    try:
        recent_logs_raw = postgres.get_recent_post_session_logs(days=28)
        if not recent_logs_raw:
            return None
        from backend.schemas.injury import PostSessionLog
        logs = []
        for row in recent_logs_raw:
            try:
                logs.append(PostSessionLog.model_validate(row))
            except Exception:
                pass
        if not logs:
            return None
        tracker = InjuryTracker(postgres_client=postgres)
        return tracker.assess_injury_risk(logs, daily_tss=daily_tss or None)
    except Exception as exc:
        logger.warning("Injury assessment failed (non-fatal): %s", exc)
        return None


def _get_gear_alerts(profile) -> List[str]:
    """Extract any gear replacement alerts from the athlete profile."""
    alerts = []
    try:
        for item in profile.equipment:
            if hasattr(item, "alert_message") and item.alert_message:
                alerts.append(item.alert_message)
    except Exception:
        pass
    return alerts


# ---------------------------------------------------------------------------
# Helpers (carried over / updated)
# ---------------------------------------------------------------------------
def _load_athlete_state(ctl: float, atl: float, tsb: float, hrv_trend: str) -> AthleteState:
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
    if tss_series.empty or len(tss_series) < 42:
        return None
    recent_avg = float(tss_series.iloc[-7:].mean())
    prior_avg = float(tss_series.iloc[-42:-7].mean())
    if recent_avg < prior_avg * 0.5:
        return f"3+ week training gap — FTP {current_ftp}W may be optimistic, consider reducing targets 5-10%"
    if len(tss_series) > 55 and float(tss_series.iloc[-56:-42].mean()) < prior_avg * 0.8:
        return f"Week 6-8 of build with good compliance — prime window for FTP test effort"
    return None


def _compute_yesterday_tss_ratio(postgres: PostgresClient, actual_tss: float) -> Optional[float]:
    """
    Compute yesterday's TSS ratio (actual / planned) for carry-forward fatigue signal.
    Returns None if no planned session found for yesterday.
    """
    try:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        planned = postgres.get_planned_sessions(yesterday, yesterday)
        if not planned:
            return None
        planned_tss = sum(s.get("planned_tss") or 0 for s in planned)
        if planned_tss == 0:
            return None
        return round(actual_tss / planned_tss, 3)
    except Exception:
        return None
