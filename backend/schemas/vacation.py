# backend/schemas/vacation.py
"""
Vacation, travel, and training retreat schemas.

VacationWindow     — date range with equipment and location context
EquipmentChecklist — what's available at the travel destination
RetreatConfig      — training camp / retreat configuration
EnvironmentalFactors — heat, altitude, timezone adjustments
"""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class VacationType(str, Enum):
    ACTIVE_VACATION = "active_vacation"     # Maintenance training
    REST_VACATION = "rest_vacation"          # Complete rest / light activity only
    TRAINING_RETREAT = "training_retreat"    # Camp / focused training block
    WORK_TRAVEL = "work_travel"             # Business trip — constrained sessions


class EquipmentChecklist(BaseModel):
    """Available equipment at travel destination."""
    road_bike: bool = False
    smart_trainer: bool = False
    pool_access: bool = False
    open_water_access: bool = False
    gym_access: bool = False
    hotel_gym: bool = False         # Typically limited — bodyweight + cardio only
    running_shoes: bool = True      # Almost always true
    resistance_bands: bool = False
    wetsuit: bool = False
    race_bike: bool = False         # For retreats only


class EnvironmentalFactors(BaseModel):
    """Environmental conditions at destination — affects pacing and hydration."""
    avg_temp_c: Optional[float] = Field(
        None, description="Expected average temperature"
    )
    altitude_m: Optional[int] = Field(
        None, description="Destination altitude in metres"
    )
    timezone_offset_hr: Optional[float] = Field(
        None, description="Hours offset from home timezone (positive = east)"
    )
    humidity_high: bool = Field(False, description="Expected high humidity (>70%)")

    def heat_adjustment_pct(self) -> float:
        """Return pace/power reduction % for heat."""
        if self.avg_temp_c is None:
            return 0.0
        if self.avg_temp_c >= 35:
            return 15.0   # Extreme — significant reduction
        if self.avg_temp_c >= 32:
            return 10.0
        if self.avg_temp_c >= 28:
            return 5.0
        return 0.0

    def altitude_adjustment_pct(self, day_at_altitude: int = 1) -> float:
        """
        Return intensity reduction % for altitude.
        Days 1-3: full reduction. Days 4-7: half. Day 8+: minimal.
        """
        if not self.altitude_m or self.altitude_m < 1200:
            return 0.0
        base_reduction = min((self.altitude_m - 1200) / 100, 15.0)  # Cap at 15%
        if day_at_altitude <= 3:
            return base_reduction
        if day_at_altitude <= 7:
            return base_reduction * 0.5
        return base_reduction * 0.25


class VacationWindow(BaseModel):
    vacation_id: str
    start_date: str = Field(..., description="ISO date")
    end_date: str = Field(..., description="ISO date")
    vacation_type: VacationType = VacationType.ACTIVE_VACATION
    location: str = ""
    equipment: EquipmentChecklist = Field(default_factory=EquipmentChecklist)
    environment: EnvironmentalFactors = Field(default_factory=EnvironmentalFactors)
    notes: str = ""

    # Pre/post vacation blocks
    pre_travel_buffer_days: int = Field(
        1, description="Days before departure with reduced load"
    )
    post_travel_recovery_days: int = Field(
        1, description="Days after return before normal load resumes"
    )


class RetreatConfig(BaseModel):
    """
    Training camp / retreat — a focused training block at a specific location.
    Examples: swim camp at altitude, cycling camp in Mallorca, IM race-week simulation.
    """
    retreat_id: str
    name: str
    start_date: str
    end_date: str
    location: str

    # Facility details
    equipment: EquipmentChecklist = Field(default_factory=EquipmentChecklist)
    coaching_on_site: bool = False
    group_sessions: bool = False

    # Training parameters
    daily_target_hours: float = Field(4.0, description="Target daily training hours")
    primary_sport_focus: str = Field("", description="swim | bike | run | multi")
    altitude_m: Optional[int] = None

    # Block structure
    pre_retreat_taper_days: int = Field(
        3, description="Taper days before retreat for freshness"
    )
    post_retreat_recovery_days: int = Field(
        3, description="Recovery days after retreat"
    )

    # Daily structure template
    daily_structure: str = Field(
        "AM: primary sport (structured)\n"
        "PM: secondary sport or recovery\n"
        "Evening: mobility + stretching",
    )

    notes: str = ""
