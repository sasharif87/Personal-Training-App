# backend/schemas/workout.py
"""
Pydantic schemas for workout plan output.

WorkoutStep     — a single effort block (interval, warmup, etc.)
Session         — a full training session made up of steps, with optional conditional_alt
DayPlan         — a single training day (primary session + optional alt)
MonthPlan       — a full monthly mesocycle (4–5 weeks) as produced by monthly generation
PlannedSession  — unified planned session schema from any source platform
ExecutionScore  — result of comparing a planned session to a completed activity
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Step-level schema
# ---------------------------------------------------------------------------
class WorkoutStep(BaseModel):
    type: str = Field(..., description="warmup, interval, recovery, cooldown, strength")
    duration_sec: Optional[int] = Field(None, description="Step duration in seconds")
    distance_m: Optional[float] = Field(None, description="Step distance in meters")
    target_value: float = Field(..., description="Power fraction (FTP) or Pace fraction (CSS) or HR fraction (LTHR)")
    target_type: str = Field(..., description="power, pace, hr")
    repeat: int = Field(1, description="Number of times to repeat this step")
    description: Optional[str] = Field(None, description="Coaching text for this step")

# ---------------------------------------------------------------------------
# Session schema — primary or alt
# ---------------------------------------------------------------------------
class Session(BaseModel):
    sport: str = Field(..., description="swim, bike, run, brick, strength, climb, yoga, mobility")
    title: str
    description: str
    rationale: str = Field(..., description="Coach's reason for this specific session choice")
    steps: List[WorkoutStep]
    estimated_tss: float = Field(0.0, description="Training Stress Score estimate")
    alt_trigger: Optional[str] = Field(
        None,
        description="Condition string that surfaces the alt, e.g. 'HRV suppressed OR sleep < 0.65'"
    )
    alt_rationale: Optional[str] = Field(
        None,
        description="Why the alt is structured differently — what coaching intent it preserves"
    )

# ---------------------------------------------------------------------------
# Day plan — primary + optional conditional alt
# ---------------------------------------------------------------------------
class DayPlan(BaseModel):
    day: str = Field(..., description="Monday, Tuesday, etc.")
    date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD")
    primary: Optional[Session] = None
    conditional_alt: Optional[Session] = Field(
        None,
        description="Alternative session pre-authored at generation time for use when fatigue signals conflict"
    )
    rest_day: bool = Field(False, description="True if this is a scheduled rest day")
    rest_rationale: Optional[str] = None

# ---------------------------------------------------------------------------
# Weekly plan schema — used by weekly review tier
# ---------------------------------------------------------------------------
class WeekPlan(BaseModel):
    week_number: int
    block_phase: str
    target_tss: Optional[float] = None
    days: Optional[List[DayPlan]] = None
    # Legacy flat list — kept for compatibility with existing pipeline output
    sessions: List[Session] = Field(default_factory=list)
    weekly_rationale: str
    predicted_ctl_end: Optional[float] = None

# ---------------------------------------------------------------------------
# Monthly plan — full mesocycle from monthly generation
# ---------------------------------------------------------------------------
class MonthPlan(BaseModel):
    block_phase: str
    month_rationale: str
    weeks: List[WeekPlan]
    generated_at: Optional[str] = None

# ---------------------------------------------------------------------------
# Planned session — unified schema from any source platform
# ---------------------------------------------------------------------------
class PlannedSession(BaseModel):
    session_id: str = Field(..., description="UUID or platform-native ID")
    source_platform: str = Field(..., description="trainingpeaks | trainerroad | zwift | garmin | system")
    import_method: str = Field("unknown", description="api | file_watch | manual_upload | fit_name_lookup | unknown")
    planned_date: str = Field(..., description="ISO date YYYY-MM-DD")
    sport: str
    title: str
    coaching_text: str = Field("", description="Original coaching intent text from source platform")
    planned_duration_min: Optional[float] = None
    planned_tss: Optional[float] = None
    planned_if: Optional[float] = Field(None, description="Intensity factor — null for non-power sports")
    planned_distance_m: Optional[float] = None
    planned_elevation_m: Optional[float] = None
    structure: Dict[str, Any] = Field(default_factory=dict, description="Warmup/main_sets/cooldown structure")
    targets: Dict[str, Any] = Field(default_factory=dict, description="hr_zone, power_zone, pace_zone, rpe_target")
    # Execution data once matched
    executed: bool = False
    garmin_activity_id: Optional[str] = None

# ---------------------------------------------------------------------------
# Execution score — result of plan vs actual comparison
# ---------------------------------------------------------------------------
class ExecutionScore(BaseModel):
    session_date: str
    sport: str
    planned_session_id: Optional[str] = None
    # Ratios and deltas
    tss_ratio: Optional[float] = Field(None, description="actual_tss / planned_tss — 0.94 = 94% completed")
    duration_ratio: Optional[float] = None
    if_delta: Optional[float] = Field(None, description="actual_if - planned_if — positive = went harder")
    set_completion: Optional[float] = Field(None, description="Fraction of planned sets completed")
    overall_execution: Optional[float] = Field(None, description="Weighted composite 0–1")
    # Flags
    flags: List[str] = Field(default_factory=list, description="OVERCOOKED, UNDERDELIVERED, TOO_HARD, BAILED, etc.")
    # Raw values for context
    actual_tss: Optional[float] = None
    planned_tss: Optional[float] = None
    notes: str = ""
