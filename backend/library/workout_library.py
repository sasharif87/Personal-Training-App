# backend/library/workout_library.py
"""
WorkoutLibrary — unified workout index across all sources.

Sources indexed on startup:
  1. config/workouts/swim.json      — curated swim sessions
  2. config/workouts/run.json       — curated run sessions
  3. WORKOUT_IMPORT_DIR/*.zwo       — TrainerRoad / Zwift exports (bike)
  4. WORKOUT_IMPORT_DIR/*.tcx       — TrainingPeaks exports (any sport)

All workouts are stored as Session objects in memory with a searchable index.

Search:
  find_by_name("Carson")           → fuzzy title match, returns top N
  find_by_sport("swim")            → all swim workouts
  find_by_tags(["css", "build"])   → workouts with all given tags
  lookup("Carson +2")              → best single match by name (used by pipeline)

The LLM can reference workouts by name in its output; the pipeline calls lookup()
to replace the Session stub with the full structured session from the library.

Import workflow (for new TR/TP files):
  Call library.import_file(path) to index a new .zwo or .tcx file at runtime.
  The library updates its index without restart.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from backend.schemas.workout import Session
from backend.library.zwo_reader import ZwoReader
from backend.library.tcx_reader import TCXReader

logger = logging.getLogger(__name__)

_WORKOUTS_DIR = os.environ.get("WORKOUTS_CONFIG_DIR", "/config/workouts")
_IMPORT_DIR   = os.environ.get("WORKOUT_IMPORT_DIR",  "/config/workouts/imports")


# ---------------------------------------------------------------------------
# WorkoutLibrary
# ---------------------------------------------------------------------------
class WorkoutLibrary:
    def __init__(
        self,
        workouts_dir: Optional[str] = None,
        import_dir: Optional[str] = None,
        athlete_ftp: int = 250,
        athlete_lthr: int = 162,
    ):
        self.workouts_dir = Path(workouts_dir or _WORKOUTS_DIR)
        self.import_dir = Path(import_dir or _IMPORT_DIR)
        self.import_dir.mkdir(parents=True, exist_ok=True)

        self._zwo_reader = ZwoReader()
        self._tcx_reader = TCXReader(athlete_ftp=athlete_ftp, athlete_lthr=athlete_lthr)

        # title (normalised) → Session
        self._index: Dict[str, Session] = {}
        self._load_all()

    # -----------------------------------------------------------------------
    # Build index
    # -----------------------------------------------------------------------
    def _load_all(self) -> None:
        count_before = len(self._index)

        # 1. Built-in JSON libraries
        for sport_file in ("swim.json", "run.json"):
            path = self.workouts_dir / sport_file
            if path.exists():
                self._load_json_library(path)

        # 2. .zwo imports (TrainerRoad / Zwift)
        for zwo_file in sorted(self.import_dir.glob("**/*.zwo")):
            session = self._zwo_reader.read(zwo_file)
            if session:
                self._index_session(session)

        # 3. .tcx imports (TrainingPeaks)
        for tcx_file in sorted(self.import_dir.glob("**/*.tcx")):
            for session in self._tcx_reader.read(tcx_file):
                self._index_session(session)

        added = len(self._index) - count_before
        logger.info("WorkoutLibrary: indexed %d workouts total (+%d new)", len(self._index), added)

    def _load_json_library(self, path: Path) -> None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to read workout library %s: %s", path, exc)
            return

        sport = path.stem  # "swim" or "run"
        for entry in raw:
            try:
                session = Session(
                    sport=sport,
                    title=entry["title"],
                    description=entry.get("description", ""),
                    rationale=", ".join(entry.get("tags", [])),
                    steps=[],  # Will be populated below
                    estimated_tss=entry.get("estimated_tss", 0.0),
                )
                # Build WorkoutStep objects from the JSON dicts
                from backend.schemas.workout import WorkoutStep
                session.steps = [WorkoutStep(**s) for s in entry.get("steps", [])]
                self._index_session(session)
            except Exception as exc:
                logger.warning("Skipping malformed entry '%s': %s", entry.get("title", "?"), exc)

    def _index_session(self, session: Session) -> None:
        key = _normalise(session.title)
        if key in self._index:
            logger.debug("Overwriting duplicate key '%s'", key)
        self._index[key] = session

    # -----------------------------------------------------------------------
    # Import new file at runtime
    # -----------------------------------------------------------------------
    def import_file(self, path: str | Path) -> List[Session]:
        """
        Index a .zwo or .tcx file. Returns the sessions added.
        File is copied to import_dir if it isn't already there.
        """
        path = Path(path)
        dest = self.import_dir / path.name
        if path != dest:
            import shutil
            shutil.copy2(path, dest)
            logger.info("Copied %s → %s", path.name, dest)

        sessions = []
        if path.suffix.lower() == ".zwo":
            session = self._zwo_reader.read(dest)
            if session:
                self._index_session(session)
                sessions.append(session)
        elif path.suffix.lower() == ".tcx":
            sessions = self._tcx_reader.read(dest)
            for s in sessions:
                self._index_session(s)
        else:
            logger.warning("Unsupported file type: %s", path.suffix)

        return sessions

    # -----------------------------------------------------------------------
    # Search API
    # -----------------------------------------------------------------------
    def lookup(self, name: str) -> Optional[Session]:
        """
        Best single match by name. Exact key match first, then fuzzy.
        Used by pipeline to resolve LLM-referenced workout names.
        """
        key = _normalise(name)
        if key in self._index:
            return self._index[key]
        results = self._fuzzy_search(key, top_n=1)
        return results[0] if results else None

    def find_by_name(self, name: str, top_n: int = 5) -> List[Session]:
        """Fuzzy name search, returns top N matches."""
        key = _normalise(name)
        if key in self._index:
            return [self._index[key]]
        return self._fuzzy_search(key, top_n=top_n)

    def find_by_sport(self, sport: str) -> List[Session]:
        """All workouts for a given sport."""
        sport = sport.lower()
        return [s for s in self._index.values() if s.sport == sport]

    def find_by_tags(self, tags: List[str]) -> List[Session]:
        """
        Workouts whose rationale/description contains all given tags.
        Tags are stored in session.rationale for JSON-sourced workouts.
        """
        tags_lower = [t.lower() for t in tags]
        results = []
        for session in self._index.values():
            haystack = (session.rationale + " " + session.description).lower()
            if all(t in haystack for t in tags_lower):
                results.append(session)
        return results

    def all_sessions(self) -> List[Session]:
        return list(self._index.values())

    def summary(self) -> Dict[str, int]:
        """Returns {sport: count} breakdown."""
        counts: Dict[str, int] = {}
        for s in self._index.values():
            counts[s.sport] = counts.get(s.sport, 0) + 1
        return counts

    # -----------------------------------------------------------------------
    # Fuzzy search
    # -----------------------------------------------------------------------
    def _fuzzy_search(self, query: str, top_n: int = 5) -> List[Session]:
        """
        Simple token-overlap similarity. Good enough for workout name matching.
        "carson plus two" matches "carson +2" etc.
        """
        query_tokens = set(query.split())
        scored = []
        for key, session in self._index.items():
            key_tokens = set(key.split())
            overlap = len(query_tokens & key_tokens)
            if overlap == 0:
                continue
            # Boost for prefix match
            prefix_bonus = 2 if key.startswith(list(query_tokens)[0]) else 0
            scored.append((overlap + prefix_bonus, session))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:top_n]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalise(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for index keys."""
    s = name.lower()
    s = re.sub(r"[+/\-]", " ", s)           # +2 → 2, 70.3 → 70 3
    s = re.sub(r"[^\w\s]", "", s)           # strip remaining punctuation
    s = re.sub(r"\s+", " ", s).strip()
    return s
