# backend/data_ingestion/race_result_ingest.py
"""
Race result ingestion — post-race analysis and storage.

After a race:
  1. Athlete fills a short post-race form (RPE, splits, conditions, fueling)
  2. System pulls Garmin activity data for the race
  3. Pacing analysis: fade %, discipline comparison vs targets
  4. CTL correlation: fitness at race vs result
  5. Results embedded as high-value vectors in ChromaDB for RAG retrieval
"""

import json
import logging
import uuid
from datetime import date
from typing import Any, Dict, Optional

from backend.schemas.race_event import RaceResult

logger = logging.getLogger(__name__)


class RaceResultIngester:
    def __init__(self, postgres_client=None, vector_db=None):
        self._pg = postgres_client
        self._vector_db = vector_db

    # -----------------------------------------------------------------------
    # Store race result
    # -----------------------------------------------------------------------
    def store_result(self, result: RaceResult) -> None:
        """Store a race result in PostgreSQL and embed in ChromaDB."""
        if self._pg:
            try:
                self._pg._exec_write(
                    """
                    INSERT INTO race_results
                        (event_id, result_json, recorded_at)
                    VALUES (%s, %s::jsonb, NOW())
                    ON CONFLICT (event_id) DO UPDATE SET
                        result_json = EXCLUDED.result_json,
                        recorded_at = NOW()
                    """,
                    (result.event_id, result.model_dump_json()),
                )
                logger.info("Race result stored for event %s", result.event_id)
            except Exception as exc:
                logger.error("Failed to store race result: %s", exc)

        # Embed in ChromaDB for RAG retrieval
        if self._vector_db:
            try:
                summary = self._build_rag_summary(result)
                self._vector_db.add_historical_block(
                    block_text=summary,
                    metadata={
                        "type": "race_result",
                        "event_id": result.event_id,
                        "date": date.today().isoformat(),
                    },
                    block_id=f"race_{result.event_id}",
                )
                logger.info("Race result embedded in ChromaDB")
            except Exception as exc:
                logger.warning("ChromaDB embedding failed: %s", exc)

    # -----------------------------------------------------------------------
    # Pacing analysis
    # -----------------------------------------------------------------------
    def analyse_pacing(self, result: RaceResult) -> Dict[str, Any]:
        """
        Analyse race pacing patterns.
        Returns pacing quality assessment.
        """
        analysis: Dict[str, Any] = {"event_id": result.event_id}

        # Run pace fade
        if result.run_pace_fade_pct is not None:
            if result.run_pace_fade_pct < 5:
                analysis["run_pacing"] = "excellent"
                analysis["run_pacing_note"] = "Even pacing — strong execution"
            elif result.run_pace_fade_pct < 10:
                analysis["run_pacing"] = "good"
                analysis["run_pacing_note"] = f"Moderate fade ({result.run_pace_fade_pct:.1f}%)"
            else:
                analysis["run_pacing"] = "poor"
                analysis["run_pacing_note"] = (
                    f"Significant fade ({result.run_pace_fade_pct:.1f}%) "
                    "— review bike intensity and nutrition"
                )

        # Bike power analysis
        if result.bike_avg_power and result.bike_np:
            vi = result.bike_np / result.bike_avg_power  # Variability Index
            analysis["bike_variability_index"] = round(vi, 3)
            if vi > 1.06:
                analysis["bike_pacing_note"] = (
                    f"VI = {vi:.3f} — surging detected. More even power distribution "
                    "would save run legs."
                )
            else:
                analysis["bike_pacing_note"] = f"VI = {vi:.3f} — steady effort, good pacing"

        # Overall subjective
        feels = [
            r for r in [result.swim_feel, result.bike_feel, result.run_feel]
            if r is not None
        ]
        if feels:
            analysis["avg_feel"] = round(sum(feels) / len(feels), 1)

        return analysis

    # -----------------------------------------------------------------------
    # CTL correlation
    # -----------------------------------------------------------------------
    def correlate_fitness(self, result: RaceResult) -> Optional[Dict[str, Any]]:
        """
        Correlate fitness metrics at race with result.
        Returns context for future race preparation.
        """
        if not result.ctl_at_race:
            return None

        return {
            "event_id": result.event_id,
            "ctl_at_race": result.ctl_at_race,
            "atl_at_race": result.atl_at_race,
            "tsb_at_race": result.tsb_at_race,
            "overall_feel": result.overall_feel,
            "note": (
                f"Raced at CTL={result.ctl_at_race:.0f}, "
                f"TSB={result.tsb_at_race:.0f}. "
                f"Felt: {result.overall_feel or '?'}/10"
            ),
        }

    # -----------------------------------------------------------------------
    # RAG summary for ChromaDB embedding
    # -----------------------------------------------------------------------
    def _build_rag_summary(self, result: RaceResult) -> str:
        """Build a text summary for vector embedding."""
        parts = [f"Race result for event {result.event_id}."]

        if result.overall_time_sec:
            mins = result.overall_time_sec // 60
            parts.append(f"Overall time: {mins // 60}h{mins % 60}m.")

        if result.ctl_at_race:
            parts.append(
                f"Fitness: CTL={result.ctl_at_race:.0f}, "
                f"ATL={result.atl_at_race:.0f}, "
                f"TSB={result.tsb_at_race:.0f}."
            )

        if result.run_pace_fade_pct is not None:
            parts.append(f"Run pace fade: {result.run_pace_fade_pct:.1f}%.")

        if result.bike_np:
            parts.append(f"Bike NP: {result.bike_np:.0f}W.")

        if result.conditions_notes:
            parts.append(f"Conditions: {result.conditions_notes}.")

        if result.fueling_notes:
            parts.append(f"Fueling: {result.fueling_notes}.")

        if result.athlete_notes:
            parts.append(f"Notes: {result.athlete_notes}.")

        return " ".join(parts)
