# tests/conftest.py
"""
Test fixtures for the AI Coaching System.

Uses mocked clients by default. For integration tests requiring real
PostgreSQL, set TEST_DATABASE_URL env var.

For integration tests with real containers, use testcontainers-python:
    pip install testcontainers[postgres]
"""

import os
import json
import pytest
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pandas as pd


# ---------------------------------------------------------------------------
# Mocked storage clients
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_postgres():
    """Mocked PostgresClient — no database needed."""
    pg = MagicMock()
    pg.get_active_monthly_plan.return_value = {
        "block_phase": "Base",
        "weeks": [
            {
                "week_number": 1,
                "block_phase": "Base",
                "weekly_rationale": "Test week",
                "sessions": [],
            }
        ],
    }
    pg.get_planned_sessions.return_value = []
    pg.get_upcoming_races.return_value = []
    pg.get_recent_execution_summary.return_value = {}
    pg.get_recent_post_session_logs.return_value = []
    return pg


@pytest.fixture
def mock_influx():
    """Mocked InfluxClient — no InfluxDB needed."""
    influx = MagicMock()
    influx.get_daily_tss.return_value = pd.Series(
        [40, 55, 30, 60, 50, 45, 35],
        index=pd.date_range(end=date.today(), periods=7),
    )
    influx.get_hrv_trend.return_value = {"trend": "stable", "avg": 52.0}
    influx.get_yesterday_activities.return_value = []
    influx.close.return_value = None
    return influx


@pytest.fixture
def mock_ollama():
    """Mocked OllamaClient — no Ollama server needed."""
    from backend.orchestration.llm_client import OllamaClient

    ollama = MagicMock(spec=OllamaClient)
    ollama.model = "test-model"
    ollama.generate_morning_decision.return_value = {
        "conflict_level": "clear",
        "signal_summary": "All signals nominal",
        "primary": {
            "sport": "run",
            "title": "Easy run",
            "description": "30 min easy",
            "rationale": "Recovery",
            "steps": [{"type": "warmup", "duration_sec": 600, "target_value": 0.65, "target_type": "hr"}],
            "estimated_tss": 30,
        },
        "alt": None,
        "recommendation": "primary",
    }
    ollama.generate_weekly_review.return_value = {
        "week_number": 1,
        "block_phase": "Base",
        "weekly_rationale": "No changes",
        "changes_rationale": "No adjustments needed.",
        "sessions": [],
    }
    ollama.generate_monthly_plan.return_value = {
        "block_phase": "Base",
        "month_rationale": "Building base",
        "weeks": [],
    }
    return ollama


@pytest.fixture
def mock_notifier():
    """Mocked Notifier — no network calls."""
    notifier = MagicMock()
    notifier.send_ntfy.return_value = True
    notifier.send_email.return_value = True
    notifier.morning_readout.return_value = None
    notifier.pipeline_failure.return_value = None
    return notifier


@pytest.fixture
def mock_vector_db():
    """Mocked VectorDB — no ChromaDB needed."""
    vdb = MagicMock()
    vdb.retrieve_similar_blocks.return_value = []
    vdb.count.return_value = 0
    return vdb


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_daily_tss_series():
    return pd.Series(
        [40, 55, 30, 60, 50, 45, 35, 70, 40, 55, 65, 50, 45, 60],
        index=pd.date_range(end=date.today(), periods=14),
    )


@pytest.fixture
def sample_config():
    return {
        "athlete": {"ftp": 250, "css": "1:45/100m", "lthr_run": 162},
        "block": {"phase": "Base", "week_in_block": 1},
        "race_a": {"date": "2026-12-01", "format": "Olympic", "priority": "A"},
        "race_b": {"date": "", "format": "", "priority": "B"},
        "notes": "",
    }


@pytest.fixture
def sample_workout_step():
    return {
        "type": "interval",
        "duration_sec": 300,
        "target_value": 0.9,
        "target_type": "power",
        "repeat": 5,
        "description": "5x5min at FTP",
    }


@pytest.fixture
def sample_session():
    return {
        "sport": "bike",
        "title": "Sweet Spot Intervals",
        "description": "4x10min sweet spot",
        "rationale": "Build aerobic base",
        "estimated_tss": 75,
        "steps": [
            {"type": "warmup", "duration_sec": 600, "target_value": 0.55, "target_type": "power", "repeat": 1},
            {"type": "interval", "duration_sec": 600, "target_value": 0.88, "target_type": "power", "repeat": 4},
            {"type": "cooldown", "duration_sec": 300, "target_value": 0.5, "target_type": "power", "repeat": 1},
        ],
    }


@pytest.fixture
def sample_planned_session():
    return {
        "session_id": "test-001",
        "source_platform": "system",
        "import_method": "test",
        "planned_date": date.today().isoformat(),
        "sport": "run",
        "title": "Easy Run",
        "coaching_text": "30 min easy run",
        "planned_duration_min": 30.0,
        "planned_tss": 25.0,
    }


@pytest.fixture
def sample_biometrics():
    return {
        "hrv_this_morning": 55.0,
        "hrv_7d_avg": 52.0,
        "resting_hr": 48,
        "sleep_hours": 7.5,
        "sleep_quality": 0.85,
    }