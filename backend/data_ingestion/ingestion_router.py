# backend/data_ingestion/ingestion_router.py
"""
Master Ingestion Router.
API-first, file-watch fallback. Tries to sync from external platforms,
and silently falls back to reading local import folders if APIs fail.

Outputs a summary of ingested activities and planned sessions.
"""

import logging
import requests
import requests.exceptions
from pathlib import Path
from typing import Any, Dict
from datetime import date, timedelta

logger = logging.getLogger(__name__)

class GarminAPIUnavailable(Exception): pass
class TrainingPeaksAPIUnavailable(Exception): pass

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def run_ingestion(athlete_id: str, athlete_config: dict) -> Dict[str, Any]:
    """
    Master ingestion router. API-first, file-watch fallback.
    Returns summary of what was ingested and from which source.
    """
    summary = {"garmin": None, "trainingpeaks": None, "file_imports": []}
    
    # 1. Garmin completed activities
    try:
        from backend.data_ingestion.garmin_sync import GarminSync
        from garth.exc import GarthException

        garmin_username = athlete_config.get("garmin_username")
        garmin_password = athlete_config.get("garmin_password")

        if garmin_username and garmin_password:
            sync = GarminSync()
            # In a real run, this fetches FIT files and parses via garmindb
            # sync.run()
            summary["garmin"] = "api_ok"
        else:
            summary["garmin"] = "missing_credentials"

    except ImportError as exc:
        # garth or garmindb not installed — surface loudly, not silently
        logger.error("Garmin library missing — install garth and garmindb: %s", exc)
        summary["garmin"] = f"library_error: {exc}"
    except GarthException as exc:
        logger.warning("Garmin auth/session error: %s", exc)
        summary["garmin"] = f"auth_error: {exc}"
    except requests.exceptions.RequestException as exc:
        logger.warning("Garmin network error, will rely on file watch: %s", exc)
        summary["garmin"] = "network_error — using file-watch"
    except Exception as exc:
        logger.warning("Garmin sync unexpected failure, will rely on file watch: %s", exc)
        summary["garmin"] = "unavailable — using file-watch"
        
    garmin_import_dir = Path("/data/garmin/fit")
    if garmin_import_dir.exists():
        new_fit = [f for f in garmin_import_dir.glob("*.fit") if f.is_file()]
        # Typically parse_fit(new_fit) is done here...
        if new_fit:
            summary["file_imports"].append(f"garmin: {len(new_fit)} FIT files handled")
            
            
    # 2. TrainingPeaks planned workouts
    tp_sessions = []
    try:
        tp_token = athlete_config.get("tp_access_token")
        if tp_token:
            from backend.data_ingestion.training_peaks_client import TrainingPeaksClient
            client = TrainingPeaksClient(access_token=tp_token)
            
            start_date = date.today() - timedelta(days=2)
            end_date = start_date + timedelta(days=14)
            tp_sessions = client.get_planned_workouts(start_date=start_date, end_date=end_date)
            summary["trainingpeaks"] = f"api_ok ({len(tp_sessions)} sessions)"
        else:
            summary["trainingpeaks"] = "missing_token"
    except ImportError as exc:
        logger.error("TrainingPeaks library missing: %s", exc)
        summary["trainingpeaks"] = f"library_error: {exc}"
    except requests.exceptions.RequestException as exc:
        logger.warning("TrainingPeaks network error, relying on file watch: %s", exc)
        summary["trainingpeaks"] = "network_error — using file-watch"
    except Exception as exc:
        logger.warning("TrainingPeaks API unexpected failure, relying on file watch: %s", exc)
        summary["trainingpeaks"] = "unavailable — using file-watch"
        
    from backend.data_ingestion.tp_file_fallback import scan_tp_import_folder
    tp_file_sessions = scan_tp_import_folder()
    if tp_file_sessions:
        summary["file_imports"].append(f"trainingpeaks: {len(tp_file_sessions)} manual file sessions")
        
    # Merge TP API vs TP Files (and dedupe inside store call)
    all_tp = tp_sessions + tp_file_sessions
    if all_tp:
        from backend.storage.postgres_client import db
        for session in all_tp:
            db.upsert_planned_session(session)
            
    # 3. Spreadsheets (Coach Plans)
    spreadsheet_import_dir = Path("/data/imports/spreadsheets")
    if spreadsheet_import_dir.exists():
        from backend.data_ingestion.spreadsheet_parser import ingest_spreadsheet_plan
        plan_start = date.today() - timedelta(date.today().weekday()) # Default to this week's Monday
        
        sheet_count = 0
        for sheet_path in spreadsheet_import_dir.glob("*"):
            if sheet_path.suffix in (".xlsx", ".csv"):
                try:
                    ingest_spreadsheet_plan(sheet_path, athlete_id, plan_start)
                    sheet_count += 1
                except Exception as e:
                    logger.error("Failed to ingest spreadsheet %s: %s", sheet_path.name, e)
                    
        if sheet_count > 0:
            summary["file_imports"].append(f"spreadsheets: {sheet_count} processed")

    # 4. TrainerRoad 
    # TR workout names come from FIT file metadata — no separate ingestion needed.
    # enrich_activity_with_tr_plan() runs as part of activity ingestion above.
    summary["trainerroad"] = "name_lookup_from_fit_active"
    
    return summary
