# backend/schemas/nfor.py
"""
Non-Functional Overreaching (NFOR) detection schemas.

NFORSignalSnapshot — point-in-time readiness signals for multi-week analysis
NFORAlert          — generated when 2+ signals cross threshold for 2+ weeks
NFORRecoveryBlock  — recommended recovery block parameters
"""
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class NFORSeverity(str, Enum):
    WATCH = "watch"               # 1 signal crossed — log but no alert
    WARNING = "warning"           # 2 signals crossed for 2+ weeks
    ALERT = "alert"               # 3+ signals crossed for 2+ weeks
    INTERVENTION = "intervention" # Sustained 3+ weeks at warning/alert level


class NFORCause(str, Enum):
    TRAINING_OVERLOAD = "training_overload"   # High TSS + suppressed signals
    LIFE_STRESS = "life_stress"               # Low TSS + suppressed signals → external
    ILLNESS = "illness"                       # Sudden drop + resting HR spike
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Signal snapshot — one per day
# ---------------------------------------------------------------------------
class NFORSignalSnapshot(BaseModel):
    """
    The six signals monitored over 2-4 week rolling windows.
    These are the same signals used by signal_importance.py but here we
    track them longitudinally for overreaching trend detection.
    """
    date: str
    hrv_trend: Optional[str] = Field(
        None, description="normal | suppressed | elevated"
    )
    hrv_z_score: Optional[float] = Field(
        None, description="Z-score vs 28-day mean"
    )
    execution_ratio: Optional[float] = Field(
        None, description="Avg recent execution score (0-1)"
    )
    rpe_drift: Optional[float] = Field(
        None, description="RPE trend vs session intensity — rising RPE at same load"
    )
    performance_plateau: Optional[bool] = Field(
        None, description="FTP/CSS stagnation despite progressive overload"
    )
    sleep_quality_trend: Optional[str] = Field(
        None, description="normal | declining | poor"
    )
    resting_hr_trend: Optional[str] = Field(
        None, description="normal | rising | elevated"
    )


# ---------------------------------------------------------------------------
# NFOR alert
# ---------------------------------------------------------------------------
class NFORAlert(BaseModel):
    alert_date: str
    severity: NFORSeverity
    likely_cause: NFORCause
    signals_triggered: List[str] = Field(
        default_factory=list,
        description="Names of signals that crossed threshold",
    )
    signal_details: Dict[str, float] = Field(
        default_factory=dict,
        description="Signal name → current value",
    )
    weeks_detected: int = Field(
        1, description="How many consecutive weeks signals have been elevated"
    )
    recommended_response: str = Field(
        "", description="Actionable recovery recommendation"
    )
    recovery_block: Optional["NFORRecoveryBlock"] = None


# ---------------------------------------------------------------------------
# Recovery block recommendation
# ---------------------------------------------------------------------------
class NFORRecoveryBlock(BaseModel):
    duration_weeks: int = Field(1, ge=1, le=3)
    volume_pct: float = Field(
        0.50, description="Percent of current volume e.g. 0.50 = 50%"
    )
    max_intensity: str = Field(
        "Z2", description="Cap intensity at this zone"
    )
    structure_notes: str = Field(
        "Short easy sessions, emphasis on sleep and nutrition. "
        "Include mobility and light swimming. No intervals."
    )
    resume_condition: str = Field(
        "HRV restored to baseline range for 3+ consecutive days AND "
        "execution ratio > 0.85 on easy recovery sessions"
    )


# Resolve forward reference
NFORAlert.model_rebuild()
