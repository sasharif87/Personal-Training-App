# backend/output/zwift_writer.py
"""
Zwift .zwo workout file writer.

Converts a Session schema into Zwift's XML workout format and writes the
.zwo file to the configured workouts directory (ZWIFT_WORKOUTS_DIR).

Zwift .zwo structure reference:
  <workout_file>
    <author/>  <name/>  <description/>  <sportType>bike</sportType>
    <workout>
      <Warmup      Duration="sec" PowerLow="ftp_frac" PowerHigh="ftp_frac"/>
      <SteadyState Duration="sec" Power="ftp_frac"/>
      <IntervalsT  Repeat="n" OnDuration="sec" OffDuration="sec"
                   OnPower="ftp_frac" OffPower="ftp_frac"/>
      <Cooldown    Duration="sec" PowerLow="ftp_frac" PowerHigh="ftp_frac"/>
    </workout>
  </workout_file>

Power targets in WorkoutStep are already stored as FTP fractions (target_type == "power").
"""

import os
import logging
import re
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET
from xml.dom import minidom

from backend.schemas.workout import Session, WorkoutStep

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ZwiftWriter
# ---------------------------------------------------------------------------
class ZwiftWriter:
    def __init__(self, workouts_dir: Optional[str] = None):
        self.workouts_dir = Path(workouts_dir or os.environ.get("ZWIFT_WORKOUTS_DIR", "/data/zwift_workouts"))
        self.workouts_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Public: write session → .zwo file
    # -----------------------------------------------------------------------
    def write(self, session: Session, filename: Optional[str] = None) -> Path:
        """
        Converts a Session to a .zwo file and writes it to ZWIFT_WORKOUTS_DIR.
        Returns the path to the written file.
        Only processes bike sessions; raises ValueError for other sports.
        """
        if session.sport not in ("bike", "brick"):
            raise ValueError(f"ZwiftWriter only handles bike/brick sessions, got '{session.sport}'")

        xml_str = _build_zwo(session)
        safe_name = _safe_filename(session.title)
        out_path = self.workouts_dir / f"{safe_name}.zwo"
        out_path.write_text(xml_str, encoding="utf-8")
        logger.info("Wrote Zwift workout: %s", out_path)
        return out_path


# ---------------------------------------------------------------------------
# XML builder
# ---------------------------------------------------------------------------
def _build_zwo(session: Session) -> str:
    root = ET.Element("workout_file")
    ET.SubElement(root, "author").text = "AI Coach"
    ET.SubElement(root, "name").text = session.title
    ET.SubElement(root, "description").text = session.description
    ET.SubElement(root, "sportType").text = "bike"

    workout_el = ET.SubElement(root, "workout")
    for step in session.steps:
        _append_step(workout_el, step)

    raw = ET.tostring(root, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ")


def _append_step(parent: ET.Element, step: WorkoutStep) -> None:
    step_type = step.type.lower()
    duration = step.duration_sec or 300
    power = step.target_value if step.target_type == "power" else 0.75

    if step_type == "warmup":
        el = ET.SubElement(parent, "Warmup")
        el.set("Duration", str(duration * step.repeat))
        el.set("PowerLow", f"{max(0.30, power - 0.30):.2f}")
        el.set("PowerHigh", f"{power:.2f}")

    elif step_type == "cooldown":
        el = ET.SubElement(parent, "Cooldown")
        el.set("Duration", str(duration * step.repeat))
        el.set("PowerHigh", f"{max(0.30, power - 0.30):.2f}")
        el.set("PowerLow", f"{power:.2f}")

    elif step_type == "interval" and step.repeat > 1:
        # Paired interval: assume the next recovery is baked into description
        recovery_power = max(0.40, power - 0.40)
        recovery_duration = max(60, duration // 2)
        el = ET.SubElement(parent, "IntervalsT")
        el.set("Repeat", str(step.repeat))
        el.set("OnDuration", str(duration))
        el.set("OffDuration", str(recovery_duration))
        el.set("OnPower", f"{power:.2f}")
        el.set("OffPower", f"{recovery_power:.2f}")

    elif step_type == "recovery":
        el = ET.SubElement(parent, "SteadyState")
        el.set("Duration", str(duration * step.repeat))
        el.set("Power", f"{min(power, 0.60):.2f}")

    else:
        # Default: SteadyState
        el = ET.SubElement(parent, "SteadyState")
        el.set("Duration", str(duration * step.repeat))
        el.set("Power", f"{power:.2f}")

    if step.description:
        note = ET.SubElement(el, "textevent")
        note.set("timeoffset", "0")
        note.set("message", step.description[:80])


def _safe_filename(title: str) -> str:
    return re.sub(r"[^\w\-]", "_", title).strip("_")[:60]
