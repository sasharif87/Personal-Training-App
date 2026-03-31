# backend/schemas/athlete_profile.py
"""
Pydantic schemas for the athlete profile and health context.

AthleteProfile      — physiological parameters, health context, equipment, preferences
Medication          — medication entry with training effect flags
EquipmentItem       — shoe, bike, or component with mileage tracking
TrainingPreferences — rest day, session timing, weekly hour cap
HealthContext       — menstrual cycle, medications, medical notes
"""
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class MedicationClass(str, Enum):
    BETA_BLOCKER = "beta_blocker"
    ACE_INHIBITOR = "ace_inhibitor"
    CALCIUM_CHANNEL_BLOCKER = "calcium_channel_blocker"
    SSRI_SNRI = "ssri_snri"
    CORTICOSTEROID = "corticosteroid"
    THYROID = "thyroid"
    HORMONAL_CONTRACEPTIVE = "hormonal_contraceptive"
    OTHER = "other"


class CyclePhase(str, Enum):
    MENSTRUAL = "menstrual"           # Days 1-5
    FOLLICULAR = "follicular"         # Days 6-13
    OVULATION = "ovulation"           # ~Day 14
    EARLY_LUTEAL = "early_luteal"     # Days 15-21
    LATE_LUTEAL = "late_luteal"       # Days 22-28
    UNKNOWN = "unknown"
    NOT_TRACKED = "not_tracked"


class EquipmentType(str, Enum):
    RUNNING_SHOE = "running_shoe"
    ROAD_BIKE = "road_bike"
    MTB = "mtb"
    CHAIN = "chain"
    CASSETTE = "cassette"
    TYRE_TRAINING = "tyre_training"
    TYRE_RACE = "tyre_race"
    WETSUIT = "wetsuit"
    OTHER = "other"


class ContraceptiveType(str, Enum):
    NONE = "none"
    COMBINED_PILL = "combined_pill"
    IMPLANT = "implant"
    HORMONAL_IUD = "hormonal_iud"
    COPPER_IUD = "copper_iud"         # Non-hormonal — cycle model still active
    OTHER = "other"


# ---------------------------------------------------------------------------
# Medication
# ---------------------------------------------------------------------------
class Medication(BaseModel):
    name: str = Field(..., description="Medication name e.g. Metoprolol")
    medication_class: MedicationClass = Field(MedicationClass.OTHER)
    dose: str = Field("", description="Dosage e.g. 50mg daily")
    known_training_effects: str = Field(
        "", description="Known effects e.g. 'Blunts HR — max HR suppressed 10-30bpm'"
    )
    system_adjustments: List[str] = Field(
        default_factory=list,
        description="System flags: disable_hr_zones, annotate_hrv_baseline, suppress_overtraining_alerts",
    )
    start_date: Optional[str] = Field(None, description="ISO date when started")
    active: bool = True


# Medication class → default system adjustments mapping
MEDICATION_ADJUSTMENTS: Dict[str, List[str]] = {
    "beta_blocker": ["disable_hr_zones", "shift_to_rpe_power"],
    "ssri_snri": ["annotate_hrv_baseline", "suppress_overtraining_alerts"],
    "calcium_channel_blocker": ["reduce_hr_ceiling", "annotate_hr_suppression"],
    "hormonal_contraceptive": ["disable_cycle_phase_model"],
    "corticosteroid": ["flag_duration", "load_reduction_if_long_course"],
    "thyroid": ["flag_dose_change"],
}


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------
class EquipmentItem(BaseModel):
    item_id: str = Field(..., description="UUID or user-set ID")
    equipment_type: EquipmentType
    name: str = Field(..., description="e.g. 'Nike Vaporfly 3' or 'Canyon Aeroad'")
    initial_km: float = Field(0.0, description="Starting mileage at time of registration")
    current_km: float = Field(0.0, description="Current accumulated mileage")
    max_km: Optional[float] = Field(
        None, description="Lifespan threshold in km (e.g. 700 for shoes, 3000 for chain)"
    )
    status: str = Field("healthy", description="healthy | approaching | replace | overdue")
    active: bool = True
    notes: str = ""
    registered_date: Optional[str] = None
    last_activity_date: Optional[str] = None


# Default lifespan thresholds (km)
EQUIPMENT_LIFESPAN: Dict[str, float] = {
    "running_shoe": 700.0,
    "chain": 3000.0,
    "cassette": 12000.0,
    "tyre_training": 5000.0,
    "tyre_race": 0.0,   # Inspect per race — no km threshold
}


# ---------------------------------------------------------------------------
# Health context
# ---------------------------------------------------------------------------
class HealthContext(BaseModel):
    cycle_tracking_enabled: bool = Field(
        False, description="Athlete has opted in to menstrual cycle tracking"
    )
    current_cycle_phase: CyclePhase = Field(CyclePhase.NOT_TRACKED)
    cycle_day: Optional[int] = Field(None, description="Current day in cycle (1-28)")
    contraceptive_type: ContraceptiveType = Field(ContraceptiveType.NONE)
    medications: List[Medication] = Field(default_factory=list)
    medical_notes: str = Field(
        "", description="Free text, athlete-authored — encrypted at rest"
    )


# ---------------------------------------------------------------------------
# Training preferences
# ---------------------------------------------------------------------------
class TrainingPreferences(BaseModel):
    preferred_rest_day: str = Field("Friday", description="Day of week")
    morning_preference: bool = Field(
        True, description="True = prefers morning sessions"
    )
    max_weekly_hours: float = Field(12.0, description="Weekly training hour cap")
    preferred_long_day: str = Field("Saturday", description="Day for long sessions")
    indoor_temp_threshold_c: float = Field(
        -5.0, description="Below this, outdoor sessions swap to indoor"
    )


# ---------------------------------------------------------------------------
# Full athlete profile
# ---------------------------------------------------------------------------
class AthleteProfile(BaseModel):
    athlete_id: str = Field("default", description="Athlete identifier for multi-athlete support")

    # Physiological parameters
    ftp: int = Field(250, description="Functional Threshold Power (Watts) — bike, synced from Garmin")
    run_ftp: Optional[int] = Field(
        None, description="Running Functional Threshold Power (Watts) — from Stryd or Garmin Running Power"
    )
    css: str = Field("1:45/100m", description="Critical Swim Speed (pace per 100m)")
    threshold_pace: str = Field(
        "4:30/km",
        description="Run threshold pace (roughly 1-hour race pace) — used for pace-based rTSS",
    )
    lthr_run: int = Field(162, description="Lactate Threshold Heart Rate — run (BPM)")
    lthr_bike: int = Field(158, description="Lactate Threshold Heart Rate — bike (BPM)")
    weight_kg: float = Field(75.0)
    height_cm: float = Field(178.0)
    age: int = Field(35)

    # Sub-objects
    health: HealthContext = Field(default_factory=HealthContext)
    equipment: List[EquipmentItem] = Field(default_factory=list)
    preferences: TrainingPreferences = Field(default_factory=TrainingPreferences)

    # Home equipment baseline (vacation mode diffs against this)
    home_equipment: List[str] = Field(
        default_factory=lambda: [
            "road_bike", "smart_trainer", "pool_access",
            "running_shoes", "gym_access", "resistance_bands",
        ],
        description="Equipment available at home base",
    )
