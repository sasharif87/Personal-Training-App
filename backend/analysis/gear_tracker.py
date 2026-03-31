# backend/analysis/gear_tracker.py
"""
Gear and equipment tracking.

Manages:
  - Running shoe mileage auto-increment from Garmin activities
  - Bike component tracking (chain, cassette, tyres)
  - Status alerts for morning readout and weekly summary
  - Equipment assignment (which shoes for which run type)
"""

import json
import logging
from typing import Any, Dict, List, Optional

from backend.schemas.athlete_profile import EquipmentItem, EquipmentType, EQUIPMENT_LIFESPAN
from backend.schemas.gear import (
    GearAlert,
    shoe_status,
    shoe_alert,
    bike_component_alert,
)

logger = logging.getLogger(__name__)


class GearTracker:
    def __init__(self, postgres_client=None):
        self._pg = postgres_client

    # -----------------------------------------------------------------------
    # Load / save equipment registry
    # -----------------------------------------------------------------------
    def load_equipment(self, athlete_id: str = "default") -> List[EquipmentItem]:
        """Load equipment registry from PostgreSQL."""
        if not self._pg:
            return []
        try:
            rows = self._pg._exec_query(
                "SELECT item_json FROM gear_registry WHERE athlete_id = %s AND active = TRUE",
                (athlete_id,),
            )
            return [EquipmentItem.model_validate(json.loads(r[0])) for r in rows]
        except Exception as exc:
            logger.warning("Failed to load gear registry: %s", exc)
            return []

    def save_equipment(self, athlete_id: str, item: EquipmentItem) -> None:
        """Save or update equipment item in PostgreSQL."""
        if not self._pg:
            return
        try:
            self._pg._exec_write(
                """
                INSERT INTO gear_registry (item_id, athlete_id, equipment_type, item_json, active)
                VALUES (%s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (item_id) DO UPDATE SET
                    item_json = EXCLUDED.item_json,
                    active = EXCLUDED.active
                """,
                (
                    item.item_id, athlete_id, item.equipment_type.value,
                    item.model_dump_json(), item.active,
                ),
            )
        except Exception as exc:
            logger.error("Failed to save equipment: %s", exc)

    # -----------------------------------------------------------------------
    # Auto-increment from Garmin activity
    # -----------------------------------------------------------------------
    def increment_from_activity(
        self,
        athlete_id: str,
        sport: str,
        distance_km: float,
        activity_date: str,
    ) -> List[GearAlert]:
        """
        Auto-increment equipment mileage from a completed activity.
        Returns any alerts triggered by the new mileage.

        Logic:
          run → increment all active running shoes
          bike → increment all active bike components
        """
        equipment = self.load_equipment(athlete_id)
        alerts = []

        for item in equipment:
            if not item.active:
                continue

            # Match sport to equipment type
            should_increment = False
            if sport in ("run", "trail_running") and item.equipment_type == EquipmentType.RUNNING_SHOE:
                should_increment = True
            elif sport == "bike" and item.equipment_type in (
                EquipmentType.CHAIN, EquipmentType.CASSETTE,
                EquipmentType.TYRE_TRAINING, EquipmentType.ROAD_BIKE,
            ):
                should_increment = True

            if should_increment:
                item.current_km += distance_km
                item.last_activity_date = activity_date
                item.status = self._calculate_status(item)
                self.save_equipment(athlete_id, item)

                # Check for alerts
                alert = self._generate_alert(item)
                if alert:
                    alerts.append(alert)

        return alerts

    # -----------------------------------------------------------------------
    # Generate alerts for morning readout / weekly summary
    # -----------------------------------------------------------------------
    def get_all_alerts(self, athlete_id: str = "default") -> List[GearAlert]:
        """Generate alerts for all active equipment."""
        equipment = self.load_equipment(athlete_id)
        alerts = []

        for item in equipment:
            if not item.active:
                continue
            alert = self._generate_alert(item)
            if alert:
                alerts.append(alert)

        return alerts

    def get_morning_readout_alerts(self, athlete_id: str = "default") -> List[str]:
        """Get concise alert strings for the morning readout."""
        alerts = self.get_all_alerts(athlete_id)
        return [
            f"⚠️ {a.message}" if a.alert_level.value != "critical"
            else f"🔴 {a.message}"
            for a in alerts
        ]

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------
    def _calculate_status(self, item: EquipmentItem) -> str:
        """Calculate equipment status from current mileage."""
        max_km = item.max_km or EQUIPMENT_LIFESPAN.get(item.equipment_type.value, 0)
        if max_km == 0:
            return "healthy"

        if item.equipment_type == EquipmentType.RUNNING_SHOE:
            return shoe_status(item.current_km)

        # Generic threshold-based status
        ratio = item.current_km / max_km
        if ratio < 0.75:
            return "healthy"
        if ratio < 0.90:
            return "approaching"
        if ratio < 1.0:
            return "replace"
        return "overdue"

    def _generate_alert(self, item: EquipmentItem) -> Optional[GearAlert]:
        """Generate an alert for an equipment item if needed."""
        max_km = item.max_km or EQUIPMENT_LIFESPAN.get(item.equipment_type.value, 0)

        if item.equipment_type == EquipmentType.RUNNING_SHOE:
            return shoe_alert(item.item_id, item.name, item.current_km, max_km or 700.0)

        if item.equipment_type.value in ("chain", "cassette", "tyre_training"):
            return bike_component_alert(
                item.item_id, item.name, item.equipment_type.value, item.current_km
            )

        return None

    # -----------------------------------------------------------------------
    # Summary for weekly report
    # -----------------------------------------------------------------------
    def weekly_summary(self, athlete_id: str = "default") -> Dict[str, Any]:
        """Generate a weekly gear summary for the weekly report."""
        equipment = self.load_equipment(athlete_id)
        alerts = self.get_all_alerts(athlete_id)

        by_type: Dict[str, List] = {}
        for item in equipment:
            if item.active:
                by_type.setdefault(item.equipment_type.value, []).append({
                    "name": item.name,
                    "current_km": round(item.current_km, 1),
                    "max_km": item.max_km or EQUIPMENT_LIFESPAN.get(item.equipment_type.value, 0),
                    "status": item.status,
                })

        return {
            "equipment_count": len([e for e in equipment if e.active]),
            "by_type": by_type,
            "alerts": [a.model_dump() for a in alerts],
            "needs_attention": len(alerts),
        }
