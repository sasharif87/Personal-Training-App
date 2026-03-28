from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class AthleteState(BaseModel):
    ftp: int = Field(..., description="Functional Threshold Power (Watts)")
    css: str = Field(..., description="Critical Swim Speed (Pace per 100m)")
    lthr_run: int = Field(..., description="Lactate Threshold Heart Rate (BPM)")
    ctl: float = Field(..., description="Chronic Training Load (Fitness)")
    atl: float = Field(..., description="Acute Training Load (Fatigue)")
    tsb: float = Field(..., description="Training Stress Balance (Form)")
    hrv_trend: str = Field(..., description="Historical HRV trend: normal, suppressed, elevated")

class RaceEvent(BaseModel):
    date: str
    format: str = Field(..., description="Olympic, Ironman, 70.3, etc.")
    priority: str = Field(..., description="A (Peak), B (Training), C (Check)")

class TrainingBlock(BaseModel):
    phase: str = Field(..., description="Base, Build, Peak, Taper")
    week_in_block: int
    weeks_to_race: int
    target_race: RaceEvent

class ContextAssembler(BaseModel):
    athlete: AthleteState
    block: TrainingBlock
    yesterday_actual: Dict[str, Any]
    retrieved_history: List[Dict[str, Any]] = Field(default_factory=list)
    ftp_advisory: Optional[str] = None
