# backend/orchestration/monitor.py
"""
Pipeline monitoring — health checks and component status.

Provides:
  - GET /api/health — comprehensive system health check
  - Component-level health: PostgreSQL, InfluxDB, Ollama, Garmin tokens, ChromaDB
  - Last successful pipeline run timestamp
  - Data freshness checks (how old is the most recent Garmin sync?)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class PipelineMonitor:
    def __init__(
        self,
        influx_url: Optional[str] = None,
        ollama_url: Optional[str] = None,
        postgres_conn_str: Optional[str] = None,
    ):
        self.influx_url = influx_url or os.environ.get("INFLUXDB_URL", "http://localhost:8086")
        # Prefer OLLAMA_PRIMARY_URL (set by docker-compose); fall back to legacy OLLAMA_BASE_URL
        self.ollama_url = (
            ollama_url
            or os.environ.get("OLLAMA_PRIMARY_URL")
            or os.environ.get("OLLAMA_BASE_URL", "http://192.168.50.46:11434")
        )
        self.postgres_conn_str = postgres_conn_str

    def full_health_check(self) -> Dict[str, Any]:
        """
        Run health checks on all components.
        Returns structured status report.
        """
        checks = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall": "healthy",
            "components": {},
        }

        components = [
            ("influxdb",   self._check_influxdb),
            ("ollama",     self._check_ollama),
            ("postgresql", self._check_postgresql),
            ("garmin",     self._check_garmin_tokens),
        ]

        unhealthy = 0
        for name, func in components:
            try:
                result = func()
                checks["components"][name] = result
                if result.get("status") != "healthy":
                    unhealthy += 1
            except Exception as exc:
                checks["components"][name] = {
                    "status": "error",
                    "error": str(exc),
                }
                unhealthy += 1

        if unhealthy > 0:
            checks["overall"] = "degraded" if unhealthy < len(components) else "unhealthy"

        return checks

    # -----------------------------------------------------------------------
    # Component checks
    # -----------------------------------------------------------------------
    def _check_influxdb(self) -> Dict[str, Any]:
        """Check InfluxDB is reachable and responding."""
        try:
            resp = requests.get(f"{self.influx_url}/ping", timeout=5)
            return {
                "status": "healthy" if resp.status_code == 204 else "unhealthy",
                "url": self.influx_url,
                "response_code": resp.status_code,
            }
        except requests.RequestException as exc:
            return {"status": "unreachable", "url": self.influx_url, "error": str(exc)}

    def _check_ollama(self) -> Dict[str, Any]:
        """Check Ollama is running and has the configured model."""
        try:
            resp = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return {"status": "unhealthy", "url": self.ollama_url}

            models = resp.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            # Check both the fast model and heavy model are present
            fast_model  = os.environ.get("OLLAMA_FAST_MODEL",  os.environ.get("OLLAMA_MODEL", "llama3.1:8b"))
            heavy_model = os.environ.get("OLLAMA_HEAVY_MODEL", "qwen2.5:72b")
            has_fast  = any(fast_model  in n for n in model_names)
            has_heavy = any(heavy_model in n for n in model_names)

            if has_fast and has_heavy:
                status = "healthy"
            elif has_fast:
                status = "heavy_model_missing"
            else:
                status = "model_missing"

            return {
                "status": status,
                "url": self.ollama_url,
                "models_available": len(models),
                "fast_model": fast_model,
                "heavy_model": heavy_model,
                "fast_model_loaded": has_fast,
                "heavy_model_loaded": has_heavy,
            }
        except requests.RequestException as exc:
            return {"status": "unreachable", "url": self.ollama_url, "error": str(exc)}

    def _check_postgresql(self) -> Dict[str, Any]:
        """Check PostgreSQL connectivity."""
        try:
            import psycopg2
            conn_str = self.postgres_conn_str or os.environ.get(
                "DATABASE_URL", "postgresql://coaching:@postgres:5432/coaching"
            )
            conn = psycopg2.connect(conn_str, connect_timeout=5)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM planned_sessions")
                count = cur.fetchone()[0]
            conn.close()
            return {
                "status": "healthy",
                "planned_sessions": count,
            }
        except ImportError:
            return {"status": "driver_missing", "error": "psycopg2 not installed"}
        except Exception as exc:
            return {"status": "unhealthy", "error": str(exc)}

    def _check_garmin_tokens(self) -> Dict[str, Any]:
        """Check if Garmin/garth tokens exist and aren't expired."""
        from pathlib import Path
        garth_home = Path(os.environ.get("GARTH_HOME", "/data/garth"))
        token_file = garth_home / "oauth2_token"

        if not token_file.exists():
            return {
                "status": "no_tokens",
                "message": "Garth tokens not found — initial login required",
            }

        # Check token freshness
        import time
        age_hours = (time.time() - token_file.stat().st_mtime) / 3600

        return {
            "status": "healthy" if age_hours < 168 else "stale",
            "token_age_hours": round(age_hours, 1),
            "message": (
                "Tokens fresh"
                if age_hours < 168
                else f"Tokens are {age_hours:.0f}h old — may need refresh"
            ),
        }

    # -----------------------------------------------------------------------
    # Data freshness
    # -----------------------------------------------------------------------
    def check_data_freshness(self) -> Dict[str, Any]:
        """Check how fresh the pipeline data is."""
        from pathlib import Path
        log_dir = Path(os.environ.get("LOG_DIR", "/data/logs"))

        # Find most recent plan log
        plan_files = sorted(log_dir.glob("plan_*.json"))
        last_plan = None
        if plan_files:
            last_plan = plan_files[-1].stem.replace("plan_", "")

        return {
            "last_plan_generated": last_plan,
            "log_dir": str(log_dir),
            "total_plan_files": len(plan_files),
        }
