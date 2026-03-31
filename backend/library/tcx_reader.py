# backend/library/tcx_reader.py
"""
TCX workout reader — parses TrainingPeaks and Garmin TCX workout files.

TrainingPeaks exports structured workout definitions as TCX (Training Center XML).
The workout section is different from the activity section — it describes *intended*
structure (steps, targets) rather than recorded data.

Supported TCX workout target types:
  No target            → no target
  HeartRateZone        → HR zone number mapped to BPM range
  Speed                → speed range (m/s) mapped to pace fraction of CSS/LTHR
  Power / PowerZone    → watts or zone number mapped to FTP fraction
  Cadence              → ignored (no equivalent in WorkoutStep)

TCX workout file structure:
  <TrainingCenterDatabase>
    <Workouts>
      <Workout Sport="Biking|Running|Swimming|Other">
        <Name>...</Name>
        <Step xsi:type="Step_t">
          <StepId>1</StepId>
          <Name>...</Name>
          <Duration xsi:type="Time_t|Distance_t|Open_t">
            <Seconds>600</Seconds>      <!-- Time_t -->
            <Meters>1000</Meters>       <!-- Distance_t -->
          </Duration>
          <Intensity>Warmup|Active|Resting|Cooldown</Intensity>
          <Target xsi:type="Speed_t|HeartRateZone_t|Power_t|None_t">
            <!-- varies by type -->
          </Target>
        </Step>
        <Step xsi:type="Repeat_t">
          <Repetitions>5</Repetitions>
          <Child xsi:type="Step_t">...</Child>
        </Step>
      </Workout>
    </Workouts>
  </TrainingCenterDatabase>

Note: some TrainingPeaks exports use absolute power (Watts) rather than FTP fractions.
If the power values are > 10, they are treated as absolute watts and divided by athlete FTP.
Pass athlete_ftp when reading if you want accurate FTP-fraction targets.
"""

import logging
import re
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree as ET

from backend.schemas.workout import Session, WorkoutStep

logger = logging.getLogger(__name__)

# TCX uses namespaces — strip them for simpler tag matching
_NS_PATTERN = re.compile(r"\{[^}]+\}")

# Garmin TCX HR zone BPM midpoints (rough population averages — pipeline will
# contextualise against athlete LTHR)
_HR_ZONE_BPM = {1: 115, 2: 130, 3: 145, 4: 158, 5: 170}

_SPORT_MAP = {
    "biking":    "bike",
    "cycling":   "bike",
    "running":   "run",
    "swimming":  "swim",
    "other":     "run",
}


# ---------------------------------------------------------------------------
# TCXReader
# ---------------------------------------------------------------------------
class TCXReader:
    def __init__(self, athlete_ftp: int = 250, athlete_lthr: int = 162):
        self.athlete_ftp = athlete_ftp
        self.athlete_lthr = athlete_lthr

    def read(self, path: str | Path) -> List[Session]:
        """
        Parse a TCX file and return a list of Sessions (one per <Workout> element).
        Returns empty list if parsing fails.
        """
        path = Path(path)
        try:
            tree = ET.parse(str(path))
        except ET.ParseError as exc:
            logger.error("TCX parse error in %s: %s", path, exc)
            return []

        root = tree.getroot()
        sessions = []

        for workout_el in _findall(root, "Workout"):
            session = self._parse_workout(workout_el, path.stem)
            if session:
                sessions.append(session)

        if not sessions:
            logger.warning("No parseable workouts found in %s", path)
        return sessions

    def read_directory(self, directory: str | Path) -> List[Session]:
        directory = Path(directory)
        sessions = []
        for tcx_file in sorted(directory.glob("**/*.tcx")):
            sessions.extend(self.read(tcx_file))
        logger.info("Loaded %d TCX workouts from %s", len(sessions), directory)
        return sessions

    # -----------------------------------------------------------------------
    # Workout element → Session
    # -----------------------------------------------------------------------
    def _parse_workout(self, el: ET.Element, filename: str) -> Optional[Session]:
        name = _text(el, "Name") or filename
        notes = _text(el, "ScheduledOn") or ""  # TP sometimes puts notes here
        sport_raw = el.get("Sport", "Other").lower()
        sport = _SPORT_MAP.get(sport_raw, "run")

        steps: List[WorkoutStep] = []
        for child in el:
            tag = _strip_ns(child.tag)
            if tag == "Step":
                step = self._parse_step(child, sport)
                if step:
                    steps.append(step)

        if not steps:
            return None

        total_tss = _estimate_tss(steps, sport)
        return Session(
            sport=sport,
            title=name,
            description=notes or f"Imported from {filename}.tcx",
            rationale="TrainingPeaks import",
            steps=steps,
            estimated_tss=round(total_tss, 1),
        )

    # -----------------------------------------------------------------------
    # Step element → WorkoutStep (handles both Step_t and Repeat_t)
    # -----------------------------------------------------------------------
    def _parse_step(self, el: ET.Element, sport: str) -> Optional[WorkoutStep]:
        xsi_type = el.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
        if not xsi_type:
            # Try attribute without namespace
            xsi_type = el.get("type", "Step_t")

        if "Repeat_t" in xsi_type:
            return self._parse_repeat(el, sport)

        # Step_t
        step_name = _text(el, "Name") or ""
        intensity = _text(el, "Intensity") or "Active"
        duration_sec, distance_m = self._parse_duration(el)
        target_value, target_type = self._parse_target(el, sport)

        step_type = _intensity_to_type(intensity)

        return WorkoutStep(
            type=step_type,
            duration_sec=duration_sec,
            distance_m=distance_m,
            target_value=target_value,
            target_type=target_type,
            repeat=1,
            description=step_name or f"{step_type.title()} @ {_fmt_target(target_value, target_type)}",
        )

    def _parse_repeat(self, el: ET.Element, sport: str) -> Optional[WorkoutStep]:
        reps = int(_text(el, "Repetitions") or "1")
        # Find the first Child step to use as template
        child_el = _find(el, "Child")
        if child_el is None:
            return None
        step = self._parse_step(child_el, sport)
        if step:
            step.repeat = reps
            step.description = f"{reps}× {step.description}"
        return step

    def _parse_duration(self, el: ET.Element):
        dur_el = _find(el, "Duration")
        if dur_el is None:
            return None, None

        xsi_type = dur_el.get("{http://www.w3.org/2001/XMLSchema-instance}type", "") or dur_el.get("type", "")
        if "Time_t" in xsi_type:
            secs = _text(dur_el, "Seconds")
            return int(secs) if secs else None, None
        if "Distance_t" in xsi_type:
            metres = _text(dur_el, "Meters")
            return None, float(metres) if metres else None
        return None, None

    def _parse_target(self, el: ET.Element, sport: str):
        tgt_el = _find(el, "Target")
        if tgt_el is None:
            return 0.75, "power" if sport == "bike" else "pace"

        xsi_type = tgt_el.get("{http://www.w3.org/2001/XMLSchema-instance}type", "") or tgt_el.get("type", "")

        if "Power_t" in xsi_type:
            return self._power_target(tgt_el)
        if "Speed_t" in xsi_type:
            return self._speed_target(tgt_el, sport)
        if "HeartRateZone_t" in xsi_type or "HeartRate_t" in xsi_type:
            return self._hr_target(tgt_el)
        # None_t or unknown
        default = 0.75 if sport == "bike" else 0.88
        return default, "power" if sport == "bike" else "pace"

    def _power_target(self, tgt_el: ET.Element):
        # Try absolute watts first
        low = _text(tgt_el, "Low") or _text(_find(tgt_el, "PowerZone") or tgt_el, "Low")
        high = _text(tgt_el, "High") or _text(_find(tgt_el, "PowerZone") or tgt_el, "High")
        if low and float(low) > 10:
            mid = (float(low) + float(high or low)) / 2
            return round(mid / self.athlete_ftp, 3), "power"
        # Zone number (1–7 Coggan)
        zone_num = _text(_find(tgt_el, "PowerZone") or tgt_el, "Number")
        if zone_num:
            frac = {1: 0.55, 2: 0.68, 3: 0.83, 4: 0.95, 5: 1.05, 6: 1.15, 7: 1.30}.get(int(zone_num), 0.75)
            return frac, "power"
        return 0.75, "power"

    def _speed_target(self, tgt_el: ET.Element, sport: str):
        low = _text(tgt_el, "Low")
        high = _text(tgt_el, "High")
        if low:
            mid_mps = (float(low) + float(high or low)) / 2
            # Store as absolute m/s — library will normalise to CSS fraction at runtime
            pace_frac = round(mid_mps / 1.4, 3)  # 1.4 m/s ≈ default CSS placeholder
            return pace_frac, "pace"
        return 0.88, "pace"

    def _hr_target(self, tgt_el: ET.Element):
        zone_el = _find(tgt_el, "Zone")
        if zone_el is not None:
            num = _text(zone_el, "Number")
            if num:
                bpm = _HR_ZONE_BPM.get(int(num), 145)
                return round(bpm / self.athlete_lthr, 3), "hr"
        low = _text(tgt_el, "Low")
        high = _text(tgt_el, "High")
        if low:
            mid = (float(low) + float(high or low)) / 2
            return round(mid / self.athlete_lthr, 3), "hr"
        return 0.85, "hr"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _strip_ns(tag: str) -> str:
    return _NS_PATTERN.sub("", tag)


def _find(el: ET.Element, local_tag: str) -> Optional[ET.Element]:
    for child in el:
        if _strip_ns(child.tag) == local_tag:
            return child
    return None


def _findall(el: ET.Element, local_tag: str) -> List[ET.Element]:
    return [c for c in el.iter() if _strip_ns(c.tag) == local_tag]


def _text(el: ET.Element, local_tag: str) -> str:
    child = _find(el, local_tag)
    return (child.text or "").strip() if child is not None else ""


def _intensity_to_type(intensity: str) -> str:
    mapping = {
        "Warmup":  "warmup",
        "Active":  "interval",
        "Resting": "recovery",
        "Cooldown": "cooldown",
    }
    return mapping.get(intensity, "interval")


def _fmt_target(val: float, ttype: str) -> str:
    if ttype == "power":
        return f"{int(val * 100)}% FTP"
    if ttype == "hr":
        return f"{int(val * 100)}% LTHR"
    return f"{int(val * 100)}% CSS"


def _estimate_tss(steps: List[WorkoutStep], sport: str) -> float:
    total = 0.0
    for step in steps:
        if step.target_type == "power" and sport == "bike":
            dur = (step.duration_sec or 300) * step.repeat
            total += (dur * step.target_value ** 2) / 36.0
        elif step.target_type in ("pace", "hr"):
            dur = (step.duration_sec or 300) * step.repeat
            total += (dur * step.target_value ** 2) / 36.0
    return total
