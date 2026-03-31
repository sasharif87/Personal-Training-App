# backend/analysis/hrv_normaliser.py
"""
HRV device normalisation.

When an athlete switches Garmin devices (e.g. Forerunner 935 → Fenix 7),
raw RMSSD values can shift due to different optical sensors. This creates
false trend signals in the coaching system.

This module:
  1. Maintains per-device baselines (mean, std)
  2. Converts raw RMSSD to Z-scores relative to the device baseline
  3. During overlap periods (wearing both devices), calibrates offset
  4. Normalises all readings to a device-agnostic scale

Architecture doc reference: "HRV data must be Z-score normalised by device
to avoid discontinuities when switching hardware."
"""

import logging
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MIN_READINGS_FOR_BASELINE = 14  # 2 weeks minimum for stable baseline


class HRVNormaliser:
    def __init__(self):
        # device_id → list of (date, rmssd)
        self._device_readings: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        # device_id → {"mean": float, "std": float, "n": int}
        self._device_baselines: Dict[str, Dict[str, float]] = {}

    # -----------------------------------------------------------------------
    # Add a raw reading
    # -----------------------------------------------------------------------
    def add_reading(self, device_id: str, date_str: str, rmssd: float) -> None:
        """Add a raw RMSSD reading tagged with device ID."""
        self._device_readings[device_id].append((date_str, rmssd))
        # Recompute baseline if we have enough data
        readings = [r for _, r in self._device_readings[device_id]]
        if len(readings) >= _MIN_READINGS_FOR_BASELINE:
            mean = sum(readings) / len(readings)
            variance = sum((x - mean) ** 2 for x in readings) / len(readings)
            std = math.sqrt(variance) if variance > 0 else 1.0
            self._device_baselines[device_id] = {
                "mean": round(mean, 2),
                "std": round(std, 2),
                "n": len(readings),
            }

    # -----------------------------------------------------------------------
    # Normalise to Z-score
    # -----------------------------------------------------------------------
    def normalise(self, device_id: str, rmssd: float) -> Optional[float]:
        """
        Convert raw RMSSD to a Z-score relative to device baseline.
        Returns None if insufficient baseline data.

        Z-score interpretation:
          0.0 = exactly at baseline
         -1.0 = 1 std below baseline (mild suppression)
         -2.0 = 2 std below (significant suppression)
         +1.0 = 1 std above (elevated — good recovery)
        """
        baseline = self._device_baselines.get(device_id)
        if not baseline or baseline["std"] == 0:
            return None
        return round((rmssd - baseline["mean"]) / baseline["std"], 3)

    # -----------------------------------------------------------------------
    # Cross-device calibration
    # -----------------------------------------------------------------------
    def calibrate_devices(
        self, device_a: str, device_b: str
    ) -> Optional[Dict[str, float]]:
        """
        Calibrate offset between two devices during an overlap period.
        Both devices must have baseline data.
        Returns offset dict or None if calibration not possible.
        """
        base_a = self._device_baselines.get(device_a)
        base_b = self._device_baselines.get(device_b)
        if not base_a or not base_b:
            return None

        # Find overlapping dates
        dates_a = {d for d, _ in self._device_readings[device_a]}
        dates_b = {d for d, _ in self._device_readings[device_b]}
        overlap_dates = dates_a & dates_b

        if len(overlap_dates) < 5:
            logger.warning(
                "Insufficient overlap between %s and %s (%d days, need 5)",
                device_a, device_b, len(overlap_dates),
            )
            return None

        # Calculate average offset during overlap
        readings_a = {d: r for d, r in self._device_readings[device_a] if d in overlap_dates}
        readings_b = {d: r for d, r in self._device_readings[device_b] if d in overlap_dates}

        offsets = []
        for d in overlap_dates:
            if d in readings_a and d in readings_b:
                offsets.append(readings_a[d] - readings_b[d])

        avg_offset = sum(offsets) / len(offsets)

        calibration = {
            "device_a": device_a,
            "device_b": device_b,
            "offset": round(avg_offset, 2),
            "overlap_days": len(overlap_dates),
            "interpretation": (
                f"{device_a} reads ~{abs(avg_offset):.1f}ms "
                f"{'higher' if avg_offset > 0 else 'lower'} than {device_b}"
            ),
        }
        logger.info("Device calibration: %s", calibration["interpretation"])
        return calibration

    # -----------------------------------------------------------------------
    # Normalise a series (for batch processing historical data)
    # -----------------------------------------------------------------------
    def normalise_series(
        self, readings: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Normalise a series of {date, device_id, rmssd} dicts.
        Adds 'z_score' field to each dict.
        """
        # First pass: build baselines
        for r in readings:
            self.add_reading(r["device_id"], r["date"], r["rmssd"])

        # Second pass: normalise
        for r in readings:
            r["z_score"] = self.normalise(r["device_id"], r["rmssd"])

        return readings

    # -----------------------------------------------------------------------
    # Get baseline info
    # -----------------------------------------------------------------------
    def get_baseline_info(self) -> Dict[str, Dict[str, float]]:
        """Return current baselines per device."""
        return dict(self._device_baselines)
