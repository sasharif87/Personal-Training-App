# backend/schemas/workout.py
"""
Pydantic schemas for workout plan output.

Defines the structured response the LLM must return:
  WorkoutStep  — a single effort block (interval, warmup, etc.)
  Session      — a full training session made up of steps
  WeekPlan     — a full week of sessions for one training block
"""
from typing import List, Optional
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Step-level schema
# ---------------------------------------------------------------------------
class WorkoutStep(BaseModel):
    type: str = Field(..., description="warmup, interval, recovery, cooldown, strength")
    duration_sec: Optional[int] = Field(None, description="Step duration in seconds")
    distance_m: Optional[float] = Field(None, description="Step distance in meters")
    target_value: float = Field(..., description="Power fraction (FTP) or Pace fraction (CSS/LTHR)")
    target_type: str = Field(..., description="power, pace, hr")
    repeat: int = Field(1, description="Number of times to repeat this step")
    description: Optional[str] = Field(None, description="Coaching text for this step")

# ---------------------------------------------------------------------------
# Session schema
# ---------------------------------------------------------------------------
class Session(BaseModel):
    sport: str = Field(..., description="swim, bike, run, brick, strength")
    title: str
    description: str
    rationale: str = Field(..., description="Coach's reason for this specific session choice")
    steps: List[WorkoutStep]
    estimated_tss: float = Field(0.0, description="Training Stress Score estimate")

# ---------------------------------------------------------------------------
# Weekly plan schema
# ---------------------------------------------------------------------------
class WeekPlan(BaseModel):
    week_number: int
    block_phase: str
    sessions: List[Session]
    weekly_rationale: str
