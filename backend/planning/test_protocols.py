# backend/planning/test_protocols.py
"""
Testing protocol generation — FTP, CSS, LTHR structured workouts.

Generates structured test workouts that can be:
  1. Written as .zwo for Zwift (bike)
  2. Pushed to Garmin Connect (all sports)
  3. Auto-detected from FIT file post-session

Protocols:
  FTP — 20-minute test, Ramp test, 2×8min test
  CSS — 400m + 200m swim time trials
  LTHR — 30-minute steady run at threshold effort

After detection, calculates new threshold and prompts for confirmation
before updating the athlete profile.
"""

import logging
import uuid
from datetime import date
from typing import List, Optional

from backend.schemas.workout import Session, WorkoutStep

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FTP test protocols
# ---------------------------------------------------------------------------

def generate_ftp_20min() -> Session:
    """Standard 20-minute FTP test."""
    return Session(
        sport="bike",
        title="FTP Test — 20 Minute",
        description=(
            "Classic 20-minute FTP test. After a structured warmup, hold the highest "
            "power you can sustain for exactly 20 minutes. FTP = avg power × 0.95."
        ),
        rationale="FTP assessment — schedule every 6-8 weeks during Build phase",
        estimated_tss=85,
        steps=[
            WorkoutStep(
                type="warmup", duration_sec=600, target_value=0.55,
                target_type="power", repeat=1, description="Easy spin, legs loose",
            ),
            WorkoutStep(
                type="interval", duration_sec=60, target_value=1.00,
                target_type="power", repeat=3,
                description="3×1min fast spin to open up — 1min easy between",
            ),
            WorkoutStep(
                type="recovery", duration_sec=300, target_value=0.50,
                target_type="power", repeat=1, description="5min easy recovery",
            ),
            WorkoutStep(
                type="interval", duration_sec=300, target_value=1.05,
                target_type="power", repeat=1,
                description="5min hard blow-out — gives a more accurate 20min result",
            ),
            WorkoutStep(
                type="recovery", duration_sec=600, target_value=0.50,
                target_type="power", repeat=1, description="10min easy recovery — fully recover",
            ),
            WorkoutStep(
                type="interval", duration_sec=1200, target_value=1.05,
                target_type="power", repeat=1,
                description="🔴 20 MINUTES — maximum sustainable effort. Start conservative. "
                "Negative split if possible. FTP = avg power × 0.95",
            ),
            WorkoutStep(
                type="cooldown", duration_sec=600, target_value=0.45,
                target_type="power", repeat=1, description="Easy cooldown spin",
            ),
        ],
    )


def generate_ftp_ramp() -> Session:
    """Ramp (MAP) test — 1-minute steps increasing until failure."""
    steps = [
        WorkoutStep(
            type="warmup", duration_sec=300, target_value=0.50,
            target_type="power", repeat=1, description="Easy warmup",
        ),
    ]
    # Ramp from 50% to 150% FTP in 5% increments
    for pct in range(50, 155, 5):
        ftp_frac = pct / 100
        steps.append(WorkoutStep(
            type="interval", duration_sec=60, target_value=ftp_frac,
            target_type="power", repeat=1,
            description=f"{pct}% FTP — hold target. Stop when you cannot maintain.",
        ))
    steps.append(WorkoutStep(
        type="cooldown", duration_sec=600, target_value=0.40,
        target_type="power", repeat=1, description="Cooldown — FTP ≈ 75% of last completed step",
    ))

    return Session(
        sport="bike",
        title="FTP Test — Ramp (MAP)",
        description=(
            "Ramp test: 1-minute steps at increasing power until failure. "
            "FTP ≈ 75% of the last fully completed minute's power. "
            "Quick, repeatable, less suffering than 20min test."
        ),
        rationale="FTP assessment via ramp — good for regular monitoring",
        estimated_tss=65,
        steps=steps,
    )


# ---------------------------------------------------------------------------
# CSS test protocol
# ---------------------------------------------------------------------------

def generate_css_test() -> Session:
    """CSS test — 400m + 200m swim time trials."""
    return Session(
        sport="swim",
        title="CSS Test — 400m + 200m TT",
        description=(
            "Critical Swim Speed test. After a thorough warmup, swim:\n"
            "1. 400m all-out (even-paced, not a sprint)\n"
            "2. Full recovery (at least 5 minutes)\n"
            "3. 200m all-out\n\n"
            "CSS = (400 - 200) / (T400 - T200) → pace per 100m"
        ),
        rationale="CSS assessment — schedule every 8-12 weeks or after a swim-focused block",
        estimated_tss=55,
        steps=[
            WorkoutStep(
                type="warmup", duration_sec=600, target_value=0.70,
                target_type="pace", repeat=1,
                description="400m easy with drills. 4×50m build to race pace.",
            ),
            WorkoutStep(
                type="interval", duration_sec=360, target_value=1.0,
                target_type="pace", repeat=1,
                description="🔴 400m TIME TRIAL — even pace, not a sprint start. "
                "Record your time precisely.",
            ),
            WorkoutStep(
                type="recovery", duration_sec=300, target_value=0.50,
                target_type="pace", repeat=1,
                description="5min full recovery — easy kick or rest",
            ),
            WorkoutStep(
                type="interval", duration_sec=150, target_value=1.05,
                target_type="pace", repeat=1,
                description="🔴 200m TIME TRIAL — slightly faster than 400m pace. "
                "Record time. CSS = (400-200)/(T400-T200)",
            ),
            WorkoutStep(
                type="cooldown", duration_sec=600, target_value=0.60,
                target_type="pace", repeat=1,
                description="300m easy cooldown swim",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# LTHR test protocol
# ---------------------------------------------------------------------------

def generate_lthr_run_test() -> Session:
    """LTHR run test — 30-minute steady-state threshold effort."""
    return Session(
        sport="run",
        title="LTHR Test — 30min Threshold Run",
        description=(
            "Lactate Threshold HR test. After warmup, run 30 minutes at the "
            "hardest pace you can sustain for the full duration. "
            "LTHR = average HR of the last 20 minutes (discard first 10 min)."
        ),
        rationale="LTHR assessment — schedule every 8-12 weeks, ideally on flat terrain",
        estimated_tss=70,
        steps=[
            WorkoutStep(
                type="warmup", duration_sec=900, target_value=0.75,
                target_type="hr", repeat=1,
                description="15min easy jog with 4×20sec strides",
            ),
            WorkoutStep(
                type="interval", duration_sec=1800, target_value=0.98,
                target_type="hr", repeat=1,
                description="🔴 30 MINUTES — hardest sustainable effort. "
                "Build into it for 2-3 min, then hold. FLAT terrain. "
                "LTHR = avg HR of last 20min (not first 10).",
            ),
            WorkoutStep(
                type="cooldown", duration_sec=600, target_value=0.65,
                target_type="hr", repeat=1,
                description="10min easy cooldown jog",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Threshold calculation from test results
# ---------------------------------------------------------------------------

def calculate_ftp_from_20min(avg_power_20min: float) -> int:
    """FTP = 95% of 20-minute average power."""
    return round(avg_power_20min * 0.95)


def calculate_ftp_from_ramp(last_completed_step_power: float) -> int:
    """FTP ≈ 75% of last completed ramp step power."""
    return round(last_completed_step_power * 0.75)


def calculate_css_from_test(
    time_400m_sec: float, time_200m_sec: float
) -> dict:
    """
    Calculate CSS from 400m and 200m swim times.
    Returns {css_m_per_sec, css_pace_per_100m_sec, css_pace_str}.
    """
    css_mps = (400 - 200) / (time_400m_sec - time_200m_sec)
    pace_sec_per_100m = 100.0 / css_mps
    minutes = int(pace_sec_per_100m // 60)
    seconds = int(pace_sec_per_100m % 60)

    return {
        "css_m_per_sec": round(css_mps, 3),
        "css_pace_per_100m_sec": round(pace_sec_per_100m, 1),
        "css_pace_str": f"{minutes}:{seconds:02d}/100m",
    }


def calculate_lthr_from_test(hr_data: List[float]) -> Optional[int]:
    """LTHR = average HR of last 20 minutes of a 30-minute threshold effort."""
    if len(hr_data) < 1200:  # Need at least 20min of second-by-second data
        # Try with what we have — use last 2/3
        cutoff = len(hr_data) // 3
        if cutoff < 300:
            return None
        return round(sum(hr_data[cutoff:]) / len(hr_data[cutoff:]))

    # Standard: discard first 10 minutes (600 seconds)
    last_20 = hr_data[600:]
    return round(sum(last_20) / len(last_20))
