# backend/schemas/nutrition.py
"""
Nutrition and fueling schemas.

FuelingTargets       — carb/fluid targets for a session
RaceDayFuelingPlan   — comprehensive race nutrition plan
FuelingCompliance    — planned vs actual fueling for sessions > 90min
CalorieEstimate      — caloric expenditure estimation
"""
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Per-session fueling targets
# ---------------------------------------------------------------------------
class FuelingTargets(BaseModel):
    """
    Auto-generated fueling targets based on session duration and intensity.

    Duration bands (from architecture doc):
      < 60 min:  water only, optional electrolyte
      60-90 min: 30-60g carbs/hr
      90-180 min: 60-90g carbs/hr, aim for practiced tolerable rate
      > 180 min: 80-120g carbs/hr (race target), requires gut training
    """
    session_duration_min: float
    sport: str
    intensity: str = Field("moderate", description="easy | moderate | hard | race")

    carb_target_g_per_hr: float = 0.0
    fluid_target_ml_per_hr: float = 500.0
    sodium_target_mg_per_hr: float = 500.0
    caffeine_mg: Optional[float] = Field(None, description="If applicable (e.g. race morning)")

    notes: str = ""


# ---------------------------------------------------------------------------
# Race day fueling plan
# ---------------------------------------------------------------------------
class RaceDaySegmentPlan(BaseModel):
    segment: str = Field(..., description="pre_race | swim | t1 | bike | t2 | run")
    duration_min: Optional[float] = None
    carb_g: float = 0.0
    fluid_ml: float = 0.0
    sodium_mg: float = 0.0
    products: str = Field("", description="Specific product names/types")
    timing_notes: str = ""


class RaceDayFuelingPlan(BaseModel):
    event_id: str
    event_name: str
    race_date: str

    # Pre-race loading
    carb_load_days: int = Field(2, description="Days of carb loading pre-race")
    carb_load_target_g_per_kg: float = Field(8.0, description="Target g/kg/day during loading")

    # Race morning
    race_morning_meal_hr_before: float = Field(3.0)
    race_morning_carb_g: float = Field(120.0)
    race_morning_caffeine_mg: float = Field(200.0)

    # Per-segment plans
    segments: List[RaceDaySegmentPlan] = Field(default_factory=list)

    # Contingency
    gi_distress_protocol: str = Field(
        "Reduce to sips of water only for 10-15min, then restart at 50% rate. "
        "Switch to cola + pretzels if gels are not tolerable."
    )
    hot_weather_adjustment: str = Field(
        "Increase fluid by 25%, add extra sodium (500mg/hr), reduce intensity 3-5%"
    )

    notes: str = ""


# ---------------------------------------------------------------------------
# Fueling compliance — post-session
# ---------------------------------------------------------------------------
class FuelingCompliance(BaseModel):
    """
    Tracks planned vs actual fueling for sessions > 90 minutes.
    Similar pattern to execution scoring.
    """
    session_date: str
    session_id: Optional[str] = None
    sport: str
    duration_min: float

    # Planned
    planned_carb_g: float = 0.0
    planned_fluid_ml: float = 0.0

    # Actual (self-reported or from watch if available)
    actual_carb_g: Optional[float] = None
    actual_fluid_ml: Optional[float] = None

    # Ratios (like execution scoring)
    carb_ratio: Optional[float] = Field(
        None, description="actual / planned — 1.0 = on target"
    )
    fluid_ratio: Optional[float] = Field(
        None, description="actual / planned"
    )

    # GI issues
    gi_distress: bool = False
    gi_notes: str = ""


# ---------------------------------------------------------------------------
# Caloric expenditure estimate
# ---------------------------------------------------------------------------
class CalorieEstimate(BaseModel):
    session_date: str
    sport: str
    duration_sec: int
    tss: float
    ftp: int
    estimated_kj: float
    estimated_kcal: float
    method: str = Field("tss_based", description="tss_based | power_based | hr_based")


# ---------------------------------------------------------------------------
# Gut training tracker
# ---------------------------------------------------------------------------
class GutTrainingProgress(BaseModel):
    """
    Tracks carb intake escalation across long sessions for race readiness.
    Used during IM/70.3 build phases.
    """
    athlete_id: str = "default"
    target_race_format: str = "70.3"
    target_carb_g_per_hr: float = Field(90.0, description="Race target")
    current_max_tolerated_g_per_hr: float = Field(
        60.0, description="Current max tolerated without GI issues"
    )
    escalation_log: List[Dict] = Field(
        default_factory=list,
        description="List of {date, session_id, carb_g_per_hr, gi_issues: bool}",
    )
    ready_for_race: bool = Field(
        False, description="True when tolerated rate >= target rate for 3+ sessions"
    )
