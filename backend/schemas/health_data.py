# backend/schemas/health_data.py
"""
Health platform integration schemas.

HealthDataPost     — payload from iOS Shortcut / Android Tasker companion
MedicationLogEntry — medication taken/skipped log
CycleData          — menstrual cycle phase data from health apps
SupplementalMetric — additional metrics not in Garmin (CGM, etc.)
"""
from typing import List, Optional
from pydantic import BaseModel, Field

from backend.schemas.athlete_profile import CyclePhase


# ---------------------------------------------------------------------------
# Medication log entry
# ---------------------------------------------------------------------------
class MedicationLogEntry(BaseModel):
    medication_name: str
    taken: bool = True
    dose: str = ""
    timestamp: str = Field(..., description="ISO datetime")
    notes: str = ""


# ---------------------------------------------------------------------------
# Cycle data from health apps
# ---------------------------------------------------------------------------
class CycleData(BaseModel):
    phase: CyclePhase = Field(CyclePhase.UNKNOWN)
    cycle_day: Optional[int] = Field(None, ge=1, le=45)
    flow_intensity: Optional[str] = Field(
        None, description="none | light | medium | heavy"
    )
    predicted_ovulation_date: Optional[str] = None
    source_app: str = Field("", description="Clue | Flo | Natural Cycles | Apple Health | etc.")
    timestamp: str = Field(..., description="ISO datetime")


# ---------------------------------------------------------------------------
# Supplemental metrics not in Garmin
# ---------------------------------------------------------------------------
class SupplementalMetric(BaseModel):
    metric_name: str = Field(..., description="blood_glucose | skin_temp | spo2 | etc.")
    value: float
    unit: str = ""
    timestamp: str = Field(..., description="ISO datetime")
    source: str = Field("", description="Dexcom | Libre | Apple Watch | etc.")


# ---------------------------------------------------------------------------
# Full health data post — companion app → server
# ---------------------------------------------------------------------------
class HealthDataPost(BaseModel):
    """
    Payload received from iOS Shortcut or Android Tasker via
    POST /api/health-data over Tailscale.

    Scheduled daily. All fields optional — companion sends what it has.
    """
    athlete_id: str = Field("default")
    timestamp: str = Field(..., description="ISO datetime of the sync")

    # Menstrual cycle
    cycle_data: Optional[CycleData] = None

    # Medication log
    medication_entries: List[MedicationLogEntry] = Field(default_factory=list)

    # Supplemental metrics
    supplemental_metrics: List[SupplementalMetric] = Field(default_factory=list)

    # Resting metrics that might come from Apple Watch instead of Garmin
    apple_resting_hr: Optional[float] = None
    apple_hrv: Optional[float] = None
    apple_vo2max: Optional[float] = None
    apple_respiratory_rate: Optional[float] = None
