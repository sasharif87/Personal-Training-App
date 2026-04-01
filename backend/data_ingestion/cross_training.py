# backend/data_ingestion/cross_training.py
"""
Cross-Training Logging Module.
Maps Garmin cross-training activities (climb, yoga, strength) to a local taxonomy.
Stores parsed sessions into PostgreSQL.
"""

import json
from typing import Dict, Optional

from backend.storage.postgres_client import db
from backend.analysis.execution_scoring import (
    calculate_strength_tss,
    calculate_climb_tss,
    calculate_yoga_tss
)

GARMIN_CROSS_TRAINING_MAP = {
    "ROCK_CLIMBING": ("climb", "climbing_outdoor"),
    "INDOOR_CLIMBING": ("climb", "climbing_gym"),
    "YOGA": ("yoga", "hatha"),              # default — refine from activity name
    "FITNESS_EQUIPMENT": ("strength", "gym"),
    "TRAINING": ("strength", "bodyweight"),
    "HIKING": ("climb", "hiking"),          # low TSS but leg load
    "WALKING": None,                         # skip — too low load
}

def log_strength_session(session: dict) -> None:
    """
    Store strength session with computed TSS to PostgreSQL.
    Schema: strength_sessions table.
    """
    tss = calculate_strength_tss(session.get("exercises", []), session.get("duration_min", 0))
    
    # Needs to match actual schema. For now, creating it on the fly if missing or using execute
    db.execute("""
        CREATE TABLE IF NOT EXISTS strength_sessions (
            session_date DATE,
            type TEXT,
            subtype TEXT,
            duration_min NUMERIC,
            planned_tss NUMERIC,
            actual_tss NUMERIC,
            exercises JSONB,
            notes TEXT,
            rpe_avg NUMERIC,
            recovery_impact TEXT
        )
    """)
    
    exercises = session.get("exercises", [])
    rpe_avg = sum(e.get("rpe", 7) for e in exercises) / len(exercises) if exercises else None
    
    record = {
        "session_date": session.get("date"),
        "type": "strength",
        "subtype": session.get("subtype", "gym"),
        "duration_min": session.get("duration_min"),
        "planned_tss": session.get("planned_tss"),
        "actual_tss": tss,
        "exercises": json.dumps(exercises),
        "notes": session.get("notes", ""),
        "rpe_avg": rpe_avg,
        "recovery_impact": classify_recovery_impact(tss, session.get("subtype"))
    }
    
    db.execute("""
        INSERT INTO strength_sessions (
            session_date, type, subtype, duration_min,
            planned_tss, actual_tss, exercises, notes, rpe_avg, recovery_impact
        ) VALUES (
            %(session_date)s, %(type)s, %(subtype)s, %(duration_min)s,
            %(planned_tss)s, %(actual_tss)s, %(exercises)s, %(notes)s, %(rpe_avg)s, %(recovery_impact)s
        )
    """, record)

def classify_recovery_impact(tss: float, subtype: Optional[str]) -> str:
    """Tag recovery impact for LLM context."""
    if subtype in ("restorative", "stretching", "mobility"):
        return "positive"
    if tss > 60:
        return "elevated"
    if tss > 35:
        return "standard"
    return "low"

def classify_yoga_subtype(name: str) -> str:
    """Extrapolate yoga subtype from activity name."""
    name = name.lower()
    if "hot" in name: return "hot_yoga"
    if "vinyasa" in name or "flow" in name: return "vinyasa"
    if "restorative" in name or "recovery" in name: return "restorative"
    if "stretch" in name or "mobility" in name: return "mobility"
    return "hatha"

def map_garmin_cross_training(activity: dict) -> Optional[dict]:
    """Convert Garmin activity type to cross-training session schema."""
    act_type = activity.get("activityType", "")
    mapping = GARMIN_CROSS_TRAINING_MAP.get(act_type)
    if not mapping:
        return None
    
    sport, subtype = mapping
    
    if sport == "climb":
        tss = calculate_climb_tss(
            activity.get("hr_data", []),
            activity.get("lthr", 155),
            activity.get("duration_sec", 0),
            activity.get("elevation_gain_m", 0)
        )
    elif sport == "yoga":
        subtype = classify_yoga_subtype(activity.get("name", ""))
        tss = calculate_yoga_tss(subtype, activity.get("duration_min", 0))
    else:
        # Strength
        tss = calculate_strength_tss(activity.get("exercises", []), activity.get("duration_min", 0))
    
    return {
        "session_date": activity.get("date"),
        "type": sport,
        "subtype": subtype,
        "duration_min": activity.get("duration_min"),
        "actual_tss": tss,
        "source": "garmin_auto"
    }
