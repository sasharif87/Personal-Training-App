# backend/data_ingestion/training_peaks_client.py
"""
TrainingPeaks API client — retrieves planned workout sessions.

Uses the TrainingPeaks v1 REST API with OAuth2 Bearer token authentication.
This is the richest source of multi-sport planned sessions — swim sets, run
intervals, brick sessions, strength days — all with coaching intent text.

OAuth2 flow:
  1. Register an app at https://developers.trainingpeaks.com
  2. Use the authorization_code flow to get an access token
  3. Store the token in TRAININGPEAKS_ACCESS_TOKEN env var
  4. Tokens expire — implement refresh if running long-lived

All planned sessions are normalised to the unified PlannedSession schema
before being stored in PostgreSQL.
"""

import logging
import os
import uuid
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.trainingpeaks.com/v1"

_SPORT_MAP = {
    "Swim":       "swim",
    "Bike":       "bike",
    "Run":        "run",
    "Strength":   "strength",
    "MTB":        "bike",
    "Rowing":     "climb",
    "Other":      "cross_training",
    "Duathlon":   "brick",
    "Triathlon":  "brick",
}


# ---------------------------------------------------------------------------
# TrainingPeaksClient
# ---------------------------------------------------------------------------
class TrainingPeaksClient:
    def __init__(self, access_token: Optional[str] = None, user_id: Optional[int] = None):
        self.access_token = access_token or os.environ.get("TRAININGPEAKS_ACCESS_TOKEN")
        self.user_id = user_id or int(os.environ.get("TRAININGPEAKS_USER_ID", "0"))

        if not self.access_token:
            raise RuntimeError(
                "TRAININGPEAKS_ACCESS_TOKEN not set — "
                "complete OAuth2 flow at https://developers.trainingpeaks.com"
            )
        self._headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type":  "application/json",
        }

    # -----------------------------------------------------------------------
    # Fetch planned workouts in date range
    # -----------------------------------------------------------------------
    def get_planned_workouts(
        self,
        start_date: date,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch all planned workouts between start_date and end_date.
        Returns list of normalised PlannedSession-compatible dicts.
        """
        end_date = end_date or start_date + timedelta(days=30)

        try:
            resp = requests.get(
                f"{_BASE_URL}/workouts/{self.user_id}",
                params={
                    "startDate": start_date.isoformat(),
                    "endDate":   end_date.isoformat(),
                },
                headers=self._headers,
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("TrainingPeaks API request failed: %s", exc)
            raise

        raw_workouts = resp.json()
        logger.info(
            "TrainingPeaks: fetched %d workouts %s → %s",
            len(raw_workouts), start_date, end_date,
        )
        return [self._normalise(w) for w in raw_workouts]

    # -----------------------------------------------------------------------
    # Normalise TP workout → unified PlannedSession schema
    # -----------------------------------------------------------------------
    def _normalise(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        sport_raw = raw.get("exerciseType") or raw.get("workoutType") or "Other"
        sport = _SPORT_MAP.get(sport_raw, sport_raw.lower())

        structure = self._parse_structure(raw.get("structure") or raw.get("workoutStructure"))

        return {
            "session_id":           raw.get("workoutId") or str(uuid.uuid4()),
            "source_platform":      "trainingpeaks",
            "planned_date":         (raw.get("workoutDay") or raw.get("scheduledDate") or "")[:10],
            "sport":                sport,
            "title":                raw.get("title") or raw.get("name") or "TP Workout",
            "coaching_text":        raw.get("description") or raw.get("coachComments") or "",
            "planned_duration_min": _safe_div(raw.get("totalTime"), 60),
            "planned_tss":          raw.get("tss") or raw.get("totalStressScore"),
            "planned_if":           raw.get("if") or raw.get("intensityFactor"),
            "planned_distance_m":   raw.get("distance"),
            "planned_elevation_m":  raw.get("elevationGain"),
            "structure":            structure,
            "targets": {
                "hr_zone":    raw.get("heartRateZone"),
                "power_zone": raw.get("powerZone"),
                "pace_zone":  raw.get("paceZone"),
                "rpe_target": raw.get("perceivedExertionTarget"),
            },
        }

    def _parse_structure(self, structure: Optional[Dict]) -> Dict[str, Any]:
        """
        Parse TP structured workout steps into unified format.
        TP structure: {"steps": [...], "estimatedDurationInSecs": N}
        """
        if not structure:
            return {}

        steps = structure.get("structure") or structure.get("steps") or []
        warmup, main_sets, cooldown = [], [], []

        for step in steps:
            step_type = step.get("type") or step.get("stepType") or "active"
            parsed = self._parse_step(step)
            if not parsed:
                continue
            if step_type.lower() in ("warmup", "warm_up"):
                warmup.append(parsed)
            elif step_type.lower() in ("cooldown", "cool_down"):
                cooldown.append(parsed)
            else:
                main_sets.append(parsed)

        return {
            "warmup":    warmup,
            "main_sets": main_sets,
            "cooldown":  cooldown,
        }

    def _parse_step(self, step: Dict) -> Optional[Dict]:
        """Parse a single TP step into the unified step schema."""
        length = step.get("length") or {}
        duration_sec = None
        distance_m = None

        length_type = length.get("unit") or length.get("type") or ""
        value = length.get("value", 0)
        if "second" in length_type.lower() or "time" in length_type.lower():
            duration_sec = int(value)
        elif "meter" in length_type.lower() or "metre" in length_type.lower():
            distance_m = float(value)
        elif "kilometer" in length_type.lower():
            distance_m = float(value) * 1000
        elif "mile" in length_type.lower():
            distance_m = float(value) * 1609.34

        # Target
        targets = step.get("targets") or step.get("intensityTarget") or {}
        target_value, target_type = _parse_tp_target(targets)

        return {
            "type":         step.get("type") or "interval",
            "duration_sec": duration_sec,
            "distance_m":   distance_m,
            "target_value": target_value,
            "target_type":  target_type,
            "repeat":       step.get("repetitions") or step.get("repeat") or 1,
            "description":  step.get("description") or step.get("name") or "",
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_div(value: Optional[float], divisor: float) -> Optional[float]:
    if value is None or divisor == 0:
        return None
    return round(value / divisor, 1)


def _parse_tp_target(targets: Dict) -> tuple:
    """
    Parse TP target into (target_value, target_type).
    TP may use power (FTP fraction or watts), pace, or HR.
    """
    if not targets:
        return 0.75, "power"

    # Power zone / FTP fraction
    power = targets.get("power") or targets.get("powerTarget")
    if power:
        if isinstance(power, dict):
            low = power.get("min") or power.get("low") or 0
            high = power.get("max") or power.get("high") or low
            mid = (low + high) / 2
        else:
            mid = float(power)
        # Values > 10 are absolute watts — store raw; pipeline divides by FTP
        return round(mid, 3), "power"

    # HR
    hr = targets.get("heartRate") or targets.get("hrTarget")
    if hr:
        if isinstance(hr, dict):
            low = hr.get("min") or hr.get("low") or 0
            high = hr.get("max") or hr.get("high") or low
            mid = (low + high) / 2
        else:
            mid = float(hr)
        return round(mid, 1), "hr"

    # Pace (m/s or min/km)
    pace = targets.get("pace") or targets.get("paceTarget")
    if pace:
        if isinstance(pace, dict):
            low = pace.get("min") or pace.get("low") or 0
            high = pace.get("max") or pace.get("high") or low
            mid = (low + high) / 2
        else:
            mid = float(pace)
        return round(mid, 3), "pace"

    return 0.75, "power"
