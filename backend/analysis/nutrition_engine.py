# backend/analysis/nutrition_engine.py
"""
Nutrition and fueling engine.

Calculates:
  - Caloric expenditure from TSS and power data
  - Per-session fueling targets (carbs, fluid, sodium) by duration band
  - Race day fueling plans (A-race detail with segment-by-segment targets)
  - Fueling compliance scoring (mirrors execution scoring pattern)
  - Gut training escalation tracking for IM/70.3 builds
"""

import logging
from typing import Any, Dict, List, Optional

from backend.schemas.nutrition import (
    FuelingTargets,
    RaceDayFuelingPlan,
    RaceDaySegmentPlan,
    FuelingCompliance,
    CalorieEstimate,
    GutTrainingProgress,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Caloric expenditure estimation
# ---------------------------------------------------------------------------
def estimate_calories(
    tss: float,
    ftp: int,
    sport: str,
    duration_sec: int,
    avg_power: Optional[float] = None,
) -> CalorieEstimate:
    """
    Estimate caloric expenditure for a session.

    Methods:
      Power-based (bike):  kJ = avg_power × duration_sec / 1000
                           kcal ≈ kJ / 0.25 (human efficiency ~25%)
      TSS-based (fallback): kcal ≈ TSS × (FTP × 3.6) / 100
                           Rough but serviceable when no power available.
    """
    if sport == "bike" and avg_power and avg_power > 0:
        # Direct kJ calculation from power
        kj = avg_power * duration_sec / 1000
        kcal = round(kj / 0.25, 0)  # ~25% gross mechanical efficiency
        return CalorieEstimate(
            session_date="",
            sport=sport,
            duration_sec=duration_sec,
            tss=tss,
            ftp=ftp,
            estimated_kj=round(kj, 0),
            estimated_kcal=kcal,
            method="power_based",
        )

    # TSS-based estimation for all sports
    # Approximate: 1 TSS at threshold ≈ 10-12 kcal for a 75kg athlete at 250W FTP
    kcal_per_tss = max(8, ftp / 25)  # Scale with FTP
    estimated_kcal = round(tss * kcal_per_tss, 0)
    estimated_kj = round(estimated_kcal * 0.25, 0)

    return CalorieEstimate(
        session_date="",
        sport=sport,
        duration_sec=duration_sec,
        tss=tss,
        ftp=ftp,
        estimated_kj=estimated_kj,
        estimated_kcal=estimated_kcal,
        method="tss_based",
    )


# ---------------------------------------------------------------------------
# Fueling targets by duration band
# ---------------------------------------------------------------------------
def generate_fueling_targets(
    duration_min: float,
    sport: str,
    intensity: str = "moderate",
) -> FuelingTargets:
    """
    Generate fueling targets based on session duration and intensity.

    Duration bands (from architecture doc):
      < 60 min:  water only, optional electrolyte
      60-90 min: 30-60g carbs/hr
      90-180 min: 60-90g carbs/hr, practiced tolerable rate
      > 180 min: 80-120g carbs/hr (race target), requires gut training
    """
    # Carb targets (g/hr)
    if duration_min < 60:
        carb = 0.0
        notes = "Water only; optional electrolyte tab if hot"
    elif duration_min < 90:
        carb = 30.0 if intensity == "easy" else 45.0
        notes = "1 gel per 30-40min or sports drink"
    elif duration_min < 180:
        carb = 60.0 if intensity in ("easy", "moderate") else 80.0
        notes = "Mix of gels + sports drink. Practice race-day products."
    else:
        carb = 80.0 if intensity != "race" else 100.0
        notes = (
            "Race-level fueling — requires gut training. "
            "Alternate gels + drink mix + real food. "
            "Start within first 30min."
        )

    # Fluid targets (ml/hr)
    base_fluid = 500 if intensity in ("easy", "moderate") else 700
    # Swimming doesn't need as much fluid unless long open water
    if sport == "swim":
        base_fluid = 250

    # Sodium targets (mg/hr)
    sodium = 500 if intensity in ("easy", "moderate") else 750

    return FuelingTargets(
        session_duration_min=duration_min,
        sport=sport,
        intensity=intensity,
        carb_target_g_per_hr=carb,
        fluid_target_ml_per_hr=float(base_fluid),
        sodium_target_mg_per_hr=float(sodium),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Race day fueling plan
# ---------------------------------------------------------------------------
def generate_race_day_plan(
    event: Dict[str, Any],
    athlete_weight_kg: float = 75.0,
) -> RaceDayFuelingPlan:
    """
    Generate a comprehensive race-day fueling plan.
    Uses well-established triathlon nutrition guidelines.
    """
    race_format = event.get("format", "Olympic")
    event_name = event.get("name", "Race")
    race_date = event.get("event_date", "")

    # Duration estimates by format
    _est_durations = {
        "Olympic":       {"swim": 25, "t1": 3, "bike": 75, "t2": 2, "run": 50},
        "70.3":          {"swim": 40, "t1": 5, "bike": 165, "t2": 3, "run": 120},
        "Ironman":       {"swim": 70, "t1": 8, "bike": 330, "t2": 5, "run": 270},
        "marathon":      {"swim": 0, "t1": 0, "bike": 0, "t2": 0, "run": 240},
        "half_marathon":  {"swim": 0, "t1": 0, "bike": 0, "t2": 0, "run": 110},
    }
    durations = _est_durations.get(race_format, _est_durations["Olympic"])

    segments = []

    # Pre-race
    segments.append(RaceDaySegmentPlan(
        segment="pre_race",
        carb_g=round(athlete_weight_kg * 1.5),  # 1-2g/kg 3hr before
        fluid_ml=500,
        sodium_mg=300,
        products="Oatmeal + banana + honey, coffee, water",
        timing_notes=f"3 hours before start. Small top-up (gel + water) 15min pre-start.",
    ))

    # Swim (minimal fueling, just hydrate after)
    if durations["swim"] > 0:
        segments.append(RaceDaySegmentPlan(
            segment="swim",
            duration_min=durations["swim"],
            carb_g=0,
            fluid_ml=0,
            sodium_mg=0,
            timing_notes="No fueling during swim — hydrate in T1",
        ))

    # T1
    if durations["t1"] > 0:
        segments.append(RaceDaySegmentPlan(
            segment="t1",
            duration_min=durations["t1"],
            carb_g=20,
            fluid_ml=200,
            sodium_mg=100,
            products="Sips of sports drink, gel if stomach settled",
        ))

    # Bike — where most race nutrition happens
    if durations["bike"] > 0:
        bike_hours = durations["bike"] / 60
        target_carb_rate = 90.0 if race_format in ("70.3", "Ironman") else 60.0
        segments.append(RaceDaySegmentPlan(
            segment="bike",
            duration_min=durations["bike"],
            carb_g=round(target_carb_rate * bike_hours),
            fluid_ml=round(600 * bike_hours),
            sodium_mg=round(600 * bike_hours),
            products="Sports drink in bottles + gels every 30min + bar every 60min (if IM)",
            timing_notes=f"Target {target_carb_rate:.0f}g/hr. Start within first 15min. Set timer.",
        ))

    # T2
    if durations["t2"] > 0:
        segments.append(RaceDaySegmentPlan(
            segment="t2",
            duration_min=durations["t2"],
            carb_g=25,
            fluid_ml=150,
            sodium_mg=100,
            products="Gel + water — quick swap, don't linger",
        ))

    # Run
    if durations["run"] > 0:
        run_hours = durations["run"] / 60
        run_carb_rate = 60.0 if race_format in ("70.3", "Ironman") else 30.0
        segments.append(RaceDaySegmentPlan(
            segment="run",
            duration_min=durations["run"],
            carb_g=round(run_carb_rate * run_hours),
            fluid_ml=round(400 * run_hours),
            sodium_mg=round(500 * run_hours),
            products="Cola + gels + pretzels at aid stations. Alternate water and sports drink.",
            timing_notes=f"Target {run_carb_rate:.0f}g/hr. Take from every aid station.",
        ))

    carb_load_days = 2 if race_format in ("Olympic", "half_marathon") else 3

    return RaceDayFuelingPlan(
        event_id=event.get("event_id", ""),
        event_name=event_name,
        race_date=race_date,
        carb_load_days=carb_load_days,
        carb_load_target_g_per_kg=8.0 if race_format in ("Ironman", "70.3") else 6.0,
        race_morning_meal_hr_before=3.0,
        race_morning_carb_g=round(athlete_weight_kg * 1.5),
        race_morning_caffeine_mg=200 if athlete_weight_kg < 90 else 250,
        segments=segments,
    )


# ---------------------------------------------------------------------------
# Fueling compliance scoring
# ---------------------------------------------------------------------------
def score_fueling_compliance(
    planned_carb_g: float,
    actual_carb_g: Optional[float],
    planned_fluid_ml: float,
    actual_fluid_ml: Optional[float],
    gi_distress: bool = False,
) -> Dict[str, Any]:
    """
    Score fueling compliance — mirrors the execution scoring pattern.
    Returns ratios and flags.
    """
    carb_ratio = None
    fluid_ratio = None
    flags = []

    if planned_carb_g > 0 and actual_carb_g is not None:
        carb_ratio = round(actual_carb_g / planned_carb_g, 3)
        if carb_ratio < 0.70:
            flags.append("UNDER_FUELED")
        elif carb_ratio > 1.30:
            flags.append("OVER_FUELED")

    if planned_fluid_ml > 0 and actual_fluid_ml is not None:
        fluid_ratio = round(actual_fluid_ml / planned_fluid_ml, 3)
        if fluid_ratio < 0.60:
            flags.append("DEHYDRATED")

    if gi_distress:
        flags.append("GI_DISTRESS")

    return {
        "carb_ratio": carb_ratio,
        "fluid_ratio": fluid_ratio,
        "gi_distress": gi_distress,
        "flags": flags,
        "on_target": carb_ratio is not None and 0.85 <= carb_ratio <= 1.15 and not gi_distress,
    }


# ---------------------------------------------------------------------------
# Gut training tracker
# ---------------------------------------------------------------------------
def update_gut_training(
    progress: GutTrainingProgress,
    session_carb_g_per_hr: float,
    gi_issues: bool,
    session_id: str = "",
) -> GutTrainingProgress:
    """
    Update gut training progress after a long session.
    Escalates tolerated rate when successful, backs off on GI distress.
    """
    from datetime import date as d

    entry = {
        "date": d.today().isoformat(),
        "session_id": session_id,
        "carb_g_per_hr": session_carb_g_per_hr,
        "gi_issues": gi_issues,
    }
    progress.escalation_log.append(entry)

    if not gi_issues and session_carb_g_per_hr >= progress.current_max_tolerated_g_per_hr:
        # Escalate by 5g/hr per successful session
        progress.current_max_tolerated_g_per_hr = min(
            progress.current_max_tolerated_g_per_hr + 5,
            progress.target_carb_g_per_hr + 10,  # Allow slight overshoot
        )
    elif gi_issues:
        # Back off by 10g/hr
        progress.current_max_tolerated_g_per_hr = max(
            progress.current_max_tolerated_g_per_hr - 10,
            30.0,  # Floor
        )

    # Check readiness: tolerated >= target for 3+ consecutive sessions without GI
    recent = progress.escalation_log[-3:]
    if len(recent) >= 3:
        progress.ready_for_race = all(
            e["carb_g_per_hr"] >= progress.target_carb_g_per_hr and not e["gi_issues"]
            for e in recent
        )

    return progress
