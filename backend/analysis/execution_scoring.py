# backend/analysis/execution_scoring.py
"""
Execution scoring engine — compares planned vs actual sessions.

Produces an ExecutionScore per session with:
  - tss_ratio, duration_ratio, if_delta, set_completion
  - overall_execution (weighted composite)
  - flags (OVERCOOKED, UNDERDELIVERED, TOO_HARD, BAILED, MISSED)

Also provides aggregate weekly/monthly execution summaries for the LLM context.
"""

import logging
from typing import Any, Dict, List, Optional

from backend.schemas.workout import ExecutionScore, PlannedSession

logger = logging.getLogger(__name__)

# Thresholds for flag generation
_TSS_OVER_THRESHOLD = 1.15
_TSS_UNDER_THRESHOLD = 0.75
_IF_HIGH_DELTA = 0.10
_SET_BAIL_THRESHOLD = 0.80
_MISSED_THRESHOLD = 0.20   # below 20% of planned = effectively missed

# Weights for overall_execution composite
_WEIGHTS = {
    "tss_ratio":      0.40,
    "duration_ratio": 0.25,
    "set_completion": 0.35,
}


def score_execution(planned: Dict[str, Any], actual: Dict[str, Any]) -> ExecutionScore:
    """
    Compare a planned session to a completed Garmin activity.

    planned: PlannedSession dict (or any dict with planned_tss, planned_duration_min, etc.)
    actual:  activity dict from garmindb / InfluxDB
             expected keys: tss, duration_min, intensity_factor (optional), fit_data (optional)
    """
    planned_tss = planned.get("planned_tss")
    actual_tss = actual.get("tss")
    planned_dur = planned.get("planned_duration_min")
    actual_dur = actual.get("duration_min") or (actual.get("duration_sec", 0) / 60)
    planned_if = planned.get("planned_if")
    actual_if = actual.get("intensity_factor")

    tss_ratio = _safe_ratio(actual_tss, planned_tss)
    duration_ratio = _safe_ratio(actual_dur, planned_dur)
    if_delta = _safe_delta(actual_if, planned_if)

    # Set completion — requires structured interval data
    planned_sets = _count_planned_sets(planned.get("structure", {}))
    actual_sets = _count_actual_sets(actual.get("fit_data"))
    set_completion = _safe_ratio(actual_sets, planned_sets)

    overall = _weighted_score(tss_ratio, duration_ratio, set_completion)
    flags = generate_flags(tss_ratio, if_delta, set_completion)

    return ExecutionScore(
        session_date=planned.get("planned_date", actual.get("date", "")),
        sport=planned.get("sport", actual.get("sport", "unknown")),
        planned_session_id=planned.get("session_id"),
        tss_ratio=tss_ratio,
        duration_ratio=duration_ratio,
        if_delta=if_delta,
        set_completion=set_completion,
        overall_execution=overall,
        flags=flags,
        actual_tss=actual_tss,
        planned_tss=planned_tss,
    )


def score_missed_session(planned: Dict[str, Any]) -> ExecutionScore:
    """
    Create an execution score for a session that was never executed.
    Missed sessions are data — systematic misses on specific days/types are a signal.
    """
    return ExecutionScore(
        session_date=planned.get("planned_date", ""),
        sport=planned.get("sport", "unknown"),
        planned_session_id=planned.get("session_id"),
        tss_ratio=0.0,
        duration_ratio=0.0,
        if_delta=None,
        set_completion=0.0,
        overall_execution=0.0,
        flags=["MISSED"],
        actual_tss=0.0,
        planned_tss=planned.get("planned_tss"),
    )


def generate_flags(
    tss_ratio: Optional[float],
    if_delta: Optional[float],
    set_completion: Optional[float],
) -> List[str]:
    flags = []
    if tss_ratio is not None:
        if tss_ratio > _TSS_OVER_THRESHOLD:
            flags.append("OVERCOOKED")
        elif tss_ratio < _MISSED_THRESHOLD:
            flags.append("MISSED")
        elif tss_ratio < _TSS_UNDER_THRESHOLD:
            flags.append("UNDERDELIVERED")
    if if_delta is not None and if_delta > _IF_HIGH_DELTA:
        flags.append("TOO_HARD")
    if set_completion is not None and 0 < set_completion < _SET_BAIL_THRESHOLD:
        flags.append("BAILED")
    return flags


# ---------------------------------------------------------------------------
# Weekly / monthly summaries
# ---------------------------------------------------------------------------
def summarise_week(scores: List[ExecutionScore]) -> Dict[str, Any]:
    """
    Aggregate execution scores across a week. Returns dict for LLM context.
    """
    if not scores:
        return {"sessions_scored": 0}

    valid_tss = [s.tss_ratio for s in scores if s.tss_ratio is not None]
    valid_dur = [s.duration_ratio for s in scores if s.duration_ratio is not None]
    valid_sets = [s.set_completion for s in scores if s.set_completion is not None]
    all_flags = [f for s in scores for f in s.flags]

    missed = sum(1 for s in scores if "MISSED" in s.flags)
    completed = len(scores) - missed

    return {
        "sessions_scored": len(scores),
        "sessions_completed": completed,
        "sessions_missed": missed,
        "week_tss_ratio": round(sum(valid_tss) / len(valid_tss), 3) if valid_tss else None,
        "avg_duration_ratio": round(sum(valid_dur) / len(valid_dur), 3) if valid_dur else None,
        "avg_set_completion": round(sum(valid_sets) / len(valid_sets), 3) if valid_sets else None,
        "flag_summary": {f: all_flags.count(f) for f in set(all_flags)},
        "total_actual_tss": round(sum(s.actual_tss or 0 for s in scores), 1),
        "total_planned_tss": round(sum(s.planned_tss or 0 for s in scores), 1),
        "by_sport": _by_sport_summary(scores),
    }


def _by_sport_summary(scores: List[ExecutionScore]) -> Dict[str, Dict]:
    by_sport: Dict[str, List] = {}
    for s in scores:
        by_sport.setdefault(s.sport, []).append(s)
    return {
        sport: {
            "count": len(sl),
            "missed": sum(1 for s in sl if "MISSED" in s.flags),
            "avg_tss_ratio": round(
                sum(s.tss_ratio for s in sl if s.tss_ratio) / max(1, sum(1 for s in sl if s.tss_ratio)), 3
            ),
        }
        for sport, sl in by_sport.items()
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_ratio(actual, planned) -> Optional[float]:
    if actual is None or planned is None or planned == 0:
        return None
    return round(actual / planned, 3)


def _safe_delta(actual, planned) -> Optional[float]:
    if actual is None or planned is None:
        return None
    return round(actual - planned, 3)


def _weighted_score(
    tss_ratio: Optional[float],
    duration_ratio: Optional[float],
    set_completion: Optional[float],
) -> Optional[float]:
    total_weight = 0.0
    weighted_sum = 0.0
    for val, key in [(tss_ratio, "tss_ratio"), (duration_ratio, "duration_ratio"), (set_completion, "set_completion")]:
        if val is not None:
            w = _WEIGHTS[key]
            # Clip at 1.0 — over-delivery doesn't improve the score
            weighted_sum += min(val, 1.0) * w
            total_weight += w
    if total_weight == 0:
        return None
    return round(weighted_sum / total_weight, 3)


def _count_planned_sets(structure: Dict) -> Optional[int]:
    main_sets = structure.get("main_sets") or structure.get("sets") or []
    if not main_sets:
        return None
    return sum(s.get("repeat", 1) for s in main_sets)


def _count_actual_sets(fit_data: Optional[Dict]) -> Optional[int]:
    """
    Extract completed set count from FIT lap data if available.
    fit_data: optional dict from FIT file parser with 'laps' list.
    """
    if not fit_data:
        return None
    laps = fit_data.get("laps") or []
    # Count laps flagged as intervals (excludes warmup/cooldown laps where available)
    return sum(1 for lap in laps if lap.get("type") in ("interval", "active", None))
