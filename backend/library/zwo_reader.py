# backend/library/zwo_reader.py
"""
ZwoReader — parses Zwift/TrainerRoad .zwo XML files into the Session schema.

Handles all standard .zwo block types:
  Warmup, Cooldown       — ramp between PowerLow and PowerHigh
  SteadyState            — single Power target
  IntervalsT             — on/off block with Repeat
  Ramp                   — progressive power ramp
  FreeRide               — unstructured (maps to Z2 steady state)
  MaxEffort              — all-out sprint

Power values in .zwo are FTP fractions (0.0–2.0), matching WorkoutStep.target_value.

TSS estimation uses the standard formula:
  TSS = (duration_sec * NP * IF) / (FTP * 3600) * 100
For .zwo files, IF ≈ weighted power fraction, NP ≈ IF * FTP, so:
  TSS ≈ (duration_sec * IF²) / 36
"""

import logging
import re
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree as ET

from backend.schemas.workout import Session, WorkoutStep

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ZwoReader
# ---------------------------------------------------------------------------
class ZwoReader:

    def read(self, path: str | Path) -> Optional[Session]:
        """
        Parse a .zwo file and return a Session, or None if parsing fails.
        """
        path = Path(path)
        try:
            tree = ET.parse(str(path))
        except ET.ParseError as exc:
            logger.error("Failed to parse %s: %s", path, exc)
            return None

        root = tree.getroot()
        name = _text(root, "name") or path.stem
        description = _text(root, "description") or ""
        author = _text(root, "author") or ""

        workout_el = root.find("workout")
        if workout_el is None:
            logger.warning("No <workout> element in %s", path)
            return None

        steps: List[WorkoutStep] = []
        for el in workout_el:
            step = _parse_element(el)
            if step:
                steps.append(step)

        if not steps:
            logger.warning("No parseable steps in %s", path)
            return None

        estimated_tss = _estimate_tss(steps)
        source_tag = f"tr:{path.stem}" if author.lower().startswith("trainer") else f"zwo:{path.stem}"

        return Session(
            sport="bike",
            title=name,
            description=description or f"Imported from {path.name}",
            rationale=f"Imported workout — {author}".strip(" —"),
            steps=steps,
            estimated_tss=round(estimated_tss, 1),
        )

    def read_directory(self, directory: str | Path) -> List[Session]:
        """
        Read all .zwo files in a directory. Returns successfully parsed sessions.
        """
        directory = Path(directory)
        sessions = []
        for zwo_file in sorted(directory.glob("**/*.zwo")):
            session = self.read(zwo_file)
            if session:
                sessions.append(session)
        logger.info("Loaded %d workouts from %s", len(sessions), directory)
        return sessions


# ---------------------------------------------------------------------------
# Element parsers
# ---------------------------------------------------------------------------
def _parse_element(el: ET.Element) -> Optional[WorkoutStep]:
    tag = el.tag

    if tag == "Warmup":
        duration = int(el.get("Duration", 600))
        power_high = float(el.get("PowerHigh", 0.75))
        return WorkoutStep(
            type="warmup",
            duration_sec=duration,
            target_value=power_high,
            target_type="power",
            repeat=1,
            description="Warmup",
        )

    if tag == "Cooldown":
        duration = int(el.get("Duration", 600))
        power_high = float(el.get("PowerHigh", 0.50))
        return WorkoutStep(
            type="cooldown",
            duration_sec=duration,
            target_value=power_high,
            target_type="power",
            repeat=1,
            description="Cooldown",
        )

    if tag == "SteadyState":
        duration = int(el.get("Duration", 300))
        power = float(el.get("Power", 0.75))
        # Pick up any textevent
        note = _first_textevent(el)
        return WorkoutStep(
            type="interval",
            duration_sec=duration,
            target_value=power,
            target_type="power",
            repeat=1,
            description=note or f"{int(power * 100)}% FTP",
        )

    if tag == "IntervalsT":
        repeat = int(el.get("Repeat", 1))
        on_dur = int(el.get("OnDuration", 60))
        on_power = float(el.get("OnPower", 1.0))
        off_dur = int(el.get("OffDuration", 60))
        off_power = float(el.get("OffPower", 0.5))
        note = _first_textevent(el)

        # Model as the ON interval; off/recovery encoded in description
        return WorkoutStep(
            type="interval",
            duration_sec=on_dur,
            target_value=on_power,
            target_type="power",
            repeat=repeat,
            description=note or f"{int(on_power * 100)}% FTP × {repeat}, {off_dur}s @ {int(off_power * 100)}% recovery",
        )

    if tag == "Ramp":
        duration = int(el.get("Duration", 300))
        power_low = float(el.get("PowerLow", 0.60))
        power_high = float(el.get("PowerHigh", 1.00))
        return WorkoutStep(
            type="interval",
            duration_sec=duration,
            target_value=(power_low + power_high) / 2,
            target_type="power",
            repeat=1,
            description=f"Ramp {int(power_low * 100)}–{int(power_high * 100)}% FTP",
        )

    if tag == "FreeRide":
        duration = int(el.get("Duration", 1800))
        return WorkoutStep(
            type="interval",
            duration_sec=duration,
            target_value=0.65,
            target_type="power",
            repeat=1,
            description="Free ride — unstructured Z2",
        )

    if tag == "MaxEffort":
        duration = int(el.get("Duration", 30))
        return WorkoutStep(
            type="interval",
            duration_sec=duration,
            target_value=1.50,
            target_type="power",
            repeat=1,
            description="Max effort sprint",
        )

    return None


def _text(root: ET.Element, tag: str) -> str:
    el = root.find(tag)
    return (el.text or "").strip() if el is not None else ""


def _first_textevent(el: ET.Element) -> str:
    te = el.find("textevent")
    return te.get("message", "").strip() if te is not None else ""


# ---------------------------------------------------------------------------
# TSS estimator
# ---------------------------------------------------------------------------
def _estimate_tss(steps: List[WorkoutStep]) -> float:
    """
    Approximate TSS from step power fractions.
    TSS ≈ Σ (duration * IF²) / 36   where IF = power fraction.
    """
    total = 0.0
    for step in steps:
        if step.target_type != "power":
            continue
        duration = (step.duration_sec or 300) * step.repeat
        intensity = step.target_value
        total += (duration * intensity ** 2) / 36.0
    return total
