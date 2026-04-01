# backend/data_ingestion/tp_file_fallback.py
"""
TrainingPeaks file fallback parser.
Handles CSV and JSON exports from TrainingPeaks when the API fails.
"""

import csv
import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from dateutil import parser as dp

from backend.storage.postgres_client import db
from backend.data_ingestion.training_peaks_client import _SPORT_MAP

logger = logging.getLogger(__name__)

TP_IMPORT_DIR = Path("/data/imports/trainingpeaks")
TP_IMPORT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# File Watch / Loading Logic
# ---------------------------------------------------------------------------
def load_tp_calendar_csv(csv_path: Path) -> List[Dict]:
    """
    Parse a TrainingPeaks calendar export CSV into unified planned_session schema.
    TP CSV includes: date, title, duration, TSS, IF, description, sport type.
    """
    from backend.data_ingestion.training_peaks_client import _safe_div

    sessions = []
    try:
        with open(csv_path, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                sport_raw = row.get("Sport", "")
                sport = _SPORT_MAP.get(sport_raw, sport_raw.lower() if sport_raw else "other")
                
                planned_date = row.get("Date")
                if not planned_date:
                    continue
                # Parse robustly to YYYY-MM-DD
                parsed_date = dp.parse(planned_date).date()
                
                title = row.get("Title", "")
                
                sessions.append({
                    "session_id": f"tp_file_{uuid.uuid5(uuid.NAMESPACE_DNS, str(parsed_date) + title).hex[:8]}",
                    "source_platform": "trainingpeaks",
                    "import_method": "file_watch",
                    "planned_date": parsed_date.isoformat(),
                    "sport": sport,
                    "title": title,
                    "coaching_text": row.get("Description", ""),
                    "planned_duration_min": _parse_duration(row.get("Duration")),
                    "planned_tss": float(row["TSS"]) if row.get("TSS") else None,
                    "planned_if": float(row["IF"]) if row.get("IF") else None,
                    "planned_distance_m": None,
                    "planned_elevation_m": None,
                    "structure": {},   # CSV doesn't include interval structure
                    "targets": {}
                })
    except Exception as exc:
        logger.error("Failed to parse TP CSV %s: %s", csv_path.name, exc)
    
    return sessions

def load_tp_workout_json(json_path: Path) -> List[Dict]:
    """
    Parse a single TrainingPeaks workout export (JSON).
    Relies on the same normalizer used in the API client if possible.
    """
    from backend.data_ingestion.training_peaks_client import TrainingPeaksClient
    client = TrainingPeaksClient(access_token="mock", user_id=0) # dummy init for _normalise
    
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [client._normalise(w) for w in raw]
        else:
            return [client._normalise(raw)]
    except Exception as exc:
        logger.error("Failed to parse TP JSON %s: %s", json_path.name, exc)
    
    return []

def scan_tp_import_folder() -> List[Dict]:
    """Watch for new TP exports and process them."""
    new_files = [f for f in TP_IMPORT_DIR.glob("*") if f.suffix in (".csv", ".json", ".xml")]
    sessions = []
    for f in new_files:
        if f.suffix == ".csv":
            file_sessions = load_tp_calendar_csv(f)
            sessions.extend(file_sessions)
            logger.info("Parsed %d sessions from TP CSV: %s", len(file_sessions), f.name)
        elif f.suffix == ".json":
            file_sessions = load_tp_workout_json(f)
            sessions.extend(file_sessions)
            logger.info("Parsed %d sessions from TP JSON: %s", len(file_sessions), f.name)
            
        _mark_processed(f)
        
    return sessions

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_duration(duration_str: str) -> Optional[float]:
    """TP CSV 'Duration' often '1:30' representing 1hr 30m."""
    if not duration_str:
        return None
    try:
        parts = duration_str.split(":")
        if len(parts) == 3: # H:M:S
            return float(parts[0]) * 60 + float(parts[1]) + float(parts[2]) / 60
        elif len(parts) == 2: # H:M
            if int(parts[0]) > 23: # likely M:S
                return float(parts[0]) + float(parts[1]) / 60
            return float(parts[0]) * 60 + float(parts[1])
        return float(duration_str)  # Try flat float
    except Exception:
        return None

def _mark_processed(path: Path) -> None:
    """Move processed file to an archive subfolder to avoid re-reading."""
    archive_dir = path.parent / "archive"
    archive_dir.mkdir(exist_ok=True)
    try:
        path.rename(archive_dir / path.name)
    except Exception as exc:
        logger.error("Failed to move %s to archive: %s", path.name, exc)
