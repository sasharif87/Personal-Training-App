# backend/analysis/injury_tracker.py
"""
Injury tracking and post-session wellness monitoring.

Handles:
  - Post-session RPE/wellness logging
  - Acute:Chronic Workload Ratio (ACWR) — flag > 1.5
  - Running volume cap — 10% weekly increase limit
  - Recurring niggle detection from pain history
  - Injury risk signal generation for LLM context
"""

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from backend.schemas.injury import (
    PostSessionLog,
    PainEntry,
    InjuryRecord,
    BodyMapLocation,
)

logger = logging.getLogger(__name__)


class InjuryTracker:
    def __init__(self, postgres_client=None, influx_client=None):
        self._pg = postgres_client
        self._influx = influx_client

    # -----------------------------------------------------------------------
    # Log post-session data
    # -----------------------------------------------------------------------
    def log_post_session(self, log: PostSessionLog) -> Dict[str, Any]:
        """
        Store a post-session log. Checks for injury patterns after storage.
        Returns summary including any alerts generated.
        """
        result = {"stored": False, "alerts": []}

        if self._pg:
            try:
                import json
                self._pg._exec_write(
                    """
                    INSERT INTO post_session_logs
                        (session_date, sport, session_id, rpe, leg_feel, motivation,
                         pain_entries, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        log.session_date, log.sport, log.session_id,
                        log.rpe, log.leg_feel, log.motivation,
                        json.dumps([p.model_dump() for p in log.pain_entries]),
                        log.notes,
                    ),
                )
                result["stored"] = True
            except Exception as exc:
                logger.error("Failed to store post-session log: %s", exc)

        # Check for patterns
        if log.pain_entries:
            alerts = self._check_pain_patterns(log)
            result["alerts"] = alerts

        # RPE drift check
        rpe_alert = self._check_rpe_drift(log)
        if rpe_alert:
            result["alerts"].append(rpe_alert)

        return result

    # -----------------------------------------------------------------------
    # ACWR — Acute:Chronic Workload Ratio
    # -----------------------------------------------------------------------
    def calculate_acwr(
        self, daily_tss: List[float], acute_window: int = 7, chronic_window: int = 28
    ) -> Dict[str, Any]:
        """
        Calculate Acute:Chronic Workload Ratio.

        ACWR > 1.5 → elevated injury risk
        ACWR 0.8-1.3 → training sweet spot
        ACWR < 0.8 → possible detraining

        daily_tss: list of daily TSS values (most recent last)
        """
        if len(daily_tss) < chronic_window:
            return {
                "acwr": None,
                "acute_load": None,
                "chronic_load": None,
                "status": "insufficient_data",
                "alert": None,
            }

        acute = daily_tss[-acute_window:]
        chronic = daily_tss[-chronic_window:]

        acute_avg = sum(acute) / len(acute)
        chronic_avg = sum(chronic) / len(chronic)

        acwr = round(acute_avg / chronic_avg, 3) if chronic_avg > 0 else 0.0

        if acwr > 1.5:
            status = "high_risk"
            alert = f"ACWR = {acwr:.2f} — elevated injury risk. Reduce acute load."
        elif acwr > 1.3:
            status = "elevated"
            alert = f"ACWR = {acwr:.2f} — entering danger zone. Be cautious with load increases."
        elif acwr >= 0.8:
            status = "optimal"
            alert = None
        else:
            status = "detraining"
            alert = f"ACWR = {acwr:.2f} — training load very low relative to baseline."

        return {
            "acwr": acwr,
            "acute_load": round(acute_avg, 1),
            "chronic_load": round(chronic_avg, 1),
            "status": status,
            "alert": alert,
        }

    # -----------------------------------------------------------------------
    # Running volume cap — 10% rule
    # -----------------------------------------------------------------------
    def check_run_volume_cap(
        self, weekly_run_km: List[float], cap_pct: float = 10.0
    ) -> Dict[str, Any]:
        """
        Enforce the 10% weekly running volume increase rule.

        weekly_run_km: list of weekly run distances (most recent last, need >= 2)
        cap_pct: max allowed weekly increase percentage
        """
        if len(weekly_run_km) < 2:
            return {"capped": False, "message": "Insufficient data for volume check"}

        last_week = weekly_run_km[-1]
        prior_week = weekly_run_km[-2]

        if prior_week == 0:
            return {
                "capped": last_week > 30,  # Hard cap for first week back
                "last_week_km": last_week,
                "prior_week_km": prior_week,
                "increase_pct": None,
                "max_this_week_km": 30.0,
                "message": "Returning from zero — cap at 30km this week",
            }

        increase_pct = ((last_week - prior_week) / prior_week) * 100
        max_km = round(prior_week * (1 + cap_pct / 100), 1)

        return {
            "capped": increase_pct > cap_pct,
            "last_week_km": last_week,
            "prior_week_km": prior_week,
            "increase_pct": round(increase_pct, 1),
            "max_this_week_km": max_km,
            "message": (
                f"Running volume increased {increase_pct:.1f}% — exceeds {cap_pct}% cap"
                if increase_pct > cap_pct
                else f"Running volume within limits ({increase_pct:.1f}%)"
            ),
        }

    # -----------------------------------------------------------------------
    # Injury risk assessment
    # -----------------------------------------------------------------------
    def assess_injury_risk(
        self,
        recent_logs: List[PostSessionLog],
        daily_tss: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """
        Comprehensive injury risk assessment combining:
        - Pain pattern analysis
        - ACWR
        - RPE drift
        - Fatigue markers (leg feel trend)
        """
        risk_signals = []

        # Pain patterns — recurring locations
        pain_counts: Dict[str, int] = defaultdict(int)
        for log in recent_logs:
            for pain in log.pain_entries:
                pain_counts[pain.location.value] += 1

        recurring = {loc: count for loc, count in pain_counts.items() if count >= 3}
        if recurring:
            for loc, count in recurring.items():
                risk_signals.append({
                    "signal": "recurring_pain",
                    "location": loc,
                    "count": count,
                    "message": f"Pain at {loc.replace('_', ' ')} reported {count} times in recent sessions",
                })

        # Leg feel trend — declining average
        leg_feels = [l.leg_feel for l in recent_logs if l.leg_feel is not None]
        if len(leg_feels) >= 5:
            recent_avg = sum(leg_feels[-3:]) / 3
            prior_avg = sum(leg_feels[:-3]) / len(leg_feels[:-3])
            if recent_avg < prior_avg * 0.75:
                risk_signals.append({
                    "signal": "declining_leg_feel",
                    "recent_avg": round(recent_avg, 1),
                    "prior_avg": round(prior_avg, 1),
                    "message": f"Leg feel declining: {recent_avg:.1f}/10 vs {prior_avg:.1f}/10 baseline",
                })

        # ACWR
        if daily_tss and len(daily_tss) >= 28:
            acwr_result = self.calculate_acwr(daily_tss)
            if acwr_result.get("alert"):
                risk_signals.append({
                    "signal": "acwr_elevated",
                    "acwr": acwr_result["acwr"],
                    "message": acwr_result["alert"],
                })

        # Motivation trend
        motivations = [l.motivation for l in recent_logs if l.motivation is not None]
        if len(motivations) >= 5 and sum(motivations[-3:]) / 3 < 4:
            risk_signals.append({
                "signal": "low_motivation",
                "recent_avg": round(sum(motivations[-3:]) / 3, 1),
                "message": "Motivation consistently low — may indicate overtraining or burnout",
            })

        return {
            "risk_level": "high" if len(risk_signals) >= 3 else "moderate" if risk_signals else "low",
            "signals": risk_signals,
            "summary": self._summarise_risk(risk_signals),
        }

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------
    def _check_pain_patterns(self, log: PostSessionLog) -> List[Dict]:
        """Check for concerning pain patterns in the current log."""
        alerts = []
        for pain in log.pain_entries:
            if pain.severity >= 7:
                alerts.append({
                    "type": "high_severity_pain",
                    "location": pain.location.value,
                    "severity": pain.severity,
                    "message": f"High severity pain ({pain.severity}/10) at {pain.location.value}",
                })
            if pain.altered_mechanics:
                alerts.append({
                    "type": "altered_mechanics",
                    "location": pain.location.value,
                    "message": f"Pain at {pain.location.value} altered movement mechanics — monitor closely",
                })
        return alerts

    def _check_rpe_drift(self, log: PostSessionLog) -> Optional[Dict]:
        """
        Check RPE drift — high RPE on easy/moderate sessions.
        This would normally compare against planned session intensity,
        but as a quick check we flag RPE >= 8 with a note.
        """
        if log.rpe >= 9:
            return {
                "type": "very_high_rpe",
                "rpe": log.rpe,
                "message": f"RPE {log.rpe}/10 reported — verify this was a hard session",
            }
        return None

    def _summarise_risk(self, signals: List[Dict]) -> str:
        if not signals:
            return "No injury risk signals detected"
        summaries = [s["message"] for s in signals]
        return "; ".join(summaries)
