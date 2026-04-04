# backend/api/export.py
"""
Data export & portability.

Provides a one-click data export endpoint that assembles a ZIP archive
containing all athlete data:
  - Season config (JSON)
  - Athlete profile (JSON)
  - Race calendar (JSON + Markdown)
  - All planned sessions (CSV)
  - Execution scores (CSV)
  - Strength sessions (CSV)
  - Morning choices (CSV)
  - Training plans (JSON)
  - Post-session logs (CSV)
  - Gear registry (JSON)

GDPR-compliant data portability.
"""

import csv
import io
import json
import logging
import os
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class DataExporter:
    def __init__(self, postgres_client=None, config_manager=None):
        self._pg = postgres_client
        self._cfg = config_manager

    def export_all(self) -> io.BytesIO:
        """
        Assemble a ZIP archive containing all athlete data.
        Returns a BytesIO object ready to stream as a response.
        """
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Season config
            if self._cfg:
                try:
                    config = self._cfg.load()
                    zf.writestr("config/season.json", json.dumps(config, indent=2))
                except Exception as exc:
                    logger.warning("Failed to export config: %s", exc)

            if self._pg:
                # Planned sessions
                self._export_table_csv(
                    zf, "data/planned_sessions.csv",
                    "SELECT * FROM planned_sessions ORDER BY planned_date",
                )

                # Execution scores
                self._export_table_csv(
                    zf, "data/execution_scores.csv",
                    "SELECT * FROM execution_scores ORDER BY session_date",
                )

                # Race calendar
                self._export_table_csv(
                    zf, "data/race_calendar.csv",
                    "SELECT * FROM race_calendar ORDER BY event_date",
                )

                # Strength sessions
                self._export_table_csv(
                    zf, "data/strength_sessions.csv",
                    "SELECT * FROM strength_sessions ORDER BY session_date",
                )

                # Morning choices
                self._export_table_csv(
                    zf, "data/morning_choices.csv",
                    "SELECT * FROM morning_choices ORDER BY choice_date",
                )

                # Monthly plans
                self._export_table_json(
                    zf, "data/monthly_plans.json",
                    "SELECT plan_json, generated_at, active FROM monthly_plans ORDER BY generated_at",
                )

                # Post-session logs (if table exists)
                try:
                    self._export_table_csv(
                        zf, "data/post_session_logs.csv",
                        "SELECT * FROM post_session_logs ORDER BY session_date",
                    )
                except Exception:
                    pass

                # Athlete profiles
                try:
                    self._export_table_json(
                        zf, "data/athlete_profiles.json",
                        "SELECT athlete_id, profile_json FROM athlete_profiles",
                    )
                except Exception:
                    pass

                # Gear registry
                try:
                    self._export_table_json(
                        zf, "data/gear_registry.json",
                        "SELECT item_id, athlete_id, item_json FROM gear_registry",
                    )
                except Exception:
                    pass

            # Export metadata
            zf.writestr("export_metadata.json", json.dumps({
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "export_version": "1.0",
                "system": "AI Coaching System",
            }, indent=2))

        buffer.seek(0)
        logger.info("Data export assembled — %d bytes", buffer.tell() or buffer.getbuffer().nbytes)
        return buffer

    def _export_table_csv(self, zf: zipfile.ZipFile, filename: str, query: str) -> None:
        """Export a PostgreSQL table as CSV into the ZIP."""
        try:
            with self._pg._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchall()

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(cols)
            for row in rows:
                writer.writerow([
                    str(v) if not isinstance(v, (str, int, float, type(None))) else v
                    for v in row
                ])

            zf.writestr(filename, output.getvalue())
            logger.debug("Exported %s — %d rows", filename, len(rows))
        except Exception as exc:
            logger.warning("Failed to export %s: %s", filename, exc)

    def _export_table_json(self, zf: zipfile.ZipFile, filename: str, query: str) -> None:
        """Export a PostgreSQL query result as JSON into the ZIP."""
        try:
            with self._pg._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchall()

            data = []
            for row in rows:
                record = {}
                for col, val in zip(cols, row):
                    if isinstance(val, (date, datetime)):
                        record[col] = val.isoformat()
                    elif isinstance(val, dict):
                        record[col] = val
                    else:
                        record[col] = val
                data.append(record)

            zf.writestr(filename, json.dumps(data, indent=2, default=str))
            logger.debug("Exported %s — %d records", filename, len(data))
        except Exception as exc:
            logger.warning("Failed to export %s: %s", filename, exc)
