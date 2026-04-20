"""
Offline Bootstrap — seed InfluxDB from Garmin GDPR export.

Reads JSON activity summaries, HRV, and sleep data from the GDPR export
directory and writes historical time-series to InfluxDB.

Data sources (relative to GARMIN_EXPORT_DIR):
  Activities:  DI_CONNECT/DI-Connect-Fitness/*_summarizedActivities.json
  HRV/Health:  DI_CONNECT/DI-Connect-Wellness/*_healthStatusData.json
  Sleep:       DI_CONNECT/DI-Connect-Wellness/*_sleepData.json

Usage (local — InfluxDB on localhost:8086):
    python -m backend.data_ingestion.offline_bootstrap

Env overrides:
    GARMIN_EXPORT_DIR   path to extracted GDPR zip  (default: ./tmp/garmin_export)
    INFLUXDB_URL        override URL                 (default: http://localhost:8086)
    INFLUXDB_TOKEN      required
    INFLUXDB_ORG        (default: coaching)
    INFLUXDB_BUCKET     (default: training)
    ATHLETE_FTP         watts, used for bike TSS fallback  (default: 250)
    ATHLETE_LTHR        bpm, used for HR TSS fallback      (default: 162)
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from backend.storage.influx_client import InfluxClient
from backend.analysis.tss_calculators import calculate_run_tss

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] bootstrap: %(message)s",
)
logger = logging.getLogger(__name__)

EXPORT_DIR = Path(os.environ.get("GARMIN_EXPORT_DIR", "tmp/garmin_export"))

# Garmin sportType → canonical sport
_SPORT_TYPE_MAP = {
    "CYCLING": "bike",
    "RUNNING": "run",
    "SWIMMING": "swim",
}

# Garmin activityType (lower) → canonical sport
_ACTIVITY_TYPE_MAP = {
    "virtual_ride": "bike",
    "cycling": "bike",
    "indoor_cycling": "bike",
    "road_biking": "bike",
    "gravel_cycling": "bike",
    "mountain_biking": "bike",
    "running": "run",
    "trail_running": "run",
    "treadmill_running": "run",
    "track_running": "run",
    "open_water_swimming": "swim",
    "lap_swimming": "swim",
    "pool_swim": "swim",
}


def _map_sport(activity: dict) -> str:
    sport = _SPORT_TYPE_MAP.get(activity.get("sportType", ""))
    if sport:
        return sport
    sport = _ACTIVITY_TYPE_MAP.get((activity.get("activityType") or "").lower())
    if sport:
        return sport
    combined = f"{activity.get('sportType', '')} {activity.get('activityType', '')}".lower()
    if any(k in combined for k in ("cycl", "bike", "ride", "zwift")):
        return "bike"
    if "run" in combined:
        return "run"
    if "swim" in combined:
        return "swim"
    return "other"


def _get_tss(activity: dict, sport: str) -> float:
    """
    TSS resolution order:
      1. Garmin Firstbeat Training Load  (trainingLoadPeakSumSession) — most accurate
      2. Bike power formula using normPower or avgPower + assumed FTP
      3. HR-based TRIMP (Banister) fallback
      4. Flat 50 TSS/hr absolute fallback
    """
    # 1. Firstbeat Training Load
    fb = (activity.get("firstbeatData") or {}).get("results") or {}
    atl = fb.get("trainingLoadPeakSumSession")
    if atl and float(atl) > 0:
        return round(float(atl), 1)

    duration_ms = activity.get("duration") or activity.get("elapsedDuration") or 0
    duration_sec = int(duration_ms / 1000)
    if duration_sec <= 0:
        return 0.0

    # 2. Bike power
    if sport == "bike":
        ftp = float(os.environ.get("ATHLETE_FTP", "250"))
        np_watts = activity.get("normPower")
        avg_power = activity.get("avgPower")
        if not np_watts and avg_power:
            np_watts = avg_power * 0.97
        if np_watts and np_watts > 0 and ftp > 0:
            if_ = np_watts / ftp
            tss = (duration_sec * np_watts * if_) / (ftp * 3600) * 100
            return round(min(tss, 400.0), 1)

    # 3. HR-based TRIMP
    avg_hr = activity.get("avgHr")
    if avg_hr and avg_hr > 0:
        lthr = float(os.environ.get("ATHLETE_LTHR", "162"))
        return calculate_run_tss(duration_sec=duration_sec, avg_hr=avg_hr, lthr=lthr, method="hr")

    # 4. Flat fallback
    return round((duration_sec / 3600.0) * 50.0, 1)


def _parse_activities(export_dir: Path, influx: InfluxClient) -> int:
    fitness_dir = export_dir / "DI_CONNECT" / "DI-Connect-Fitness"
    files = sorted(fitness_dir.glob("*_summarizedActivities.json"))

    if not files:
        logger.error("No activity files found in %s", fitness_dir)
        return 0

    activity_count = 0
    daily_tss_map: dict = {}  # {date_str: {sport: float}}

    for filepath in files:
        logger.info("  Reading %s", filepath.name)
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        activities = data[0]["summarizedActivitiesExport"]

        for act in activities:
            ts_ms = act.get("beginTimestamp") or act.get("startTimeGmt")
            if not ts_ms:
                continue
            try:
                dt = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                continue

            sport = _map_sport(act)
            if sport == "other":
                continue

            duration_ms = act.get("duration") or act.get("elapsedDuration") or 0
            duration_sec = int(duration_ms / 1000)
            tss = _get_tss(act, sport)
            hr_avg = act.get("avgHr")
            power_avg = act.get("avgPower")

            try:
                influx.write_activity(
                    activity_time=dt,
                    sport=sport,
                    duration_sec=duration_sec,
                    tss=tss,
                    hr_avg=hr_avg,
                    power_avg=power_avg,
                )
            except Exception as exc:
                logger.warning("Activity write failed (%s): %s", dt.date(), exc)
                continue

            d_key = dt.strftime("%Y-%m-%d")
            daily_tss_map.setdefault(d_key, {}).setdefault(sport, 0.0)
            daily_tss_map[d_key][sport] += tss
            activity_count += 1

    # Write daily TSS aggregates for CTL/ATL/TSB calculation
    daily_points = 0
    for d_key, sports in daily_tss_map.items():
        dt = datetime.strptime(d_key, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        for sport, total_tss in sports.items():
            try:
                influx.write_daily_tss(dt, sport, total_tss)
                daily_points += 1
            except Exception as exc:
                logger.warning("Daily TSS write failed (%s %s): %s", d_key, sport, exc)

    logger.info(
        "Activities: %d imported → %d daily TSS points across %d days",
        activity_count, daily_points, len(daily_tss_map),
    )
    return activity_count


def _parse_hrv(export_dir: Path, influx: InfluxClient) -> int:
    wellness_dir = export_dir / "DI_CONNECT" / "DI-Connect-Wellness"
    files = sorted(wellness_dir.glob("*_healthStatusData.json"))

    hrv_count = 0
    for filepath in files:
        with open(filepath, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed HRV file: %s", filepath.name)
                continue

        for entry in data:
            date_str = entry.get("calendarDate")
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            for metric in entry.get("metrics", []):
                if metric.get("type") == "HRV" and metric.get("value") is not None:
                    try:
                        val = float(metric["value"])
                        if val > 0:
                            influx.write_hrv(dt, rmssd=val)
                            hrv_count += 1
                    except (ValueError, TypeError, Exception) as exc:
                        logger.warning("HRV write failed (%s): %s", date_str, exc)
                    break  # one HRV metric per day entry

    logger.info("HRV: %d daily readings from %d files", hrv_count, len(files))
    return hrv_count


def _parse_sleep(export_dir: Path, influx: InfluxClient) -> int:
    wellness_dir = export_dir / "DI_CONNECT" / "DI-Connect-Wellness"
    files = sorted(wellness_dir.glob("*_sleepData.json"))

    sleep_count = 0
    for filepath in files:
        with open(filepath, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed sleep file: %s", filepath.name)
                continue

        for entry in data:
            date_str = entry.get("calendarDate")
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            deep_sec = entry.get("deepSleepSeconds") or 0
            light_sec = entry.get("lightSleepSeconds") or 0
            rem_sec = entry.get("remSleepSeconds") or 0
            total_sec = deep_sec + light_sec + rem_sec

            if total_sec <= 0:
                continue

            try:
                influx.write_sleep(
                    date=dt,
                    total_sleep_sec=total_sec,
                    deep_sleep_sec=deep_sec,
                    rem_sleep_sec=rem_sec,
                )
                sleep_count += 1
            except Exception as exc:
                logger.warning("Sleep write failed (%s): %s", date_str, exc)

    logger.info("Sleep: %d days from %d files", sleep_count, len(files))
    return sleep_count


def run() -> None:
    logger.info("=== Offline Bootstrap starting ===")
    logger.info("Export dir: %s", EXPORT_DIR.resolve())

    if not EXPORT_DIR.exists():
        logger.error("Export directory not found: %s", EXPORT_DIR.resolve())
        return

    # When running locally, swap Docker-internal hostname for localhost
    influx_url = os.environ.get("INFLUXDB_URL", "http://localhost:8086")
    if "//influxdb:" in influx_url:
        influx_url = influx_url.replace("//influxdb:", "//localhost:")
        logger.info("Docker URL detected — using %s for local run", influx_url)

    influx = InfluxClient(url=influx_url)

    _parse_activities(EXPORT_DIR, influx)
    _parse_hrv(EXPORT_DIR, influx)
    _parse_sleep(EXPORT_DIR, influx)

    influx.close()
    logger.info("=== Offline Bootstrap complete ===")


if __name__ == "__main__":
    run()
