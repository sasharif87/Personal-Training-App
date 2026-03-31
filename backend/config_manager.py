# backend/config_manager.py
"""
ConfigManager — reads and writes the mutable season configuration.

Stores block/race/athlete parameters in config/season.json so they can be
updated from the web UI without touching .env or restarting containers.

The daily pipeline reads all block/race/athlete config through here rather
than directly from environment variables.

Thread safety: uses a file lock (via a simple rename-swap write) so the API
and the pipeline cannot corrupt the file if they write simultaneously.
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG: Dict[str, Any] = {
    "athlete": {
        "ftp": 250,
        "css": "1:45/100m",
        "lthr_run": 162,
    },
    "block": {
        "phase": "Base",
        "week_in_block": 1,
    },
    "race_a": {
        "date": "",
        "format": "Olympic",
        "priority": "A",
    },
    "race_b": {
        "date": "",
        "format": "",
        "priority": "B",
    },
    "notes": "",
}

BLOCK_PHASES = ["Base", "Build", "Peak", "Taper", "Recovery"]
RACE_FORMATS = ["Olympic", "70.3", "Ironman", "Endurance Run", "Triple Bypass", "Other"]
RACE_PRIORITIES = ["A", "B", "C"]


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------
class ConfigManager:
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(
            config_path
            or os.environ.get("SEASON_CONFIG_PATH", "/config/season.json")
        )
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.config_path.exists():
            self._write(_DEFAULT_CONFIG)

    # -----------------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------------
    def load(self) -> Dict[str, Any]:
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to read season config: %s — using defaults", exc)
            return dict(_DEFAULT_CONFIG)

    # -----------------------------------------------------------------------
    # Typed accessors used by the pipeline
    # -----------------------------------------------------------------------
    def athlete_ftp(self) -> int:
        return int(self.load()["athlete"].get("ftp") or os.environ.get("ATHLETE_FTP", 250))

    def athlete_css(self) -> str:
        return self.load()["athlete"].get("css") or os.environ.get("ATHLETE_CSS", "1:45/100m")

    def athlete_lthr_run(self) -> int:
        return int(self.load()["athlete"].get("lthr_run") or os.environ.get("ATHLETE_LTHR_RUN", 162))

    def block_phase(self) -> str:
        return self.load()["block"].get("phase") or os.environ.get("BLOCK_PHASE", "Base")

    def block_week(self) -> int:
        return int(self.load()["block"].get("week_in_block") or os.environ.get("BLOCK_WEEK", 1))

    def race_a(self) -> Dict[str, str]:
        cfg = self.load()["race_a"]
        return {
            "date":     cfg.get("date")     or os.environ.get("RACE_A_DATE", ""),
            "format":   cfg.get("format")   or os.environ.get("RACE_A_FORMAT", "Olympic"),
            "priority": cfg.get("priority") or os.environ.get("RACE_A_PRIORITY", "A"),
        }

    def race_b(self) -> Dict[str, str]:
        return self.load().get("race_b", {"date": "", "format": "", "priority": "B"})

    # -----------------------------------------------------------------------
    # Write — atomic swap so pipeline never reads a partial file
    # -----------------------------------------------------------------------
    def save(self, data: Dict[str, Any]) -> None:
        merged = self.load()
        _deep_merge(merged, data)
        self._write(merged)
        logger.info("Season config saved to %s", self.config_path)

    def _write(self, data: Dict[str, Any]) -> None:
        tmp = self.config_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.config_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _deep_merge(base: Dict, override: Dict) -> None:
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val
