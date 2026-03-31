# backend/data_ingestion/garmin_sync.py
"""
GarminSyncManager — pulls activity, HRV, and sleep data from Garmin Connect.

Two complementary approaches:
  1. garmindb  — syncs FIT files locally; provides rich historical data
  2. garth     — direct Connect API access; used for reading recent HRV/readiness
                 and writing structured workout definitions back to Garmin

On first run garth will prompt for MFA. After that, tokens persist in GARTH_HOME.
garmindb uses a config pointing to GARMIN_DATA_DIR.
"""

import os
import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GarminSyncManager
# ---------------------------------------------------------------------------
class GarminSyncManager:
    def __init__(
        self,
        garmin_data_dir: Optional[str] = None,
        garth_home: Optional[str] = None,
    ):
        self.garmin_data_dir = Path(garmin_data_dir or os.environ.get("GARMIN_DATA_DIR", "/data/garmin"))
        self.garth_home = Path(garth_home or os.environ.get("GARTH_HOME", "/data/garth"))
        self.garmin_data_dir.mkdir(parents=True, exist_ok=True)
        self.garth_home.mkdir(parents=True, exist_ok=True)
        self._garth_client = None

    # -----------------------------------------------------------------------
    # garth client (lazy-init, tokens persisted to GARTH_HOME)
    # -----------------------------------------------------------------------
    def _get_garth(self):
        if self._garth_client is not None:
            return self._garth_client

        try:
            import garth
        except ImportError:
            raise RuntimeError("garth is not installed — add it to requirements.txt")

        token_file = self.garth_home / "oauth2_token"
        if token_file.exists():
            garth.resume(str(self.garth_home))
        else:
            username = os.environ.get("GARMIN_USERNAME")
            password = os.environ.get("GARMIN_PASSWORD")
            if not username or not password:
                raise RuntimeError("GARMIN_USERNAME and GARMIN_PASSWORD must be set for initial garth login")
            garth.login(username, password)
            garth.save(str(self.garth_home))

        self._garth_client = garth
        return garth

    # -----------------------------------------------------------------------
    # Full garmindb sync (pulls new FIT files + writes to garmindb SQLite)
    # -----------------------------------------------------------------------
    def sync_garmindb(self) -> None:
        """
        Runs garmindb_cli to pull recent activities from Garmin Connect
        and update the local garmindb SQLite databases.

        garmindb stores data under GARMIN_DATA_DIR:
          activities/  — FIT files
          FitFiles/    — raw FIT archive
          garmin.db    — SQLite summary database
          garmin_activities.db
          garmin_monitoring.db  (HRV, stress, body battery)
        """
        try:
            import garmindb
            from garmindb.garmindb import GarminDb, Attributes, Sleep, HrvDb
        except ImportError:
            raise RuntimeError("garmindb is not installed — add it to requirements.txt")

        import subprocess
        logger.info("Running garmindb sync into %s", self.garmin_data_dir)
        result = subprocess.run(
            [
                "python", "-m", "garmindb_cli",
                "--all", "--latest",
                "--data_dir", str(self.garmin_data_dir),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("garmindb sync stderr: %s", result.stderr)
            raise RuntimeError(f"garmindb sync failed (exit {result.returncode})")
        logger.info("garmindb sync complete")

    # -----------------------------------------------------------------------
    # Read recent activities from garmindb SQLite
    # -----------------------------------------------------------------------
    def get_recent_activities(self, days: int = 7) -> List[Dict]:
        """
        Query garmindb SQLite for recent activities.
        Returns list of dicts: {date, sport, duration_sec, tss, hr_avg, ...}
        """
        db_path = self.garmin_data_dir / "garmin_activities.db"
        if not db_path.exists():
            logger.warning("garmindb activities database not found at %s — run sync first", db_path)
            return []

        cutoff = (date.today() - timedelta(days=days)).isoformat()
        activities = []
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT
                    start_time,
                    sport,
                    sub_sport,
                    elapsed_time AS duration_sec,
                    avg_hr,
                    avg_power,
                    avg_pace,
                    training_effect,
                    tss
                FROM activities
                WHERE DATE(start_time) >= ?
                ORDER BY start_time DESC
                """,
                (cutoff,),
            )
            for row in cursor:
                activities.append({
                    "time": row["start_time"],
                    "sport": _normalise_sport(row["sport"], row["sub_sport"]),
                    "duration_sec": row["duration_sec"],
                    "hr_avg": row["avg_hr"],
                    "power_avg": row["avg_power"],
                    "pace_avg": row["avg_pace"],
                    "tss": row["tss"],
                })
            conn.close()
        except sqlite3.Error as exc:
            logger.error("SQLite query failed: %s", exc)

        return activities

    # -----------------------------------------------------------------------
    # Read HRV from garmindb monitoring DB
    # -----------------------------------------------------------------------
    def get_hrv_readings(self, days: int = 14) -> List[Dict]:
        """
        Returns recent HRV morning readiness readings.
        {date, rmssd, hrv_score}
        """
        db_path = self.garmin_data_dir / "garmin_monitoring.db"
        if not db_path.exists():
            logger.warning("garmindb monitoring database not found — run sync first")
            return []

        cutoff = (date.today() - timedelta(days=days)).isoformat()
        readings = []
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            # garmindb stores HRV summary in stress_events or hrv_weekly table
            # Field names vary by garmindb version — try both
            for table in ("hrv_weekly", "stress_events"):
                try:
                    cursor = conn.execute(
                        f"SELECT day, rmssd, hrv_status FROM {table} WHERE day >= ? ORDER BY day",
                        (cutoff,),
                    )
                    for row in cursor:
                        readings.append({
                            "date": row["day"],
                            "rmssd": row["rmssd"],
                            "hrv_score": row.get("hrv_status"),
                        })
                    if readings:
                        break
                except sqlite3.OperationalError:
                    continue
            conn.close()
        except sqlite3.Error as exc:
            logger.error("SQLite HRV query failed: %s", exc)

        return readings

    # -----------------------------------------------------------------------
    # Read yesterday's summary for pipeline context
    # -----------------------------------------------------------------------
    def get_yesterday_summary(self) -> Dict:
        """
        Returns a concise dict describing yesterday's training for the LLM context.
        """
        activities = self.get_recent_activities(days=2)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        yesterday_activities = [a for a in activities if a["time"].startswith(yesterday)]
        hrv = self.get_hrv_readings(days=2)
        latest_hrv = hrv[-1] if hrv else {}

        return {
            "date": yesterday,
            "activities": yesterday_activities,
            "hrv": latest_hrv,
            "total_tss": sum(a.get("tss") or 0 for a in yesterday_activities),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalise_sport(sport: Optional[str], sub_sport: Optional[str]) -> str:
    if not sport:
        return "unknown"
    s = sport.lower()
    ss = (sub_sport or "").lower()
    if s in ("cycling", "biking", "virtual_ride", "indoor_cycling") or ss == "virtual_race":
        return "bike"
    if s in ("running", "trail_running", "treadmill_running"):
        return "run"
    if s == "swimming" or ss in ("lap_swimming", "open_water"):
        return "swim"
    if s == "multisport" or "brick" in s:
        return "brick"
    return s
