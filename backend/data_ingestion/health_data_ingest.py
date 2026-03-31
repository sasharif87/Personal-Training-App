# backend/data_ingestion/health_data_ingest.py
"""
Health data ingestion endpoint.

Receives health data from iOS Shortcuts or Android Tasker
over the Tailscale VPN at POST /api/health-data.

Data sources:
  - Apple Health / Google Health Connect (menstrual cycle, resting HR, HRV)
  - Manual medication log
  - Supplemental metrics (CGM, SpO2, respiratory rate)

Data flows:
  cycle_data      → updates athlete profile cycle phase
  medication_log  → stored in health_data table
  supplemental    → written to InfluxDB as additional time series
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from backend.schemas.health_data import HealthDataPost, CycleData

logger = logging.getLogger(__name__)


class HealthDataIngester:
    def __init__(
        self,
        postgres_client=None,
        influx_client=None,
        profile_manager=None,
    ):
        self._pg = postgres_client
        self._influx = influx_client
        self._profile_manager = profile_manager

    def process(self, payload: HealthDataPost) -> Dict[str, Any]:
        """
        Process a health data sync payload.
        Returns a summary of what was stored.
        """
        result = {
            "athlete_id": payload.athlete_id,
            "timestamp": payload.timestamp,
            "cycle_updated": False,
            "medications_logged": 0,
            "supplemental_metrics": 0,
        }

        # --- Cycle data → profile update ---
        if payload.cycle_data:
            try:
                self._update_cycle_phase(payload.athlete_id, payload.cycle_data)
                result["cycle_updated"] = True
            except Exception as exc:
                logger.error("Cycle phase update failed: %s", exc)

        # --- Medication log entries → PostgreSQL ---
        for entry in payload.medication_entries:
            try:
                self._store_medication_entry(payload.athlete_id, entry.model_dump())
                result["medications_logged"] += 1
            except Exception as exc:
                logger.error("Medication log failed: %s", exc)

        # --- Supplemental metrics → InfluxDB ---
        for metric in payload.supplemental_metrics:
            try:
                self._store_supplemental_metric(metric.model_dump())
                result["supplemental_metrics"] += 1
            except Exception as exc:
                logger.error("Supplemental metric write failed: %s", exc)

        # --- Apple Watch resting metrics → InfluxDB ---
        if payload.apple_hrv and self._influx:
            try:
                self._influx.write_hrv(
                    date=datetime.fromisoformat(payload.timestamp),
                    rmssd=payload.apple_hrv,
                    hrv_score=None,
                )
            except Exception as exc:
                logger.error("Apple HRV write failed: %s", exc)

        logger.info(
            "Health data processed: cycle=%s, meds=%d, metrics=%d",
            result["cycle_updated"],
            result["medications_logged"],
            result["supplemental_metrics"],
        )
        return result

    def _update_cycle_phase(self, athlete_id: str, cycle_data: CycleData) -> None:
        if not self._profile_manager:
            return
        profile = self._profile_manager.load_profile(athlete_id)
        self._profile_manager.update_cycle_phase(profile, cycle_data.model_dump())
        self._profile_manager.save_profile(profile)

    def _store_medication_entry(self, athlete_id: str, entry: Dict) -> None:
        if not self._pg:
            return
        self._pg._exec_write(
            """
            INSERT INTO health_data (athlete_id, data_type, data_json, recorded_at)
            VALUES (%s, 'medication', %s::jsonb, %s)
            """,
            (athlete_id, json.dumps(entry), entry.get("timestamp")),
        )

    def _store_supplemental_metric(self, metric: Dict) -> None:
        if not self._influx:
            return
        from influxdb_client import Point, WritePrecision
        point = (
            Point("supplemental")
            .tag("metric", metric["metric_name"])
            .tag("source", metric.get("source", "unknown"))
            .field("value", float(metric["value"]))
            .time(
                datetime.fromisoformat(metric["timestamp"]),
                WritePrecision.SECONDS,
            )
        )
        self._influx._write_api.write(
            bucket=self._influx.bucket, org=self._influx.org, record=point
        )
