# backend/analysis/tss_calculators.py
"""
Sport-specific TSS calculators.

Each sport uses a different reference metric as its "threshold":
  Bike      — Normalized Power vs FTP  (standard TSS formula)
  Run       — Power, Pace, or HR       (3 methods — see below)
  Swim      — Pace vs CSS              (ssTSS — swim stress score)
  Strength  — Volume load proxy        (sTSS — rough but trackable)
  Climb     — HR vs LTHR + elevation   (ctTSS — same base as hrTSS + elevation bonus)
  Yoga      — Duration × subtype coeff (near-zero for restorative)

Run TSS methods (priority order):
  1. Power  — rTSS via running power (Stryd / Garmin Running Power)
  2. Pace   — rTSS via pace vs threshold pace (normalized or regular pace)
  3. HR     — hrTSS via TRIMP (fallback when no power or pace available)

All return float TSS values. All accept optional parameters that fall back to
safe defaults when data is sparse (e.g. no power file available).

Cross-sport daily TSS combines all sports without modification — the Banister
model is agnostic to source once TSS is normalised to the same threshold scale.
"""

import logging
import math
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bike TSS — standard power-based formula
# ---------------------------------------------------------------------------
def calculate_bike_tss(
    power_data: Optional[List[float]],
    ftp: float,
    duration_sec: int,
    avg_power: Optional[float] = None,
) -> float:
    """
    Standard TSS = (duration_sec * NP * IF) / (FTP * 3600) * 100

    power_data: second-by-second or sample-by-sample power in Watts.
    If unavailable, falls back to avg_power with a 0.97 NP/avg ratio assumption.
    """
    if duration_sec <= 0 or ftp <= 0:
        return 0.0

    if power_data and len(power_data) >= 30:
        np_watts = _normalized_power(power_data)
    elif avg_power and avg_power > 0:
        np_watts = avg_power * 0.97  # NP slightly above avg for typical road rides
    else:
        return 0.0

    intensity_factor = np_watts / ftp
    tss = (duration_sec * np_watts * intensity_factor) / (ftp * 3600) * 100
    return round(min(tss, 400.0), 1)  # cap at 400 — anything above is a data error


def _normalized_power(power_samples: List[float]) -> float:
    """
    30-second rolling average raised to 4th power, averaged, then 4th root.
    Standard Coggan NP formula. Works for both bike power and running power.
    """
    import numpy as np
    arr = np.array(power_samples, dtype=float)
    arr = np.maximum(arr, 0)
    window = min(30, len(arr))
    rolling = np.convolve(arr, np.ones(window) / window, mode="valid")
    return float(np.mean(rolling ** 4) ** 0.25)


# ---------------------------------------------------------------------------
# Run TSS — multi-method: power > pace > HR
# ---------------------------------------------------------------------------
def calculate_run_tss(
    duration_sec: int,
    # --- Power method (highest accuracy, requires Stryd / Garmin Running Power) ---
    power_data: Optional[List[float]] = None,
    avg_power: Optional[float] = None,
    run_ftp: Optional[float] = None,
    # --- Pace method (preferred for pace-based runners) ---
    pace_sec_per_km: Optional[float] = None,
    normalized_pace_sec_per_km: Optional[float] = None,
    threshold_pace_sec_per_km: Optional[float] = None,
    # --- HR method (fallback) ---
    hr_data: Optional[List[float]] = None,
    avg_hr: Optional[float] = None,
    lthr: Optional[float] = None,
    # --- GPS / Speed data for auto-calculating NGP ---
    speed_data: Optional[List[float]] = None,
    elevation_data: Optional[List[float]] = None,
    distance_data: Optional[List[float]] = None,
    lat_lon_data: Optional[List[tuple]] = None,
    # --- Control ---
    method: Optional[str] = None,
) -> float:
    """
    Run TSS with three calculation methods. Auto-selects the best available
    unless `method` is explicitly set.

    Methods:
      "power" — rTSS via running power (same formula as bike TSS but with run FTP)
                Requires: power_data or avg_power + run_ftp
      "pace"  — rTSS via pace intensity factor: IF = threshold_pace / actual_pace
                Uses normalized_pace if available, otherwise regular pace.
                Requires: pace_sec_per_km + threshold_pace_sec_per_km
      "hr"    — hrTSS via TRIMP (Banister)
                Requires: hr_data or avg_hr + lthr

    Priority (when method=None): power > pace > hr

    Pace inputs:
      pace_sec_per_km:            regular average pace (e.g. 300 = 5:00/km)
      normalized_pace_sec_per_km: grade-adjusted / normalized pace (e.g. from Garmin)
      threshold_pace_sec_per_km:  your threshold pace (roughly 1-hour race pace)

    Example — pace-based:
      Threshold pace: 4:30/km (270s), actual: 5:00/km (300s) -> IF = 0.90
      60 min run -> rTSS = 0.90^2 * 1.0 * 100 = 81

    Example — power-based:
      Run FTP: 280W, avg power: 250W -> IF = 0.89
      60 min run -> rTSS = (3600 * 250 * 0.89) / (280 * 3600) * 100 = 80
    """
    if duration_sec <= 0:
        return 0.0

    # --- Auto-calculate NGP if needed and data is available ---
    if not normalized_pace_sec_per_km and speed_data and elevation_data:
        try:
            ngp = calculate_normalized_pace_from_data(
                speed_data, elevation_data, lat_lon_data, distance_data
            )
            if ngp and ngp > 0:
                normalized_pace_sec_per_km = ngp
        except Exception as e:
            logger.warning("Failed to auto-calculate NGP: %s", e)

    # --- Auto-select method ---
    if method is None:
        if (power_data or avg_power) and run_ftp:
            method = "power"
        elif (pace_sec_per_km or normalized_pace_sec_per_km) and threshold_pace_sec_per_km:
            method = "pace"
        elif lthr and (hr_data or avg_hr):
            method = "hr"
        else:
            logger.warning("Run TSS: no usable data — returning 0")
            return 0.0

    if method == "power":
        return _run_tss_power(duration_sec, power_data, avg_power, run_ftp or 0)
    elif method == "pace":
        return _run_tss_pace(
            duration_sec, pace_sec_per_km, normalized_pace_sec_per_km,
            threshold_pace_sec_per_km or 0,
        )
    elif method == "hr":
        return _run_tss_hr(duration_sec, hr_data, avg_hr, lthr or 162)
    else:
        logger.error("Unknown run TSS method: %s", method)
        return 0.0


def _run_tss_power(
    duration_sec: int,
    power_data: Optional[List[float]],
    avg_power: Optional[float],
    run_ftp: float,
) -> float:
    """
    rTSS via running power — identical formula to bike TSS.
    Run FTP is typically determined via a 30-minute threshold run with Stryd.

    TSS = (duration_sec * NP * IF) / (FTP * 3600) * 100
    """
    if run_ftp <= 0:
        return 0.0

    if power_data and len(power_data) >= 30:
        np_watts = _normalized_power(power_data)
    elif avg_power and avg_power > 0:
        np_watts = avg_power * 0.98  # NP/avg ratio for running (less coasting than bike)
    else:
        return 0.0

    intensity_factor = np_watts / run_ftp
    tss = (duration_sec * np_watts * intensity_factor) / (run_ftp * 3600) * 100
    return round(min(tss, 400.0), 1)


def _run_tss_pace(
    duration_sec: int,
    pace_sec_per_km: Optional[float],
    normalized_pace_sec_per_km: Optional[float],
    threshold_pace_sec_per_km: float,
) -> float:
    """
    rTSS via pace — uses the same IF^2 * duration formula.

    Pace IF = threshold_pace / actual_pace
    (Lower seconds = faster pace = higher IF, same logic as swim CSS)

    Prefers normalized pace (adjusts for hills, stops, surges) over regular pace.
    Regular pace works well for flat, steady runs.

    Example:
      Threshold pace: 4:30/km (270s)
      Actual pace: 5:00/km (300s)  -> IF = 270/300 = 0.90
      Actual pace: 4:15/km (255s)  -> IF = 270/255 = 1.06 (above threshold)
    """
    if threshold_pace_sec_per_km <= 0:
        return 0.0

    # Prefer normalized pace, fall back to regular
    actual_pace = normalized_pace_sec_per_km or pace_sec_per_km
    if not actual_pace or actual_pace <= 0:
        return 0.0

    intensity_factor = threshold_pace_sec_per_km / actual_pace
    duration_hr = duration_sec / 3600.0
    tss = (intensity_factor ** 2) * duration_hr * 100
    return round(min(tss, 400.0), 1)


def _run_tss_hr(
    duration_sec: int,
    hr_data: Optional[List[float]],
    avg_hr: Optional[float],
    lthr: float,
) -> float:
    """
    hrTSS via TRIMP (Banister) — fallback when no power or pace data.
    TRIMP = duration_min * avg_HR_fraction * exp(1.92 * avg_HR_fraction)
    hrTSS ~ TRIMP * 0.80  (empirical scaling to align with bike TSS at threshold)
    """
    if lthr <= 0:
        return 0.0

    if hr_data and len(hr_data) >= 10:
        _avg_hr = sum(hr_data) / len(hr_data)
    elif avg_hr and avg_hr > 0:
        _avg_hr = avg_hr
    else:
        _avg_hr = lthr * 0.80  # Assume Z2

    hr_frac = _avg_hr / lthr
    duration_min = duration_sec / 60.0
    trimp = duration_min * hr_frac * math.exp(1.92 * hr_frac)
    tss = trimp * 0.80
    return round(min(tss, 400.0), 1)


# ---------------------------------------------------------------------------
# NGP calculation
# ---------------------------------------------------------------------------
def _get_ngp_factor(gradient: float) -> float:
    """
    Minetti formula for running energy cost as a function of gradient.
    Normalized so flat (0%) = 1.0.
    """
    g = max(-0.25, min(0.25, gradient))
    cost = 155.4 * (g**5) - 30.4 * (g**4) - 43.3 * (g**3) + 46.3 * (g**2) + 19.5 * g + 3.6
    return max(0.5, cost / 3.6)


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Returns distance in meters between two lat/lon points."""
    import math
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def calculate_normalized_pace_from_data(
    speed_data: List[float],
    elevation_data: List[float],
    lat_lon_data: Optional[List[tuple]] = None,
    distance_data: Optional[List[float]] = None,
) -> Optional[float]:
    """
    Calculate Normalized Graded Pace (NGP) from time-series data.
    Takes 1-sec or dense arrays and applies gradient-adjusted cost.
    Returns pace in seconds per km (e.g. 5:00/km = 300).
    """
    if not speed_data or not elevation_data or len(speed_data) != len(elevation_data):
        return None
        
    gap_speeds = []
    n = len(speed_data)
    
    for i in range(1, n):
        speed = speed_data[i]
        if speed <= 0 or speed > 12.0:  # ignore stationary or car/bike glitch
            continue
            
        delta_elev = elevation_data[i] - elevation_data[i-1]
        
        if distance_data and len(distance_data) == n:
            delta_dist = distance_data[i] - distance_data[i-1]
        elif lat_lon_data and len(lat_lon_data) == n:
            lat1, lon1 = lat_lon_data[i-1][:2]
            lat2, lon2 = lat_lon_data[i][:2]
            delta_dist = _haversine_distance(lat1, lon1, lat2, lon2)
        else:
            delta_dist = speed * 1.0  # assume 1Hz logging
            
        if delta_dist > 0.5:
            gradient = delta_elev / delta_dist
        else:
            gradient = 0.0
            
        factor = _get_ngp_factor(gradient)
        gap_speeds.append(speed * factor)
        
    if not gap_speeds:
        return None
        
    ngp_speed_mps = _normalized_power(gap_speeds)
    if ngp_speed_mps <= 0.5:
        return None
        
    return 1000.0 / ngp_speed_mps


# ---------------------------------------------------------------------------
# Pace helpers
# ---------------------------------------------------------------------------
def pace_str_to_sec_per_km(pace_str: str) -> float:
    """
    Parse pace string like '5:00/km' or '4:30' to seconds per km.
    Returns 300.0 (5:00/km) as default on parse failure.
    """
    try:
        cleaned = pace_str.replace("/km", "").replace("/mi", "").strip()
        parts = cleaned.split(":")
        return int(parts[0]) * 60 + float(parts[1])
    except Exception:
        return 300.0


def pace_str_to_sec_per_mile(pace_str: str) -> float:
    """Parse pace string like '8:00/mi' to seconds per mile."""
    try:
        cleaned = pace_str.replace("/mi", "").replace("/km", "").strip()
        parts = cleaned.split(":")
        return int(parts[0]) * 60 + float(parts[1])
    except Exception:
        return 480.0


def pace_per_mile_to_per_km(pace_sec_per_mile: float) -> float:
    """Convert pace in sec/mile to sec/km."""
    return pace_sec_per_mile / 1.60934


# ---------------------------------------------------------------------------
# Swim TSS — ssTSS using CSS as threshold reference
# ---------------------------------------------------------------------------
def calculate_swim_tss(
    pace_per_100m_sec: float,
    css_per_100m_sec: float,
    duration_sec: int,
) -> float:
    """
    Swim Stress Score — CSS is the threshold reference (analogous to FTP for bike).

    swim_IF = css_pace / actual_pace
    For pace, lower seconds = faster. IF > 1 means faster than CSS (harder than threshold).
    ssTSS = swim_IF^2 * duration_hr * 100

    pace_per_100m_sec: average pace e.g. 105 (1:45/100m)
    css_per_100m_sec:  CSS e.g. 100 (1:40/100m)
    """
    if duration_sec <= 0 or css_per_100m_sec <= 0 or pace_per_100m_sec <= 0:
        return 0.0

    swim_if = css_per_100m_sec / pace_per_100m_sec  # >1 means faster than CSS
    duration_hr = duration_sec / 3600.0
    tss = (swim_if ** 2) * duration_hr * 100
    return round(min(tss, 300.0), 1)


def css_str_to_sec(css_str: str) -> float:
    """
    Parse CSS string like '1:45/100m' to seconds per 100m.
    Returns 100.0 (1:40) as default on parse failure.
    """
    try:
        parts = css_str.replace("/100m", "").strip().split(":")
        return int(parts[0]) * 60 + float(parts[1])
    except Exception:
        return 100.0


# ---------------------------------------------------------------------------
# Strength TSS — volume load proxy
# ---------------------------------------------------------------------------
def calculate_strength_tss(
    exercises: Optional[List[dict]],
    duration_min: int,
    subtype: str = "gym",
) -> float:
    """
    Estimated strength TSS.

    Base: duration * 0.5 * rpe_modifier  (~30 TSS/hr at moderate RPE)
    Volume load bonus: sets * reps * (weight_kg / 100) * 0.1
    Cap: 80 TSS for any single session

    exercises: list of {sets, reps, weight_kg (optional), rpe (optional)}
    """
    if duration_min <= 0:
        return 0.0

    # Bodyweight sessions are lower load
    load_coeff = {"gym": 1.0, "bodyweight": 0.6, "climbing_gym": 0.8, "climbing_outdoor": 0.9}.get(subtype, 0.8)

    if exercises:
        rpe_values = [e.get("rpe", 7) for e in exercises]
        rpe_modifier = (sum(rpe_values) / len(rpe_values)) / 10.0
        volume_load = sum(
            e.get("sets", 3) * e.get("reps", 8) * (e.get("weight_kg", 0) / 100.0)
            for e in exercises
        )
        base_tss = duration_min * 0.5 * rpe_modifier * load_coeff
        tss = base_tss + volume_load * 0.1
    else:
        # No exercise log — estimate from duration only
        tss = duration_min * 0.4 * load_coeff

    return round(min(tss, 80.0), 1)


# ---------------------------------------------------------------------------
# Climb TSS — hrTSS equivalent + elevation bonus
# ---------------------------------------------------------------------------
def calculate_climb_tss(
    hr_data: Optional[List[float]],
    lthr: float,
    duration_sec: int,
    elevation_gain_m: float = 0,
    avg_hr: Optional[float] = None,
) -> float:
    """
    ctTSS = hrTSS (same formula as run HR method) + small elevation bonus.
    Elevation bonus: 0.01 * elevation_gain_m (e.g. 300m = +3 TSS)
    Captures upper-body fatigue and sustained cardiac load on multi-pitch routes.
    """
    base = _run_tss_hr(duration_sec, hr_data, avg_hr, lthr)
    elevation_bonus = elevation_gain_m * 0.01
    return round(min(base + elevation_bonus, 250.0), 1)


# ---------------------------------------------------------------------------
# Yoga / mobility TSS — duration * subtype coefficient
# ---------------------------------------------------------------------------
def calculate_yoga_tss(subtype: str, duration_min: int) -> float:
    """
    Yoga TSS by subtype. Restorative sessions contribute near-zero load.
    Hot yoga is moderate aerobic. The recovery contribution is modeled as a
    reduced ATL impact in the pipeline rather than negative TSS here.

    subtype: hot_yoga | vinyasa | hatha | restorative | mobility | stretching
    """
    coefficients = {
        "hot_yoga":    0.50,   # ~30 TSS/hr
        "vinyasa":     0.40,
        "hatha":       0.25,
        "restorative": 0.05,
        "mobility":    0.05,
        "stretching":  0.02,
    }
    coeff = coefficients.get(subtype.lower(), 0.30)
    return round(duration_min * coeff, 1)


# ---------------------------------------------------------------------------
# Garmin activity type -> cross-training normaliser
# ---------------------------------------------------------------------------
GARMIN_CROSS_TRAINING_MAP = {
    "ROCK_CLIMBING":      ("climb", "climbing_outdoor"),
    "INDOOR_CLIMBING":    ("climb", "climbing_gym"),
    "BOULDERING":         ("climb", "climbing_gym"),
    "YOGA":               ("yoga",  "hatha"),          # refined from activity name below
    "FITNESS_EQUIPMENT":  ("strength", "gym"),
    "TRAINING":           ("strength", "bodyweight"),
    "HIKING":             ("climb", "hiking"),
    "FLOOR_CLIMBING":     ("strength", "bodyweight"),
}

_YOGA_NAME_KEYWORDS = {
    "hot":        "hot_yoga",
    "bikram":     "hot_yoga",
    "vinyasa":    "vinyasa",
    "flow":       "vinyasa",
    "hatha":      "hatha",
    "restorative":"restorative",
    "yin":        "restorative",
    "mobility":   "mobility",
    "stretch":    "stretching",
}


def tss_from_garmin_activity(activity: dict, lthr: float = 162) -> Optional[float]:
    """
    Compute TSS for a Garmin cross-training activity using sport-appropriate formula.
    Returns None if the activity type is not in the cross-training map.

    activity keys: activityType, name, duration_sec, duration_min,
                   hr_data (list), avg_hr, elevation_gain_m
    """
    garmin_type = (activity.get("activityType") or "").upper()
    mapping = GARMIN_CROSS_TRAINING_MAP.get(garmin_type)
    if not mapping:
        return None

    sport, subtype = mapping

    # Refine yoga subtype from activity name
    if sport == "yoga":
        name_lower = (activity.get("name") or "").lower()
        for kw, refined in _YOGA_NAME_KEYWORDS.items():
            if kw in name_lower:
                subtype = refined
                break

    duration_sec = activity.get("duration_sec") or (activity.get("duration_min", 0) * 60)
    duration_min = duration_sec / 60

    if sport == "climb":
        return calculate_climb_tss(
            hr_data=activity.get("hr_data"),
            lthr=lthr,
            duration_sec=int(duration_sec),
            elevation_gain_m=activity.get("elevation_gain_m", 0),
            avg_hr=activity.get("avg_hr"),
        )
    elif sport == "yoga":
        return calculate_yoga_tss(subtype, int(duration_min))
    else:
        return calculate_strength_tss(
            exercises=activity.get("exercises"),
            duration_min=int(duration_min),
            subtype=subtype,
        )
