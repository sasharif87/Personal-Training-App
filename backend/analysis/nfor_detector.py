# backend/analysis/nfor_detector.py
"""
Non-Functional Overreaching (NFOR) Detector.

Monitors 6 signals over 2-4 week rolling windows:
  1. HRV Z-score vs 28-day mean
  2. Execution ratio trend (declining despite same targets)
  3. RPE drift (rising RPE at same intensity)
  4. Performance plateau (FTP/CSS stagnation despite progressive overload)
  5. Sleep quality trend
  6. Resting HR trend

Multi-signal threshold: 2+ concurrent signals triggers warning.
3+ signals for 2+ weeks triggers intervention recommendation.

Distinguishes NFOR from life stress: low TSS + suppressed signals = external cause.
"""

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from backend.schemas.nfor import (
    NFORSignalSnapshot,
    NFORAlert,
    NFORRecoveryBlock,
    NFORSeverity,
    NFORCause,
)

logger = logging.getLogger(__name__)

_SIGNAL_THRESHOLDS = {
    "hrv_z_score":         -1.5,   # Z-score below this = suppressed
    "execution_ratio":     0.80,   # Execution dropping below 80%
    "rpe_drift":           1.5,    # RPE rising > 1.5 at same load
    "sleep_quality":       "poor",
    "resting_hr_trend":    "elevated",
}


class NFORDetector:
    def __init__(self, postgres_client=None, influx_client=None):
        self._pg = postgres_client
        self._influx = influx_client

    # -----------------------------------------------------------------------
    # Main assessment
    # -----------------------------------------------------------------------
    def assess(
        self,
        snapshots: List[NFORSignalSnapshot],
        recent_daily_tss: Optional[List[float]] = None,
    ) -> Optional[NFORAlert]:
        """
        Assess NFOR risk from a sequence of daily signal snapshots.
        Looks at the most recent 2-4 weeks of data.

        Returns NFORAlert if threshold is met, None if all clear.
        """
        if len(snapshots) < 14:
            return None  # Need at least 2 weeks of data

        # Analyse most recent 2 weeks
        recent = snapshots[-14:]
        triggered_signals = self._count_triggered_signals(recent)
        n_triggered = len(triggered_signals)

        if n_triggered < 2:
            if n_triggered == 1:
                logger.debug("NFOR: 1 signal triggered (%s) — WATCH level", triggered_signals)
            return None

        # Determine duration — check if signals were also triggered 2 weeks ago
        extended = snapshots[-(28):]
        prior_two_weeks = extended[:14] if len(extended) >= 28 else []
        prior_triggered = self._count_triggered_signals(prior_two_weeks) if prior_two_weeks else []

        # Count consecutive weeks with multiple signals
        weeks_detected = 2 if len(set(triggered_signals) & set(prior_triggered)) >= 2 else 1

        # Determine cause
        cause = self._determine_cause(recent_daily_tss, triggered_signals)

        # Determine severity
        if n_triggered >= 3 and weeks_detected >= 2:
            severity = NFORSeverity.INTERVENTION
        elif n_triggered >= 3 or weeks_detected >= 2:
            severity = NFORSeverity.ALERT
        else:
            severity = NFORSeverity.WARNING

        # Build signal details
        signal_details = self._build_signal_details(recent)

        # Recovery block recommendation
        recovery = self._recommend_recovery(severity, cause)

        response = self._build_response(severity, cause, triggered_signals, weeks_detected)

        alert = NFORAlert(
            alert_date=date.today().isoformat(),
            severity=severity,
            likely_cause=cause,
            signals_triggered=triggered_signals,
            signal_details=signal_details,
            weeks_detected=weeks_detected,
            recommended_response=response,
            recovery_block=recovery if severity in (NFORSeverity.ALERT, NFORSeverity.INTERVENTION) else None,
        )

        logger.warning(
            "NFOR %s detected — %d signals, %d weeks. Cause: %s",
            severity.value, n_triggered, weeks_detected, cause.value,
        )
        return alert

    # -----------------------------------------------------------------------
    # Signal counting
    # -----------------------------------------------------------------------
    def _count_triggered_signals(self, snapshots: List[NFORSignalSnapshot]) -> List[str]:
        """Count which signals have crossed threshold for the majority of the period."""
        if not snapshots:
            return []

        triggered = []
        n = len(snapshots)

        # HRV Z-score
        hrv_scores = [s.hrv_z_score for s in snapshots if s.hrv_z_score is not None]
        if len(hrv_scores) >= n * 0.5:
            if sum(1 for z in hrv_scores if z < _SIGNAL_THRESHOLDS["hrv_z_score"]) > len(hrv_scores) * 0.6:
                triggered.append("hrv_suppressed")

        # Execution ratio
        exec_ratios = [s.execution_ratio for s in snapshots if s.execution_ratio is not None]
        if exec_ratios and sum(exec_ratios) / len(exec_ratios) < _SIGNAL_THRESHOLDS["execution_ratio"]:
            triggered.append("execution_declining")

        # RPE drift
        rpe_drifts = [s.rpe_drift for s in snapshots if s.rpe_drift is not None]
        if rpe_drifts and sum(rpe_drifts) / len(rpe_drifts) > _SIGNAL_THRESHOLDS["rpe_drift"]:
            triggered.append("rpe_drift")

        # Performance plateau
        plateaus = [s.performance_plateau for s in snapshots if s.performance_plateau is not None]
        if plateaus and sum(1 for p in plateaus if p) > len(plateaus) * 0.5:
            triggered.append("performance_plateau")

        # Sleep quality
        sleep = [s.sleep_quality_trend for s in snapshots if s.sleep_quality_trend is not None]
        if sleep and sum(1 for q in sleep if q in ("declining", "poor")) > len(sleep) * 0.5:
            triggered.append("poor_sleep")

        # Resting HR
        rhr = [s.resting_hr_trend for s in snapshots if s.resting_hr_trend is not None]
        if rhr and sum(1 for r in rhr if r in ("rising", "elevated")) > len(rhr) * 0.5:
            triggered.append("elevated_resting_hr")

        return triggered

    # -----------------------------------------------------------------------
    # Cause determination
    # -----------------------------------------------------------------------
    def _determine_cause(
        self, daily_tss: Optional[List[float]], triggered: List[str]
    ) -> NFORCause:
        """
        Distinguish training overload from life stress and illness.
        Low TSS + suppressed signals = likely external cause.
        High TSS + suppressed = classic overreaching.
        """
        if not daily_tss or len(daily_tss) < 14:
            return NFORCause.UNKNOWN

        recent_avg = sum(daily_tss[-7:]) / 7
        prior_avg = sum(daily_tss[-28:-7]) / 21 if len(daily_tss) >= 28 else recent_avg

        # Sudden resting HR spike → possible illness
        if "elevated_resting_hr" in triggered and recent_avg < prior_avg * 0.5:
            return NFORCause.ILLNESS

        # Low training load but suppressed signals → life stress
        if recent_avg < prior_avg * 0.7 and len(triggered) >= 2:
            return NFORCause.LIFE_STRESS

        # Normal/high load + suppressed = training overload
        return NFORCause.TRAINING_OVERLOAD

    # -----------------------------------------------------------------------
    # Recovery recommendation
    # -----------------------------------------------------------------------
    def _recommend_recovery(
        self, severity: NFORSeverity, cause: NFORCause
    ) -> NFORRecoveryBlock:
        """Generate a recovery block recommendation."""
        if cause == NFORCause.LIFE_STRESS:
            return NFORRecoveryBlock(
                duration_weeks=1,
                volume_pct=0.50,
                max_intensity="Z2",
                structure_notes=(
                    "Life stress detected — not training overload. "
                    "Reduce training to easy sessions only. "
                    "Prioritise sleep, nutrition, and stress management. "
                    "Training will be beneficial for mood but keep it light."
                ),
                resume_condition="Subjective stress reduction AND HRV baseline recovery",
            )

        if cause == NFORCause.ILLNESS:
            return NFORRecoveryBlock(
                duration_weeks=1,
                volume_pct=0.0,
                max_intensity="rest",
                structure_notes=(
                    "Possible illness detected — complete rest until afebrile for 24hr. "
                    "No training with fever, elevated resting HR, or chest symptoms. "
                    "Return with 3 days easy before any intensity."
                ),
                resume_condition="Afebrile 24hr, RHR returned to baseline, subjective wellness > 7/10",
            )

        # Training overload
        if severity == NFORSeverity.INTERVENTION:
            return NFORRecoveryBlock(
                duration_weeks=2,
                volume_pct=0.50,
                max_intensity="Z2",
                structure_notes=(
                    "Sustained overreaching — 2-week recovery block required. "
                    "Week 1: 40% volume, Z1-Z2 only, emphasis on sleep/nutrition. "
                    "Week 2: 60% volume, include one moderate effort. "
                    "Include daily mobility and swimming for active recovery."
                ),
            )
        return NFORRecoveryBlock(
            duration_weeks=1,
            volume_pct=0.60,
            max_intensity="Z2",
            structure_notes=(
                "Reduce volume to 60% for 1 week. "
                "No sessions above Z2. Include rest day between sessions. "
                "Monitor HRV and resting HR daily."
            ),
        )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------
    def _build_signal_details(self, snapshots: List[NFORSignalSnapshot]) -> Dict[str, float]:
        """Extract average signal values for the assessment period."""
        details = {}
        hrv = [s.hrv_z_score for s in snapshots if s.hrv_z_score is not None]
        if hrv:
            details["hrv_z_score_avg"] = round(sum(hrv) / len(hrv), 2)
        exec_r = [s.execution_ratio for s in snapshots if s.execution_ratio is not None]
        if exec_r:
            details["execution_ratio_avg"] = round(sum(exec_r) / len(exec_r), 3)
        rpe_d = [s.rpe_drift for s in snapshots if s.rpe_drift is not None]
        if rpe_d:
            details["rpe_drift_avg"] = round(sum(rpe_d) / len(rpe_d), 2)
        return details

    def _build_response(
        self, severity: NFORSeverity, cause: NFORCause,
        triggered: List[str], weeks: int
    ) -> str:
        cause_labels = {
            NFORCause.TRAINING_OVERLOAD: "training overload",
            NFORCause.LIFE_STRESS: "life stress (non-training)",
            NFORCause.ILLNESS: "possible illness",
            NFORCause.UNKNOWN: "unknown cause",
        }
        signals_str = ", ".join(s.replace("_", " ") for s in triggered)
        return (
            f"NFOR {severity.value.upper()} — likely {cause_labels[cause]}. "
            f"Signals: {signals_str}. Detected for ~{weeks} week(s). "
            f"Recovery block recommended."
        )
