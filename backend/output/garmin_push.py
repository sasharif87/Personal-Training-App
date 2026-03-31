# backend/output/garmin_push.py
"""
GarminPush — writes structured workout definitions to Garmin Connect via garth.

Uses the unofficial Garmin Connect workout API (same endpoint the website uses).
Workouts appear in the Garmin Connect calendar and sync to the watch overnight.

Risk note (from architecture doc): the Connect API is unofficial and has broken
periodically with authentication changes. garth handles token refresh automatically.

Garmin workout payload format:
  {
    "workoutName": "...",
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "estimatedDurationInSecs": 3600,
    "workoutSegments": [
      {
        "segmentOrder": 1,
        "sportType": {...},
        "workoutSteps": [
          {
            "stepOrder": 1,
            "stepType": {"stepTypeId": 1, "stepTypeKey": "warmup"},
            "durationType": {"durationTypeId": 1, "durationTypeKey": "time"},
            "durationValue": 600,
            "targetType": {"workoutTargetTypeId": 2, "workoutTargetTypeKey": "pace.zone"},
            "targetValueOne": <pace_low_mpm>,
            "targetValueTwo": <pace_high_mpm>
          }
        ]
      }
    ]
  }
"""

import os
import logging
from typing import Optional

from backend.schemas.workout import Session, WorkoutStep

logger = logging.getLogger(__name__)

# Garmin Connect sport type IDs
_SPORT_IDS = {
    "run":      {"sportTypeId": 1,  "sportTypeKey": "running"},
    "bike":     {"sportTypeId": 2,  "sportTypeKey": "cycling"},
    "swim":     {"sportTypeId": 5,  "sportTypeKey": "swimming"},
    "brick":    {"sportTypeId": 1,  "sportTypeKey": "running"},  # lead leg
    "strength": {"sportTypeId": 3,  "sportTypeKey": "strength_training"},
}

_STEP_TYPE_IDS = {
    "warmup":   {"stepTypeId": 1, "stepTypeKey": "warmup"},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval"},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery"},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown"},
    "rest":     {"stepTypeId": 5, "stepTypeKey": "rest"},
}

_DURATION_TYPE_TIME = {"durationTypeId": 1, "durationTypeKey": "time"}
_DURATION_TYPE_DIST = {"durationTypeId": 2, "durationTypeKey": "distance"}

# Target type IDs
_TARGET_NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
_TARGET_POWER_ZONE = {"workoutTargetTypeId": 11, "workoutTargetTypeKey": "power.zone"}
_TARGET_PACE_ZONE  = {"workoutTargetTypeId": 6,  "workoutTargetTypeKey": "pace.zone"}
_TARGET_HR_ZONE    = {"workoutTargetTypeId": 4,  "workoutTargetTypeKey": "heart.rate.zone"}


# ---------------------------------------------------------------------------
# GarminPush
# ---------------------------------------------------------------------------
class GarminPush:
    def __init__(self, garth_home: Optional[str] = None):
        self.garth_home = garth_home or os.environ.get("GARTH_HOME", "/data/garth")
        self._garth = None

    # -----------------------------------------------------------------------
    # garth client (lazy-init)
    # -----------------------------------------------------------------------
    def _get_garth(self):
        if self._garth is not None:
            return self._garth
        try:
            import garth
        except ImportError:
            raise RuntimeError("garth is not installed — add it to requirements.txt")

        from pathlib import Path
        token_file = Path(self.garth_home) / "oauth2_token"
        if token_file.exists():
            garth.resume(self.garth_home)
        else:
            username = os.environ.get("GARMIN_USERNAME")
            password = os.environ.get("GARMIN_PASSWORD")
            if not username or not password:
                raise RuntimeError("GARMIN_USERNAME / GARMIN_PASSWORD not set and no saved garth tokens")
            garth.login(username, password)
            garth.save(self.garth_home)

        self._garth = garth
        return garth

    # -----------------------------------------------------------------------
    # Push a single session to Garmin Connect
    # -----------------------------------------------------------------------
    def push_workout(self, session: Session, athlete_ftp: int = 200, athlete_css_mps: float = 1.4) -> str:
        """
        Converts a Session to a Garmin Connect workout payload and posts it.
        Returns the Garmin workout ID on success.

        athlete_ftp: Watts (used to convert FTP fractions to absolute power)
        athlete_css_mps: CSS in m/s (used to convert CSS fractions to pace)
        """
        garth = self._get_garth()
        payload = _build_garmin_payload(session, athlete_ftp, athlete_css_mps)

        logger.info("Pushing workout '%s' to Garmin Connect", session.title)
        try:
            response = garth.connectapi(
                "POST",
                "/workout-service/workout",
                json=payload,
            )
        except Exception as exc:
            logger.error("Garmin Connect push failed: %s", exc)
            raise

        workout_id = response.get("workoutId", "unknown")
        logger.info("Garmin workout created — ID: %s", workout_id)
        return str(workout_id)

    # -----------------------------------------------------------------------
    # Schedule a workout to a specific calendar date
    # -----------------------------------------------------------------------
    def schedule_workout(self, workout_id: str, date_str: str) -> None:
        """
        Schedules a workout to appear on a specific date in the Garmin Connect calendar.
        date_str: 'YYYY-MM-DD'
        """
        garth = self._get_garth()
        try:
            garth.connectapi(
                "POST",
                f"/workout-service/schedule/{workout_id}",
                json={"date": date_str},
            )
            logger.info("Scheduled workout %s on %s", workout_id, date_str)
        except Exception as exc:
            logger.error("Failed to schedule workout %s: %s", workout_id, exc)
            raise


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------
def _build_garmin_payload(session: Session, ftp: int, css_mps: float) -> dict:
    sport = _SPORT_IDS.get(session.sport, _SPORT_IDS["run"])
    total_duration = sum(
        (s.duration_sec or 300) * s.repeat for s in session.steps
    )

    steps = []
    for order, step in enumerate(session.steps, start=1):
        garmin_step = _build_step(order, step, session.sport, ftp, css_mps)
        if step.repeat > 1 and step.type.lower() == "interval":
            # Wrap in a repeat group
            steps.append({
                "stepOrder": order,
                "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat"},
                "numberOfIterations": step.repeat,
                "childStepId": order,
                "workoutSteps": [garmin_step],
            })
        else:
            steps.append(garmin_step)

    return {
        "workoutName": session.title,
        "description": f"{session.description}\n\nRationale: {session.rationale}",
        "sportType": sport,
        "estimatedDurationInSecs": total_duration,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": sport,
                "workoutSteps": steps,
            }
        ],
    }


def _build_step(order: int, step: WorkoutStep, sport: str, ftp: int, css_mps: float) -> dict:
    step_type = _STEP_TYPE_IDS.get(step.type.lower(), _STEP_TYPE_IDS["interval"])
    duration = step.duration_sec or 300

    garmin_step = {
        "stepOrder": order,
        "stepType": step_type,
        "durationType": _DURATION_TYPE_TIME,
        "durationValue": duration,
    }

    # Build target
    target_type = step.target_type.lower()
    val = step.target_value

    if target_type == "power" and ftp:
        abs_power = int(val * ftp)
        garmin_step["targetType"] = _TARGET_POWER_ZONE
        garmin_step["targetValueOne"] = max(0, abs_power - 10)
        garmin_step["targetValueTwo"] = abs_power + 10

    elif target_type == "pace" and sport in ("run",) and css_mps:
        # Convert fraction to seconds-per-metre, then to min/km for Garmin
        pace_mps = val * css_mps
        # Garmin uses pace in metres-per-second stored as seconds/km
        pace_sec_per_km = int(1000 / pace_mps) if pace_mps > 0 else 360
        garmin_step["targetType"] = _TARGET_PACE_ZONE
        garmin_step["targetValueOne"] = pace_sec_per_km - 15
        garmin_step["targetValueTwo"] = pace_sec_per_km + 15

    elif target_type == "hr":
        hr = int(val)
        garmin_step["targetType"] = _TARGET_HR_ZONE
        garmin_step["targetValueOne"] = max(60, hr - 5)
        garmin_step["targetValueTwo"] = hr + 5

    else:
        garmin_step["targetType"] = _TARGET_NO_TARGET

    return garmin_step
