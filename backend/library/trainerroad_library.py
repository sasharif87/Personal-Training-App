# backend/library/trainerroad_library.py
"""
TrainerRoad Library indexer and fuzzy matcher.
Reads JSON blocks downloaded from trainerroad-export, stores in Postgres,
and handles multi-signal fuzzy match against FIT file names and profiles.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

from backend.storage.postgres_client import db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Build Library
# ---------------------------------------------------------------------------
def build_tr_library_with_types(export_dir: str) -> int:
    """
    Load TR workout library export into PostgreSQL.
    Extended library build that also classifies and stores workout_type.
    """
    count = 0
    for f in Path(export_dir).glob("*.json"):
        try:
            raw = json.loads(f.read_text())
            lib_if = raw.get("If")
            lib_duration = raw.get("Duration", 0) / 60
            workout_type = classify_workout_type(lib_if, lib_duration)
            
            db.execute("""
                INSERT INTO tr_workout_library
                    (tr_id, name, name_lower, description, duration_min,
                     tss, intensity_factor, workout_type, structure)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tr_id) DO UPDATE
                SET name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    intensity_factor = EXCLUDED.intensity_factor,
                    workout_type = EXCLUDED.workout_type,
                    structure = EXCLUDED.structure
            """, (
                raw["Id"], raw["Name"], raw["Name"].lower().strip(),
                raw.get("Description", ""), lib_duration,
                raw.get("Tss"), lib_if, workout_type,
                json.dumps(parse_tr_intervals(raw.get("Intervals", [])))
            ))
            count += 1
        except Exception as e:
            logger.error("Failed to parse TR json file %s: %s", f, e)
            
    return count

def parse_tr_intervals(intervals: list) -> list:
    """Stub to parse TR structured intervals if needed later."""
    return intervals

# ---------------------------------------------------------------------------
# Extract and Fetch Workout from FIT metadata
# ---------------------------------------------------------------------------
def extract_tr_workout_name(fit_data: dict) -> Optional[str]:
    """
    Pull the TrainerRoad workout name from FIT file metadata.
    TR embeds the workout name in the 'workout_name' field of the session message.
    """
    return fit_data.get("workout_name") or fit_data.get("session", {}).get("workout_name")


def enrich_activity_with_tr_plan(activity: dict) -> dict:
    """
    After a FIT file is ingested, try to attach the TR planned session.
    If found, this becomes the 'planned' side of the plan/actual pair.
    """
    fit_metadata = activity.get("fit_metadata", {})
    workout_name = extract_tr_workout_name(fit_metadata)
    
    if not workout_name:
        return activity  # Not a TR workout or name not in FIT
        
    actual_if = activity.get("intensity_factor")
    actual_tss = activity.get("tss")
    actual_duration = activity.get("duration_min")
        
    tr_workout = lookup_tr_workout(workout_name, actual_if, actual_tss, actual_duration)
    
    if tr_workout:
        activity["planned_session"] = {
            "source_platform": "trainerroad",
            "import_method": "fit_name_lookup",
            "title": tr_workout["name"],
            "coaching_text": tr_workout["description"],
            "planned_duration_min": tr_workout.get("duration_min"),
            "planned_tss": tr_workout.get("tss"),
            "planned_if": tr_workout.get("intensity_factor"),
            "structure": tr_workout.get("structure", {}) if not isinstance(tr_workout.get("structure"), str) else json.loads(tr_workout["structure"])
        }
        activity["tr_match_method"] = tr_workout.get("_matched_as_fuzzy") and "fuzzy" or \
                                       tr_workout.get("_matched_as_base") and "base" or "exact"
    else:
        # Log unmatched for review — build up the library over time
        db.execute(
            "INSERT INTO tr_unmatched_names (workout_name, activity_date, activity_id) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (workout_name, activity.get("date"), activity.get("activity_id", "uid"))
        )
    
    return activity

# ---------------------------------------------------------------------------
# Match Engine
# ---------------------------------------------------------------------------
def lookup_tr_workout(
    workout_name: str, 
    actual_if: Optional[float] = None, 
    actual_tss: Optional[float] = None, 
    actual_duration: Optional[float] = None
) -> Optional[dict]:
    """
    Look up a TR workout by name from the local library.
    Tries exact match first, then normalised match, then fuzzy.
    """
    if not workout_name:
        return None
        
    # 1. Exact match
    result = db.fetchone(
        "SELECT * FROM tr_workout_library WHERE name_lower = %s",
        (workout_name.lower().strip(),)
    )
    if result:
        return result
        
    # 2. Normalised match (strip variant suffix +1, -1)
    base_name = strip_tr_variant_suffix(workout_name)
    if base_name != workout_name:
        result = db.fetchone(
            "SELECT * FROM tr_workout_library WHERE name_lower = %s",
            (base_name.lower().strip(),)
        )
        if result:
            return {**result, "_matched_as_base": True}
            
    # 3. Fuzzy match — multi-signal
    result = find_tr_workout_by_profile(
        name=workout_name,
        actual_if=actual_if,
        actual_tss=actual_tss,
        actual_duration=actual_duration
    )
    
    if result:
        return {**result, "_matched_as_fuzzy": True}
        
    return None

def strip_tr_variant_suffix(name: str) -> str:
    """'Carillon +2' → 'Carillon', 'Pettit -1' → 'Pettit'"""
    return re.sub(r'\s*[+-]\d+$', '', name).strip()

def classify_workout_type(intensity_factor: Optional[float], duration_min: Optional[float]) -> str:
    """Classify a workout into a physiological type from IF."""
    if intensity_factor is None:
        return "unknown"
    if intensity_factor >= 1.05: return "vo2max"
    elif intensity_factor >= 0.95: return "threshold"
    elif intensity_factor >= 0.88: return "sweet_spot"
    elif intensity_factor >= 0.76: return "tempo"
    elif intensity_factor >= 0.60: return "endurance"
    else: return "recovery"

def find_tr_workout_by_profile(
    name: str,
    actual_if: Optional[float],
    actual_tss: Optional[float],
    actual_duration: Optional[float]
) -> Optional[dict]:
    """
    Multi-signal fuzzy match against the TR workout library.
    Scores on name similarity, workout type match, IF delta, TSS delta, duration delta.
    """
    if actual_if is None and actual_tss is None:
        return None
        
    actual_type = classify_workout_type(actual_if, actual_duration)
    
    # Needs pg_trgm installed in db for similarity() function
    candidates = db.query("""
        SELECT *, similarity(name_lower, %(name)s) AS name_sim
        FROM tr_workout_library
        WHERE similarity(name_lower, %(name)s) > 0.45
          AND workout_type = %(wtype)s
        ORDER BY name_sim DESC LIMIT 10
    """, {"name": name.lower().strip(), "wtype": actual_type})
    
    if not candidates:
        adjacent = {
            "vo2max": ["threshold"],
            "threshold": ["sweet_spot", "vo2max"],
            "sweet_spot": ["threshold", "tempo"],
            "tempo": ["sweet_spot", "endurance"],
            "endurance": ["tempo"],
            "recovery": ["endurance"]
        }
        allowed_types = [actual_type] + adjacent.get(actual_type, [])
        candidates = db.query("""
            SELECT *, similarity(name_lower, %(name)s) AS name_sim
            FROM tr_workout_library
            WHERE similarity(name_lower, %(name)s) > 0.45
              AND workout_type = ANY(%(types)s)
            ORDER BY name_sim DESC LIMIT 10
        """, {"name": name.lower().strip(), "types": allowed_types})
        
    if not candidates:
        return None
        
    scored = []
    for c in candidates:
        score = score_tr_candidate(c, name, actual_if, actual_tss, actual_duration)
        if score["total"] >= 0.60 and not score["hard_pass"]:
            scored.append((score["total"], c, score))
            
    if not scored:
        return None
        
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_match, breakdown = scored[0]
    
    return {
        **best_match,
        "_match_score": round(best_score, 3),
        "_match_breakdown": breakdown
    }

def score_tr_candidate(candidate: dict, name: str, actual_if: Optional[float], actual_tss: Optional[float], actual_duration: Optional[float]) -> dict:
    components = {}
    hard_pass = False
    
    # ── Name similarity ──
    from difflib import SequenceMatcher
    name_sim = SequenceMatcher(None, name.lower(), candidate["name_lower"]).ratio()
    components["name"] = name_sim
    
    # ── IF delta ──
    lib_if = candidate.get("intensity_factor")
    if actual_if and lib_if:
        if_delta = abs(float(actual_if) - float(lib_if))
        if if_delta > 0.12: hard_pass = True
        elif if_delta <= 0.03: components["if"] = 1.0
        elif if_delta <= 0.06: components["if"] = 0.7
        else: components["if"] = 0.3
        
    # ── TSS delta ──
    lib_tss = candidate.get("tss")
    if actual_tss and lib_tss:
        tss_pct_delta = abs(float(actual_tss) - float(lib_tss)) / float(lib_tss)
        if tss_pct_delta > 0.30: hard_pass = True
        elif tss_pct_delta <= 0.10: components["tss"] = 1.0
        elif tss_pct_delta <= 0.20: components["tss"] = 0.6
        else: components["tss"] = 0.2
        
    # ── Duration delta ──
    lib_duration = candidate.get("duration_min")
    if actual_duration and lib_duration:
        dur_delta = abs(float(actual_duration) - float(lib_duration))
        if dur_delta <= 5: components["duration"] = 1.0
        elif dur_delta <= 10: components["duration"] = 0.7
        elif dur_delta <= 20: components["duration"] = 0.3
        
    # ── Workout type agreement ──
    actual_type = classify_workout_type(actual_if, actual_duration)
    if candidate.get("workout_type") == actual_type:
        components["workout_type"] = 1.0
    else:
        components["workout_type"] = 0.3
        
    # ── Composite score ──
    weights = {"workout_type": 0.30, "if": 0.25, "tss": 0.20, "name": 0.15, "duration": 0.10}
    total = sum(components.get(k, 0.5) * w for k, w in weights.items())
    
    return {
        "total": round(total, 3),
        "components": components,
        "hard_pass": hard_pass,
        "actual_type": actual_type,
        "lib_type": candidate.get("workout_type")
    }
