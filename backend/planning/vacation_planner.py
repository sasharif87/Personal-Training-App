# backend/planning/vacation_planner.py
"""
VacationPlanner — manages vacation/travel windows and equipment constraints.

Responsibilities:
  - Session type constraint logic based on available equipment
  - Environmental adaptation (heat, altitude, timezone)
  - Training retreat block generation
  - Pre/post vacation load management
"""

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from backend.schemas.vacation import (
    VacationWindow,
    VacationType,
    EquipmentChecklist,
    EnvironmentalFactors,
    RetreatConfig,
)

logger = logging.getLogger(__name__)


class VacationPlanner:
    def __init__(self, postgres_client=None):
        self._pg = postgres_client

    # -----------------------------------------------------------------------
    # Equipment-constrained session filtering
    # -----------------------------------------------------------------------
    def get_available_sports(self, equipment: EquipmentChecklist) -> List[str]:
        """
        Determine which sports are possible given available equipment.
        Always includes run (just needs shoes) and bodyweight work.
        """
        sports = ["run"]  # running shoes are almost always available

        if equipment.pool_access or equipment.open_water_access:
            sports.append("swim")
        if equipment.road_bike or equipment.smart_trainer or equipment.race_bike:
            sports.append("bike")
        if equipment.gym_access:
            sports.append("strength")
        if equipment.hotel_gym:
            sports.append("strength_light")  # Bodyweight + cardio machines
        if equipment.resistance_bands:
            sports.append("mobility")

        return sports

    def constrain_sessions(
        self,
        planned_sessions: List[Dict],
        vacation: VacationWindow,
        day_number: int = 1,
    ) -> List[Dict]:
        """
        Filter and adapt planned sessions for equipment and environment constraints.

        day_number: which day of the vacation (for altitude acclimatisation)
        """
        available = set(self.get_available_sports(vacation.equipment))
        env = vacation.environment
        adapted = []

        for session in planned_sessions:
            sport = session.get("sport", "")

            # Sport not available → suggest substitute
            if sport not in available:
                sub = self._suggest_substitute(sport, available)
                if sub:
                    session = {**session, "sport": sub, "title": f"[Substitute] {session.get('title', '')}"}
                    session["notes"] = f"Original: {sport}. Substituted due to equipment constraints."
                else:
                    logger.info("Skipping %s session — no substitute available", sport)
                    continue

            # Environmental adjustments
            heat_adj = env.heat_adjustment_pct()
            alt_adj = env.altitude_adjustment_pct(day_number)
            total_adj = heat_adj + alt_adj

            if total_adj > 0:
                session = {**session}
                original_tss = session.get("planned_tss", 0)
                session["planned_tss"] = round(original_tss * (1 - total_adj / 100), 1) if original_tss else None
                adjustments = []
                if heat_adj > 0:
                    adjustments.append(f"heat -{heat_adj:.0f}%")
                if alt_adj > 0:
                    adjustments.append(f"altitude -{alt_adj:.0f}% (day {day_number})")
                session["environmental_note"] = f"Adjusted: {', '.join(adjustments)}"

            adapted.append(session)

        return adapted

    def _suggest_substitute(self, sport: str, available: set) -> Optional[str]:
        """Find the best available substitute for an unavailable sport."""
        substitutes = {
            "swim": ["run", "bike"],           # Cardio substitute
            "bike": ["run", "strength"],        # Leg stimulus substitute
            "strength": ["strength_light", "mobility"],
            "run": ["bike", "swim"],
        }
        for sub in substitutes.get(sport, []):
            if sub in available:
                return sub
        return None

    # -----------------------------------------------------------------------
    # Vacation-type training adjustments
    # -----------------------------------------------------------------------
    def get_vacation_load_multiplier(self, vacation: VacationWindow) -> float:
        """
        Return TSS multiplier for vacation type.
        These are broad targets — the LLM refines within these constraints.
        """
        multipliers = {
            VacationType.ACTIVE_VACATION: 0.60,     # 60% — maintain, don't build
            VacationType.REST_VACATION: 0.20,        # 20% — very light, optional
            VacationType.TRAINING_RETREAT: 1.20,     # 120% — overreach block
            VacationType.WORK_TRAVEL: 0.50,          # 50% — constrained schedule
        }
        return multipliers.get(vacation.vacation_type, 0.60)

    # -----------------------------------------------------------------------
    # Retreat block generation
    # -----------------------------------------------------------------------
    def generate_retreat_block(self, retreat: RetreatConfig) -> Dict[str, Any]:
        """
        Generate a training block structure for a retreat.
        Returns context dict for LLM monthly plan generation.
        """
        start = date.fromisoformat(retreat.start_date)
        end = date.fromisoformat(retreat.end_date)
        duration_days = (end - start).days + 1

        return {
            "block_type": "retreat",
            "name": retreat.name,
            "location": retreat.location,
            "duration_days": duration_days,
            "daily_target_hours": retreat.daily_target_hours,
            "primary_sport_focus": retreat.primary_sport_focus,
            "coaching_on_site": retreat.coaching_on_site,
            "altitude_m": retreat.altitude_m,
            "pre_retreat_taper_days": retreat.pre_retreat_taper_days,
            "post_retreat_recovery_days": retreat.post_retreat_recovery_days,
            "daily_structure": retreat.daily_structure,
            "equipment": retreat.equipment.model_dump(),
            "instructions": (
                f"This is a {duration_days}-day training retreat at {retreat.location}. "
                f"Daily training target: {retreat.daily_target_hours}h. "
                f"Primary focus: {retreat.primary_sport_focus or 'multi-sport'}. "
                f"Structure: {retreat.daily_structure} "
                f"Include {retreat.pre_retreat_taper_days} days of pre-retreat taper "
                f"and {retreat.post_retreat_recovery_days} days of post-retreat recovery."
            ),
        }

    # -----------------------------------------------------------------------
    # Vacation window management
    # -----------------------------------------------------------------------
    def get_active_vacation(self) -> Optional[VacationWindow]:
        """Check if today falls within a scheduled vacation window."""
        if not self._pg:
            return None
        today = date.today().isoformat()
        try:
            rows = self._pg._exec_query(
                "SELECT vacation_json FROM vacation_windows WHERE start_date <= %s AND end_date >= %s",
                (today, today),
            )
            if rows:
                return VacationWindow.model_validate(
                    __import__("json").loads(rows[0][0])
                )
        except Exception as exc:
            logger.warning("Vacation query failed: %s", exc)
        return None

    def save_vacation(self, vacation: VacationWindow) -> None:
        """Save a vacation window to PostgreSQL."""
        if not self._pg:
            return
        self._pg._exec_write(
            """
            INSERT INTO vacation_windows (vacation_id, start_date, end_date, vacation_json)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (vacation_id) DO UPDATE SET
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                vacation_json = EXCLUDED.vacation_json
            """,
            (
                vacation.vacation_id,
                vacation.start_date,
                vacation.end_date,
                vacation.model_dump_json(),
            ),
        )
