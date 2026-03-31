# backend/schemas/gear.py
"""
Gear and equipment tracking schemas.

GearAlert        — notification about equipment state
ShoeStatus       — running shoe mileage tracking
BikeComponentLog — chain, cassette, tyre tracking
"""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class GearAlertLevel(str, Enum):
    INFO = "info"             # Advisory in weekly summary
    WARNING = "warning"       # Flag in morning readout
    CRITICAL = "critical"     # UI notification alert


class GearAlert(BaseModel):
    item_id: str
    item_name: str
    equipment_type: str
    alert_level: GearAlertLevel
    current_km: float
    max_km: float
    message: str
    action: str = Field("", description="Suggested action e.g. 'Replace shoes' or 'Check chain stretch'")


# ---------------------------------------------------------------------------
# Shoe mileage thresholds
# ---------------------------------------------------------------------------
SHOE_THRESHOLDS = {
    "healthy":     (0, 400),
    "approaching": (400, 600),
    "replace":     (600, 750),
    "overdue":     (750, float("inf")),
}


def shoe_status(current_km: float) -> str:
    """Determine shoe status from mileage."""
    for status, (low, high) in SHOE_THRESHOLDS.items():
        if low <= current_km < high:
            return status
    return "overdue"


def shoe_alert(item_id: str, name: str, current_km: float, max_km: float = 700.0) -> Optional[GearAlert]:
    """Generate a shoe alert if needed."""
    status = shoe_status(current_km)
    if status == "healthy":
        return None
    levels = {
        "approaching": GearAlertLevel.INFO,
        "replace":     GearAlertLevel.WARNING,
        "overdue":     GearAlertLevel.CRITICAL,
    }
    messages = {
        "approaching": f"{name}: {current_km:.0f}km — approaching replacement window (600-750km)",
        "replace":     f"{name}: {current_km:.0f}km — in replacement window, consider new pair",
        "overdue":     f"{name}: {current_km:.0f}km — overdue for replacement (>{max_km:.0f}km)",
    }
    return GearAlert(
        item_id=item_id,
        item_name=name,
        equipment_type="running_shoe",
        alert_level=levels[status],
        current_km=current_km,
        max_km=max_km,
        message=messages[status],
        action="Replace shoes" if status in ("replace", "overdue") else "Monitor wear",
    )


# ---------------------------------------------------------------------------
# Bike component thresholds
# ---------------------------------------------------------------------------
BIKE_COMPONENT_THRESHOLDS = {
    "chain":         {"warn_km": 2500, "replace_km": 3000, "action": "Check chain stretch with gauge"},
    "cassette":      {"warn_km": 9000, "replace_km": 15000, "action": "Inspect for shark-fin teeth"},
    "tyre_training": {"warn_km": 4000, "replace_km": 5000, "action": "Inspect for flat spots and cuts"},
    "tyre_race":     {"warn_km": 0,    "replace_km": 0,     "action": "Inspect before A-race taper week"},
}


def bike_component_alert(
    item_id: str, name: str, component_type: str, current_km: float
) -> Optional[GearAlert]:
    """Generate a bike component alert if needed."""
    thresholds = BIKE_COMPONENT_THRESHOLDS.get(component_type)
    if not thresholds:
        return None
    warn_km = thresholds["warn_km"]
    replace_km = thresholds["replace_km"]
    if warn_km == 0:
        return None  # Race tyres — manual inspection only
    if current_km < warn_km:
        return None
    if current_km >= replace_km:
        return GearAlert(
            item_id=item_id, item_name=name, equipment_type=component_type,
            alert_level=GearAlertLevel.CRITICAL,
            current_km=current_km, max_km=replace_km,
            message=f"{name}: {current_km:.0f}km — past replacement threshold ({replace_km}km)",
            action=thresholds["action"],
        )
    return GearAlert(
        item_id=item_id, item_name=name, equipment_type=component_type,
        alert_level=GearAlertLevel.WARNING,
        current_km=current_km, max_km=replace_km,
        message=f"{name}: {current_km:.0f}km — approaching limit ({replace_km}km)",
        action=thresholds["action"],
    )
