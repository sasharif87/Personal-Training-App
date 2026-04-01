# backend/planning/context_builders.py
"""
Data squashers.
Responsible for assembling complex internal representations (athlete config,
Influx curves, PostgreSQL execution histories) into cleanly structured JSON
to be passed into the LLM context window.
"""

from typing import Any, Dict, List, Optional

def build_monthly_generation_context(
    athlete: Any,
    fitness: Any,
    block: Any,
    race_calendar: List[Dict],
    history: List[Dict]
) -> Dict[str, Any]:
    """
    Constructs the prompt context for generating an entire mesocycle from scratch.
    """
    return {
        "prompt_type": "monthly_generation",
        "athlete": {
            "ftp": getattr(athlete, 'ftp', 250),
            "css_sec_per_100m": getattr(athlete, 'css', 90),
            "lthr_run": getattr(athlete, 'lthr_run', 165),
            "weight_kg": getattr(athlete, 'weight_kg', 75)
        },
        "current_state": {
            "ctl": getattr(fitness, 'ctl', 60),
            "atl": getattr(fitness, 'atl', 65),
            "tsb": getattr(fitness, 'tsb', -5),
            "hrv_7d_avg": getattr(fitness, 'hrv_7d', 60),
            "hrv_trend": getattr(fitness, 'hrv_trend', 'stable'),
            "sleep_quality_7d": getattr(fitness, 'sleep_7d', 'good')
        },
        "block": {
            "phase": getattr(block, 'phase', 'build'),          # base | build | peak | taper | recovery
            "week_in_block": getattr(block, 'week', 1),
            "total_block_weeks": getattr(block, 'total_weeks', 4),
            "weeks_to_a_race": getattr(block, 'weeks_to_race', 12),
            "race_format": getattr(block, 'race_format', '70.3')
        },
        "prior_month_summary": {
            "avg_execution_ratio": 0.91,
            "sessions_completed": 22,
            "sessions_missed": 2,
            "ctl_change": +4.2,
            "notes": "Missed Wednesday sessions both weeks — schedule conflict, not fatigue"
        },
        "race_calendar": race_calendar,    # all events with priority and taper windows
        "retrieved_history": history       # similar blocks from RAG — Phase D
    }

def build_weekly_review_context(
    monthly_plan: Dict,
    week_number: int,
    prior_execution: Dict,
    fitness: Any
) -> Dict[str, Any]:
    """
    Constructs the context to alter a singular upcoming week dynamically
    based on the preceding week's fatigue shift.
    """
    coming_week = monthly_plan.get("weeks", [])[week_number] if len(monthly_plan.get("weeks", [])) > week_number else {}
    return {
        "prompt_type": "weekly_review",
        "coming_week": coming_week,          # as generated in monthly plan
        "prior_week_execution": prior_execution, 
        "current_state": {
            "ctl": getattr(fitness, 'ctl', 60),
            "atl": getattr(fitness, 'atl', 65),
            "tsb": getattr(fitness, 'tsb', -5),
            "hrv_trend": getattr(fitness, 'hrv_trend', 'stable')
        },
        "instruction": (
            "Review the coming week sessions against prior week execution. "
            "Adjust targets, reorder days, or modify volumes if fatigue drifted from model. "
            "Do NOT regenerate the full month. Return only the revised week with rationale for each change."
        )
    }

def build_morning_decision_context(
    today_session: Dict,
    biometrics: Dict,
    yesterday_execution: Dict
) -> Dict[str, Any]:
    """
    Constructs the micro-context used by the LLM every single morning
    to decide between the parsed Primary and Conditional_Alt workouts.
    """
    hrv_baseline = biometrics.get("hrv_7d_avg", 0)
    hrv_today = biometrics.get("hrv_this_morning")
    hrv_pct_delta = ((hrv_today - hrv_baseline) / hrv_baseline) * 100 if hrv_baseline and hrv_today else 0
    
    return {
        "prompt_type": "morning_decision",
        "today_planned": today_session,       # primary + conditional_alt from stored plan
        "biometrics": {
            "hrv_this_morning": hrv_today,
            "hrv_7d_baseline": hrv_baseline,
            "hrv_pct_vs_baseline": round(hrv_pct_delta, 1),
            "hrv_available": hrv_today is not None,    # False if reading missing
            "sleep_score": biometrics.get("sleep_score"),
            "body_battery": biometrics.get("body_battery"),
            "resting_hr": biometrics.get("resting_hr")
        },
        "yesterday": {
            "sport": yesterday_execution.get("sport"),
            "tss_ratio": yesterday_execution.get("tss_ratio"),
            "flags": yesterday_execution.get("flags", [])
        }
    }

def assess_signal_conflict(biometrics: Dict, athlete_id: str) -> Dict[str, Any]:
    """
    Checks if multiple signals are fighting, or if the athlete is severely
    detraining or falling into deep NFOR profiles.
    Used before generation starts.
    """
    score = 0
    if biometrics.get("hrv_this_morning", 100) < biometrics.get("hrv_7d_avg", 100) * 0.9:
        score -= 1
    if biometrics.get("sleep_score", 100) < 65:
        score -= 1
        
    return {"conflict_score": score, "red_flag": score <= -2}
