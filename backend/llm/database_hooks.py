# backend/llm/database_hooks.py
"""
Persists the final LLM decisions, morning selections, and contexts
into the PostgreSQL layer for fine-tuning inside Phase E.
"""

import json
from datetime import date
from typing import Dict, Any, Optional

from backend.storage.postgres_client import db

def _ensure_athlete_choices_table() -> None:
    """Bootstrap the athlete_choices table. Called once at module load."""
    try:
        db.execute("""
            CREATE TABLE IF NOT EXISTS athlete_choices (
                id SERIAL PRIMARY KEY,
                session_date DATE NOT NULL,
                choice TEXT NOT NULL CHECK (choice IN ('primary', 'alt', 'missed')),
                reason TEXT,
                biometrics_snapshot JSONB,
                execution_score_next_day JSONB,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)
    except Exception:
        pass  # Table bootstrap is best-effort — schema may already exist

_ensure_athlete_choices_table()


def log_athlete_choice(session_date: str, choice: str, reason: Optional[str], biometrics_snapshot: Dict[str, Any]) -> None:
    """
    Log whether athlete took primary or alt, and why if provided.
    This data is the explicitly tracked training signal for future HRV weighting calibration.
    """
    
    db.execute("""
        INSERT INTO athlete_choices
        (session_date, choice, reason, biometrics_snapshot, execution_score_next_day)
        VALUES (%(session_date)s, %(choice)s, %(reason)s, %(biometrics)s, NULL)
    """, {
        "session_date": session_date,
        "choice": choice,
        "reason": reason,
        "biometrics": json.dumps(biometrics_snapshot)
    })
    
def update_execution_outcome(session_date: str, execution_score: Dict[str, Any]) -> None:
    """
    Postgres Trigger-equivalent wrapper.
    Called the DAY AFTER an `athlete_choice` when the Garmin data syncs.
    It stamps the result of yesterday's LLM choice with reality so the ML model can learn.
    """
    db.execute("""
        UPDATE athlete_choices
        SET execution_score_next_day = %(score)s
        WHERE session_date = %(session_date)s
    """, {
        "session_date": session_date,
        "score": json.dumps(execution_score)
    })

def retrieve_recent_choices(limit: int = 30) -> list:
    """Pull the last N days of decision vs reality."""
    return db.query("""
        SELECT session_date, choice, reason, biometrics_snapshot, execution_score_next_day
        FROM athlete_choices 
        ORDER BY session_date DESC 
        LIMIT %s
    """, (limit,))
