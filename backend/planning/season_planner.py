# backend/planning/season_planner.py
"""
SeasonPlanner — derives training block structure from the race calendar.

Given a list of upcoming races with priority and taper/recovery windows,
this module:
  1. Determines the current block phase (Base, Build, Peak, Taper, Recovery)
  2. Calculates weeks remaining to A-race
  3. Detects phase transitions that trigger monthly plan regeneration
  4. Generates a high-level TSS arc preview for season visualisation
"""

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Phase → typical weekly TSS multiplier relative to baseline
_PHASE_TSS_MULTIPLIERS = {
    "Base":     0.85,
    "Build":    1.00,
    "Peak":     1.10,
    "Taper":    0.60,
    "Recovery": 0.50,
}


class SeasonPlanner:
    def __init__(self, races: List[Dict], baseline_weekly_tss: float = 400):
        """
        races: list of race dicts from PostgreSQL (get_upcoming_races)
        baseline_weekly_tss: athlete's typical build-phase weekly TSS
        """
        self.races = sorted(races, key=lambda r: r.get("event_date", "9999"))
        self.baseline_tss = baseline_weekly_tss

    # -----------------------------------------------------------------------
    # Current block phase detection
    # -----------------------------------------------------------------------
    def detect_current_phase(self) -> Dict[str, any]:
        """
        Determine the current training phase based on proximity to races.

        Returns:
            {
                "phase": "Build",
                "a_race_name": "Ironman 70.3 Quassy",
                "a_race_date": "2026-09-20",
                "weeks_to_a_race": 24,
                "weeks_in_block": 3,
                "trigger_monthly_regen": False
            }
        """
        today = date.today()

        a_race = self._find_a_race()
        if not a_race:
            return {
                "phase": "Base",
                "a_race_name": None,
                "a_race_date": None,
                "weeks_to_a_race": None,
                "weeks_in_block": 1,
                "trigger_monthly_regen": False,
            }

        a_date = date.fromisoformat(str(a_race["event_date"])[:10])
        weeks_to_race = max(0, (a_date - today).days // 7)

        # Check if we're in taper or recovery for any race
        for race in self.races:
            taper = race.get("taper_start")
            recovery_end = race.get("recovery_end")
            race_date = str(race.get("event_date", ""))[:10]

            if taper and today >= date.fromisoformat(str(taper)[:10]) and today < date.fromisoformat(race_date):
                return self._build_result("Taper", a_race, weeks_to_race, race)
            if recovery_end and today >= date.fromisoformat(race_date) and today <= date.fromisoformat(str(recovery_end)[:10]):
                return self._build_result("Recovery", a_race, weeks_to_race, race)

        # Phase detection from weeks-out
        phase = self._phase_from_weeks(weeks_to_race)

        return self._build_result(phase, a_race, weeks_to_race)

    def _find_a_race(self) -> Optional[Dict]:
        """Find the nearest A-priority race."""
        today = date.today()
        for race in self.races:
            if race.get("priority") == "A":
                race_date = date.fromisoformat(str(race["event_date"])[:10])
                if race_date >= today:
                    return race
        # Fallback: nearest race of any priority
        for race in self.races:
            race_date = date.fromisoformat(str(race["event_date"])[:10])
            if race_date >= today:
                return race
        return None

    def _phase_from_weeks(self, weeks_to_race: int) -> str:
        """Determine phase from weeks to A-race."""
        if weeks_to_race > 16:
            return "Base"
        if weeks_to_race > 8:
            return "Build"
        if weeks_to_race > 3:
            return "Peak"
        return "Build"  # Close but not in taper — let taper window handle it

    def _build_result(
        self, phase: str, a_race: Dict, weeks_to_race: int, current_race: Optional[Dict] = None
    ) -> Dict:
        return {
            "phase": phase,
            "a_race_name": a_race.get("name"),
            "a_race_date": str(a_race.get("event_date", ""))[:10],
            "weeks_to_a_race": weeks_to_race,
            "weeks_in_block": 1,  # Will be tracked by config_manager
            "trigger_monthly_regen": False,
            "context_race": current_race.get("name") if current_race else None,
        }

    # -----------------------------------------------------------------------
    # TSS arc preview — season-level visualisation
    # -----------------------------------------------------------------------
    def generate_tss_arc(self, weeks_ahead: int = 26) -> List[Dict]:
        """
        Generate a weekly TSS arc preview from today through weeks_ahead.
        Shows expected load trajectory for season visualisation.
        """
        today = date.today()
        arc = []

        for week_offset in range(weeks_ahead):
            week_start = today + timedelta(weeks=week_offset)
            week_end = week_start + timedelta(days=6)

            phase = self._phase_for_date(week_start)
            multiplier = _PHASE_TSS_MULTIPLIERS.get(phase, 0.85)
            target_tss = round(self.baseline_tss * multiplier)

            # Recovery week pattern: every 4th week is reduced
            if (week_offset + 1) % 4 == 0 and phase not in ("Taper", "Recovery"):
                target_tss = round(target_tss * 0.65)  # Recovery week

            arc.append({
                "week": week_offset + 1,
                "start_date": week_start.isoformat(),
                "end_date": week_end.isoformat(),
                "phase": phase,
                "target_tss": target_tss,
                "is_recovery_week": (week_offset + 1) % 4 == 0,
            })

        return arc

    def _phase_for_date(self, check_date: date) -> str:
        """Determine phase for a specific date."""
        for race in self.races:
            taper = race.get("taper_start")
            recovery_end = race.get("recovery_end")
            race_date_str = str(race.get("event_date", ""))[:10]
            if not race_date_str:
                continue
            race_date = date.fromisoformat(race_date_str)

            if taper and check_date >= date.fromisoformat(str(taper)[:10]) and check_date < race_date:
                return "Taper"
            if recovery_end and check_date >= race_date and check_date <= date.fromisoformat(str(recovery_end)[:10]):
                return "Recovery"

        a_race = self._find_a_race()
        if not a_race:
            return "Base"

        a_date = date.fromisoformat(str(a_race["event_date"])[:10])
        weeks_out = max(0, (a_date - check_date).days // 7)
        return self._phase_from_weeks(weeks_out)

    # -----------------------------------------------------------------------
    # Phase transition detection (triggers monthly regen)
    # -----------------------------------------------------------------------
    def check_phase_transition(self, current_stored_phase: str) -> Tuple[bool, str]:
        """
        Check if a phase transition has occurred.
        Returns (transition_occurred, new_phase).
        """
        detected = self.detect_current_phase()
        new_phase = detected["phase"]
        transition = new_phase != current_stored_phase
        if transition:
            logger.info("Phase transition detected: %s → %s", current_stored_phase, new_phase)
        return transition, new_phase

# ---------------------------------------------------------------------------
# URL-Based Event Extraction
# ---------------------------------------------------------------------------
def extract_event_from_url(url: str, llm_client) -> dict:
    """
    Fetch event page and use LLM to extract race details.
    Handles most structured race registration sites.
    """
    import requests
    from bs4 import BeautifulSoup
    from backend.planning.llm_prompts import EVENT_EXTRACTION_PROMPT
    import json
    
    # Fetch page content
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    soup = BeautifulSoup(resp.content, "html.parser")
    
    # Strip navigation, footers, scripts — keep main content
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    
    # Extract text with a strict token budget
    text = soup.get_text(separator="\\n", strip=True)[:5000]
    
    extraction_prompt = f"{EVENT_EXTRACTION_PROMPT}\\n\\nPage content:\\n{text}"

    # Use the passed LLM client
    response_text = llm_client.generate(extraction_prompt)
    
    try:
        # Strip trailing markdown if the model hallucinated code blocks around the JSON
        clean_text = response_text.strip("```json").strip("```").strip()
        event = json.loads(clean_text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse LLM response into JSON: {response_text}")
        raise ValueError("LLM did not return valid JSON.")
        
    event["source_url"] = url
    event["extracted_at"] = date.today().isoformat()
    return event

# ---------------------------------------------------------------------------
# Database Logging
# ---------------------------------------------------------------------------
def classify_and_store_event(event: dict, priority: str) -> dict:
    """
    Store event with A/B/C priority and compute taper/recovery windows.
    Generates a new race_calendar.md directly on export.
    """
    from backend.storage.postgres_client import db
    
    event_date = date.fromisoformat(event["date"])
    event_format = event.get("format", "unknown")
    taper_days, recovery_days = get_taper_recovery(priority, event_format)
    
    event.update({
        "priority": priority,
        "taper_start": (event_date - timedelta(days=taper_days)).isoformat(),
        "recovery_end": (event_date + timedelta(days=recovery_days)).isoformat(),
        "event_id": f"race_{event_date.strftime('%Y%m%d')}_{priority}"
    })
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS race_calendar (
            event_id TEXT PRIMARY KEY,
            name TEXT,
            date DATE,
            location TEXT,
            sport TEXT,
            format TEXT,
            distance_label TEXT,
            swim_distance_m NUMERIC,
            bike_distance_km NUMERIC,
            run_distance_km NUMERIC,
            elevation_gain_m NUMERIC,
            registration_deadline DATE,
            event_url TEXT,
            source_url TEXT,
            extracted_at TIMESTAMPTZ,
            priority TEXT,
            taper_start DATE,
            recovery_end DATE
        )
    """)
    
    db.execute("""
        INSERT INTO race_calendar (
            event_id, name, date, location, sport, format, distance_label,
            swim_distance_m, bike_distance_km, run_distance_km, elevation_gain_m,
            registration_deadline, event_url, source_url, extracted_at, priority, taper_start, recovery_end
        ) VALUES (
            %(event_id)s, %(name)s, %(date)s, %(location)s, %(sport)s, %(format)s, %(distance_label)s,
            %(swim_distance_m)s, %(bike_distance_km)s, %(run_distance_km)s, %(elevation_gain_m)s,
            %(registration_deadline)s, %(event_url)s, %(source_url)s, %(extracted_at)s, %(priority)s, %(taper_start)s, %(recovery_end)s
        ) ON CONFLICT (event_id) DO UPDATE SET
            priority = EXCLUDED.priority,
            taper_start = EXCLUDED.taper_start,
            recovery_end = EXCLUDED.recovery_end
    """, event)
    
    export_race_calendar_md()   # regenerate human-readable .md on every update
    return event

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_taper_recovery(priority: str, race_format: str) -> tuple[int, int]:
    """Return (taper_days, recovery_days) for priority + format combination."""
    matrix = {
        ("A", "Ironman"):     (14, 21),
        ("A", "70.3"):        (12, 14),
        ("A", "Olympic"):     (10, 7),
        ("A", "marathon"):    (14, 14),
        ("B", "Ironman"):     (7, 7),
        ("B", "70.3"):        (5, 5),
        ("B", "Olympic"):     (5, 3),
        ("B", "marathon"):    (7, 5),
        ("C", "Olympic"):     (2, 1),
        ("C", "half_marathon"): (2, 1),
    }
    return matrix.get((priority, race_format), (7, 5))   # sensible default

def export_race_calendar_md(output_path: str = "/data/imports/race_calendar.md") -> None:
    """
    Export current race calendar to Markdown.
    Regenerated on every event add/update/reclassify.
    """
    from backend.storage.postgres_client import db
    
    try:
        events = db.query("SELECT * FROM race_calendar ORDER BY date ASC")
        
        lines = [
            "# Race Calendar\\n",
            f"_Last updated: {date.today().isoformat()}_\\n\\n",
            "| Date | Event | Format | Priority | Taper Starts | Recovery End |",
            "|---|---|---|---|---|---|"
        ]
        
        for e in events:
            priority_label = {"A": "🔴 A", "B": "🟡 B", "C": "🟢 C"}.get(e.get("priority"), e.get("priority"))
            lines.append(
                f"| {e.get('date')} | {e.get('name')} | {e.get('format')} | {priority_label} "
                f"| {e.get('taper_start')} | {e.get('recovery_end')} |"
            )
        
        lines.append("\\n---\\n")
        for e in events:
            lines.append(f"## {e.get('name')} — {e.get('date')}")
            lines.append(f"- **Location:** {e.get('location', 'TBC')}")
            lines.append(f"- **Format:** {e.get('format')} ({e.get('distance_label', '')})")
            lines.append(f"- **Priority:** {e.get('priority')}")
            if e.get("swim_distance_m"): lines.append(f"- **Swim:** {e['swim_distance_m']}m")
            if e.get("bike_distance_km"): lines.append(f"- **Bike:** {e['bike_distance_km']}km")
            if e.get("run_distance_km"): lines.append(f"- **Run:** {e['run_distance_km']}km")
            if e.get("elevation_gain_m"): lines.append(f"- **Elevation:** {e['elevation_gain_m']}m gain")
            lines.append(f"- **Taper window:** {e.get('taper_start')} → {e.get('date')}")
            lines.append(f"- **Recovery window:** {e.get('date')} → {e.get('recovery_end')}")
            lines.append("")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\\n".join(lines))
    except Exception as e:
        logger.error(f"Failed to export race calendar: {e}")
