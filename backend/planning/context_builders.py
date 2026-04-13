# backend/planning/context_builders.py
"""
Compatibility shim — re-exports the canonical context builder functions.

The real implementations live in:
  backend/orchestration/llm_client.py   — build_*_context functions
  backend/analysis/signal_importance.py — assess_signal_conflict

All pipeline modules (daily_pipeline, weekly_pipeline, monthly_pipeline) import
directly from those canonical locations.  This file exists so that any external
code that imports from `backend.planning.context_builders` continues to work.
"""

from backend.orchestration.llm_client import (  # noqa: F401
    build_monthly_generation_context,
    build_morning_decision_context,
    build_weekly_review_context,
)
from backend.analysis.signal_importance import assess_signal_conflict  # noqa: F401

__all__ = [
    "build_monthly_generation_context",
    "build_weekly_review_context",
    "build_morning_decision_context",
    "assess_signal_conflict",
]
