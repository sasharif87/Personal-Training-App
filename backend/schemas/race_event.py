# backend/schemas/race_event.py
"""
Race event and season planning schemas.

RaceDistances      — swim/bike/run distances for multi-sport events
RaceEventFull      — complete race event with auto-calculated taper/recovery
TaperRecoveryCalc  — priority × format taper/recovery matrix
RaceResult         — post-race result with splits, conditions, analysis
"""
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Race distances
# ---------------------------------------------------------------------------
class RaceDistances(BaseModel):
    swim_m: Optional[int] = None
    bike_km: Optional[float] = None
    run_km: Optional[float] = None


# ---------------------------------------------------------------------------
# Full race event
# ---------------------------------------------------------------------------
class RaceEventFull(BaseModel):
    event_id: str
    name: str
    event_date: str = Field(..., description="ISO date YYYY-MM-DD")
    location: str = ""
    sport: str = Field("triathlon", description="triathlon | running | cycling | multisport")
    format: str = Field("Olympic", description="Olympic | 70.3 | Ironman | marathon | half_marathon | etc.")
    distance_label: str = Field("", description="Human-readable e.g. 'Olympic Distance'")
    priority: str = Field("C", description="A (peak) | B (training) | C (check)")
    distances: RaceDistances = Field(default_factory=RaceDistances)
    elevation_gain_m: Optional[int] = None
    source_url: str = ""
    extracted_at: Optional[str] = None
    taper_start: Optional[str] = Field(None, description="Auto-calculated from priority + format")
    recovery_end: Optional[str] = Field(None, description="Auto-calculated from priority + format")

    def calculate_taper_recovery(self) -> None:
        """Auto-calculate taper_start and recovery_end from priority and format."""
        taper_days, recovery_days = get_taper_recovery(self.priority, self.format)
        event = date.fromisoformat(self.event_date)
        self.taper_start = (event - timedelta(days=taper_days)).isoformat()
        self.recovery_end = (event + timedelta(days=recovery_days)).isoformat()


# ---------------------------------------------------------------------------
# Race result — post-race ingestion
# ---------------------------------------------------------------------------
class RaceResult(BaseModel):
    event_id: str
    overall_time_sec: Optional[int] = None
    placement: Optional[int] = None
    placement_ag: Optional[int] = None     # Age group placement

    # Splits by discipline
    swim_time_sec: Optional[int] = None
    t1_time_sec: Optional[int] = None
    bike_time_sec: Optional[int] = None
    t2_time_sec: Optional[int] = None
    run_time_sec: Optional[int] = None

    # Performance data
    bike_avg_power: Optional[float] = None
    bike_np: Optional[float] = None
    run_avg_pace_sec_km: Optional[float] = None
    run_pace_fade_pct: Optional[float] = Field(
        None, description="Second half pace vs first half — positive = faded"
    )

    # Conditions
    air_temp_c: Optional[float] = None
    water_temp_c: Optional[float] = None
    wind_kmh: Optional[float] = None
    wetsuit_legal: Optional[bool] = None
    conditions_notes: str = ""

    # Fueling
    fueling_plan_followed: Optional[bool] = None
    fueling_notes: str = ""

    # Subjective
    swim_feel: Optional[int] = Field(None, ge=1, le=10)
    bike_feel: Optional[int] = Field(None, ge=1, le=10)
    run_feel: Optional[int] = Field(None, ge=1, le=10)
    overall_feel: Optional[int] = Field(None, ge=1, le=10)
    athlete_notes: str = ""

    # Fitness state at race
    ctl_at_race: Optional[float] = None
    atl_at_race: Optional[float] = None
    tsb_at_race: Optional[float] = None


# ---------------------------------------------------------------------------
# Taper / recovery matrix
# ---------------------------------------------------------------------------
_TAPER_RECOVERY_MATRIX: Dict[Tuple[str, str], Tuple[int, int]] = {
    # (priority, format): (taper_days, recovery_days)
    ("A", "Ironman"):         (14, 21),
    ("A", "70.3"):            (12, 14),
    ("A", "Olympic"):         (10, 7),
    ("A", "marathon"):        (14, 14),
    ("A", "half_marathon"):   (10, 7),
    ("A", "Endurance Run"):   (10, 10),
    ("A", "Triple Bypass"):   (10, 14),
    ("A", "Other"):           (7, 7),
    ("B", "Ironman"):         (7, 7),
    ("B", "70.3"):            (5, 5),
    ("B", "Olympic"):         (5, 3),
    ("B", "marathon"):        (7, 5),
    ("B", "half_marathon"):   (5, 3),
    ("B", "Endurance Run"):   (5, 5),
    ("B", "Triple Bypass"):   (5, 7),
    ("B", "Other"):           (5, 3),
    ("C", "Olympic"):         (2, 1),
    ("C", "half_marathon"):   (2, 1),
    ("C", "70.3"):            (3, 2),
    ("C", "Other"):           (2, 1),
}


def get_taper_recovery(priority: str, format: str) -> Tuple[int, int]:
    """Return (taper_days, recovery_days) for a priority + format combination."""
    return _TAPER_RECOVERY_MATRIX.get((priority, format), (7, 5))
