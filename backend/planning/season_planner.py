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
