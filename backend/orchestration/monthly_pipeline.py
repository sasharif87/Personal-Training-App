# backend/orchestration/monthly_pipeline.py
"""
MonthlyPipeline — generates the full mesocycle.

Fires: 1st of each month, or on block phase transition.
Cost:  expensive (70B, ~3k–5k token output) — run once, store result.

Steps:
  1. Pull race calendar and block position from config/postgres
  2. Pull current fitness state from InfluxDB
  3. Pull prior month execution summary from PostgreSQL
  4. RAG: retrieve similar historical blocks
  5. Call Ollama monthly generation prompt
  6. Validate and store MonthPlan in PostgreSQL
  7. Push week 1 to devices immediately; queue weeks 2-4
"""

import logging
import os
from datetime import date, datetime, timezone
from typing import Optional

from backend.config_manager import ConfigManager
from backend.storage.influx_client import InfluxClient
from backend.storage.postgres_client import PostgresClient
from backend.rag.vector_db import VectorDB
from backend.orchestration.llm_client import (
    OllamaClient,
    build_monthly_generation_context,
)
from backend.analysis.fitness_models import calculate_ctl_atl_tsb
from backend.schemas.workout import MonthPlan

logger = logging.getLogger(__name__)


class MonthlyPipeline:
    def __init__(
        self,
        influx: Optional[InfluxClient] = None,
        postgres: Optional[PostgresClient] = None,
        vector_db: Optional[VectorDB] = None,
        llm: Optional[OllamaClient] = None,
        config: Optional[ConfigManager] = None,
    ):
        self.influx = influx or InfluxClient()
        self.postgres = postgres or PostgresClient()
        self.vector_db = vector_db or VectorDB()
        self.llm = llm or OllamaClient()
        self.cfg = config or ConfigManager()

    def run(self, dry_run: bool = False) -> MonthPlan:
        logger.info("=== Monthly generation starting — %s ===", date.today().isoformat())

        # --- Fitness state ---
        tss_series = self.influx.get_daily_tss(days=120)
        hrv_trend = self.influx.get_hrv_trend(days=14)
        if tss_series.empty:
            ctl, atl, tsb = 0.0, 0.0, 0.0
        else:
            ctl_s, atl_s, tsb_s = calculate_ctl_atl_tsb(tss_series)
            ctl, atl, tsb = float(ctl_s.iloc[-1]), float(atl_s.iloc[-1]), float(tsb_s.iloc[-1])

        cfg_data = self.cfg.load()
        athlete = {
            "ftp": self.cfg.athlete_ftp(),
            "css_sec_per_100m": self.cfg.athlete_css(),
            "lthr_run": self.cfg.athlete_lthr_run(),
        }
        block = {
            "phase":           self.cfg.block_phase(),
            "week_in_block":   self.cfg.block_week(),
        }
        fitness = {"ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(tsb, 1), "hrv_trend": hrv_trend}

        # --- Race calendar ---
        races = self.postgres.get_upcoming_races()
        race_calendar = [
            {k: str(v) if hasattr(v, "isoformat") else v for k, v in r.items()}
            for r in races
        ]

        # --- Vacation windows ---
        vacations = []
        try:
            vacations = self.postgres.get_upcoming_vacations()
        except Exception as exc:
            logger.warning("Could not load vacation windows (non-fatal): %s", exc)

        # --- Prior month execution summary ---
        prior_scores = self.postgres.get_recent_execution_summary(days=30)
        prior_summary = {
            "sessions_by_sport": prior_scores,
            "notes": cfg_data.get("notes", ""),
        }

        # --- RAG ---
        rag_query = f"block phase {block['phase']}, CTL {ctl:.0f} ATL {atl:.0f} TSB {tsb:.0f}"
        retrieved = self.vector_db.retrieve_similar_blocks(rag_query, n_results=3)

        context = build_monthly_generation_context(
            athlete_state={**athlete, **fitness},
            block=block,
            race_calendar=race_calendar,
            prior_month_summary=prior_summary,
            retrieved_history=retrieved,
            vacation_windows=vacations,
        )

        # --- LLM call ---
        logger.info("Calling Ollama monthly generation (model: %s)", self.llm.model)
        try:
            raw = self.llm.generate_monthly_plan(context)
            plan = MonthPlan.model_validate(raw)
        except Exception as exc:
            logger.error("MonthPlan generation/validation failed: %s", exc)
            # Fallback: return previous active plan so the pipeline doesn't leave
            # the athlete with no plan for the month.
            prev = self.postgres.get_active_monthly_plan()
            if prev:
                logger.warning("Returning previous active plan as fallback")
                try:
                    return MonthPlan.model_validate(prev)
                except Exception:
                    pass
            raise

        logger.info(
            "Generated month plan — phase: %s, weeks: %d",
            plan.block_phase, len(plan.weeks)
        )

        if not dry_run:
            plan_dict = plan.model_dump()
            plan_dict["generated_at"] = datetime.now(timezone.utc).isoformat()
            self.postgres.save_monthly_plan(plan_dict)
            logger.info("Monthly plan stored in PostgreSQL")

            # Seed ChromaDB with this block for future RAG retrieval
            _seed_chromadb(self.vector_db, plan, fitness)

        return plan


# ---------------------------------------------------------------------------
# ChromaDB seeding
# ---------------------------------------------------------------------------
def _seed_chromadb(vector_db: VectorDB, plan: "MonthPlan", fitness: dict) -> None:
    """Store the generated block summary in ChromaDB for future RAG retrieval."""
    try:
        week_summaries = []
        for week in plan.weeks:
            sessions = []
            for day in (week.days or []):
                if day.primary:
                    sessions.append(f"{day.primary.sport} {day.primary.title} ~{day.primary.estimated_tss:.0f}TSS")
            week_summaries.append(
                f"Week {week.week_number} ({week.block_phase}): target {week.target_tss}TSS — "
                + ", ".join(sessions[:4])
            )

        text = (
            f"Block: {plan.block_phase} | "
            f"CTL {fitness.get('ctl', 0):.0f} ATL {fitness.get('atl', 0):.0f} TSB {fitness.get('tsb', 0):.0f} | "
            f"HRV: {fitness.get('hrv_trend', 'unknown')}\n"
            + "\n".join(week_summaries)
        )

        block_id = f"{plan.block_phase}_{date.today().isoformat()}"
        vector_db.store_block(
            block_id=block_id,
            text=text,
            metadata={
                "phase": plan.block_phase,
                "generated_at": date.today().isoformat(),
                "ctl": fitness.get("ctl", 0),
                "atl": fitness.get("atl", 0),
                "tsb": fitness.get("tsb", 0),
                "rationale": plan.month_rationale or "",
            },
        )
        logger.info("Block seeded to ChromaDB: %s", block_id)
    except Exception as exc:
        logger.warning("ChromaDB seed failed (non-fatal): %s", exc)
