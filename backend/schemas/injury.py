# backend/schemas/injury.py
"""
Injury tracking and post-session wellness logging schemas.

PostSessionLog — low-friction post-workout entry (RPE, leg feel, pain, motivation)
PainEntry      — body map based pain entry
BodyMapLocation — anatomical location enum
InjuryRecord   — longer-term injury tracking for pattern detection
"""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Body map locations (anterior + posterior)
# ---------------------------------------------------------------------------
class BodyMapLocation(str, Enum):
    # Lower body — most common for triathletes
    LEFT_CALF = "left_calf"
    RIGHT_CALF = "right_calf"
    LEFT_SHIN = "left_shin"
    RIGHT_SHIN = "right_shin"
    LEFT_KNEE = "left_knee"
    RIGHT_KNEE = "right_knee"
    LEFT_QUAD = "left_quad"
    RIGHT_QUAD = "right_quad"
    LEFT_HAMSTRING = "left_hamstring"
    RIGHT_HAMSTRING = "right_hamstring"
    LEFT_HIP = "left_hip"
    RIGHT_HIP = "right_hip"
    LEFT_ANKLE = "left_ankle"
    RIGHT_ANKLE = "right_ankle"
    LEFT_FOOT = "left_foot"
    RIGHT_FOOT = "right_foot"
    LEFT_ACHILLES = "left_achilles"
    RIGHT_ACHILLES = "right_achilles"
    LEFT_IT_BAND = "left_it_band"
    RIGHT_IT_BAND = "right_it_band"
    LEFT_GLUTE = "left_glute"
    RIGHT_GLUTE = "right_glute"

    # Upper body
    LEFT_SHOULDER = "left_shoulder"
    RIGHT_SHOULDER = "right_shoulder"
    NECK = "neck"
    LOWER_BACK = "lower_back"
    UPPER_BACK = "upper_back"
    LEFT_WRIST = "left_wrist"
    RIGHT_WRIST = "right_wrist"
    LEFT_ELBOW = "left_elbow"
    RIGHT_ELBOW = "right_elbow"

    # Core
    ABDOMEN = "abdomen"
    CHEST = "chest"
    RIBS = "ribs"

    OTHER = "other"


class PainType(str, Enum):
    DULL_ACHE = "dull_ache"
    SHARP = "sharp"
    BURNING = "burning"
    TIGHTNESS = "tightness"
    STIFFNESS = "stiffness"
    NUMBNESS = "numbness"
    SWELLING = "swelling"
    CLICKING = "clicking"
    CRAMPING = "cramping"
    OTHER = "other"


class OnsetTiming(str, Enum):
    DURING_WARMUP = "during_warmup"
    DURING_INTERVALS = "during_intervals"
    POST_SESSION = "post_session"
    NEXT_MORNING = "next_morning"
    GRADUAL = "gradual"
    SUDDEN = "sudden"
    PRE_EXISTING = "pre_existing"


# ---------------------------------------------------------------------------
# Pain entry
# ---------------------------------------------------------------------------
class PainEntry(BaseModel):
    location: BodyMapLocation
    pain_type: PainType = PainType.DULL_ACHE
    severity: int = Field(1, ge=1, le=10, description="1 = barely noticeable, 10 = cannot continue")
    onset: OnsetTiming = OnsetTiming.POST_SESSION
    altered_mechanics: bool = Field(
        False, description="Did this pain change your gait/stroke/form?"
    )
    during_activity: bool = Field(
        False, description="Was pain present during the session?"
    )
    notes: str = ""


# ---------------------------------------------------------------------------
# Post-session log — the low-friction daily entry
# ---------------------------------------------------------------------------
class PostSessionLog(BaseModel):
    """
    Minimal post-session entry designed for maximum compliance.
    Meant to be filled in 30-60 seconds via phone notification.

    Only RPE is truly required — everything else is optional to keep friction low.
    """
    session_date: str = Field(..., description="ISO date")
    sport: str = ""
    session_id: Optional[str] = Field(
        None, description="Links to planned_sessions.session_id if matched"
    )

    # Core rating — required
    rpe: int = Field(..., ge=1, le=10, description="Session RPE (1-10)")

    # Leg/body feel — optional but valuable
    leg_feel: Optional[int] = Field(
        None, ge=1, le=10,
        description="1 = heavy/dead legs, 10 = fresh and springy",
    )
    motivation: Optional[int] = Field(
        None, ge=1, le=10,
        description="1 = had to force myself, 10 = couldn't wait to go",
    )

    # Pain data — optional, only if something hurt
    pain_entries: List[PainEntry] = Field(default_factory=list)

    # Free text — keep it short
    notes: str = Field("", description="Short notes e.g. 'Left calf tight after km 8'")


# ---------------------------------------------------------------------------
# Injury record — for pattern detection over time
# ---------------------------------------------------------------------------
class InjuryRecord(BaseModel):
    injury_id: str
    location: BodyMapLocation
    description: str
    first_logged: str = Field(..., description="ISO date when first reported")
    last_logged: Optional[str] = Field(None, description="ISO date of most recent occurrence")
    occurrence_count: int = 1
    avg_severity: float = 1.0
    resolved: bool = False
    load_at_onset: Optional[float] = Field(
        None, description="CTL at time of first occurrence"
    )
    sport_at_onset: Optional[str] = None
    notes: str = ""
