# backend/planning/profile_manager.py
"""
ProfileManager — manages the athlete profile in PostgreSQL.

Handles:
  - Load/save athlete profile (physiological + preferences + health context)
  - Medication class → system flag mapping
  - Cycle phase detection from health data sync
  - Profile diff detection for pipeline reconfiguration
"""

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from backend.schemas.athlete_profile import (
    AthleteProfile,
    HealthContext,
    Medication,
    MEDICATION_ADJUSTMENTS,
    ContraceptiveType,
    CyclePhase,
)

logger = logging.getLogger(__name__)


class ProfileManager:
    def __init__(self, postgres_client=None):
        self._pg = postgres_client

    # -----------------------------------------------------------------------
    # Load / save profile
    # -----------------------------------------------------------------------
    def load_profile(self, athlete_id: str = "default") -> AthleteProfile:
        """Load profile from PostgreSQL. Returns default profile if none exists."""
        if not self._pg:
            return AthleteProfile(athlete_id=athlete_id)

        try:
            rows = self._pg._exec_query(
                "SELECT profile_json FROM athlete_profiles WHERE athlete_id = %s",
                (athlete_id,),
            )
            if rows:
                return AthleteProfile.model_validate(json.loads(rows[0][0]))
        except Exception as exc:
            logger.warning("Failed to load profile for %s: %s", athlete_id, exc)

        return AthleteProfile(athlete_id=athlete_id)

    def save_profile(self, profile: AthleteProfile) -> None:
        """Save or update profile in PostgreSQL."""
        if not self._pg:
            logger.warning("No PostgreSQL client — profile not saved")
            return

        profile_json = profile.model_dump_json()
        try:
            self._pg._exec_write(
                """
                INSERT INTO athlete_profiles (athlete_id, profile_json, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (athlete_id) DO UPDATE SET
                    profile_json = EXCLUDED.profile_json,
                    updated_at = NOW()
                """,
                (profile.athlete_id, profile_json),
            )
            logger.info("Profile saved for athlete %s", profile.athlete_id)
        except Exception as exc:
            logger.error("Failed to save profile: %s", exc)
            raise

    # -----------------------------------------------------------------------
    # Medication → system adjustment mapping
    # -----------------------------------------------------------------------
    def get_system_adjustments(self, profile: AthleteProfile) -> List[str]:
        """
        Compute combined system adjustment flags from all active medications.
        These flags modify pipeline behaviour (e.g. disable HR zones for beta blockers).
        """
        adjustments = set()
        for med in profile.health.medications:
            if not med.active:
                continue
            # Use explicit flags first
            for flag in med.system_adjustments:
                adjustments.add(flag)
            # Fall back to class-level defaults
            class_defaults = MEDICATION_ADJUSTMENTS.get(med.medication_class.value, [])
            for flag in class_defaults:
                adjustments.add(flag)
        return sorted(adjustments)

    def annotate_context_for_medications(
        self, profile: AthleteProfile, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Annotate the LLM context with medication-aware flags.
        E.g., if on beta blockers, add a note about HR suppression.
        """
        adjustments = self.get_system_adjustments(profile)
        annotations = []

        if "disable_hr_zones" in adjustments:
            annotations.append(
                "⚠️ Athlete is on beta blockers — HR capped/suppressed. "
                "Use Power and RPE for intensity guidance. Do NOT use HR zones."
            )
        if "annotate_hrv_baseline" in adjustments:
            annotations.append(
                "ℹ️ Athlete is on SSRI/SNRI — HRV baseline may be altered. "
                "Use established personal baseline, not population norms."
            )
        if "shift_to_rpe_power" in adjustments:
            annotations.append(
                "ℹ️ HR-based targets unreliable — default to power (bike) or RPE (run/swim)."
            )

        if annotations:
            context["medication_annotations"] = annotations
            context["active_system_adjustments"] = adjustments

        return context

    # -----------------------------------------------------------------------
    # Cycle phase management
    # -----------------------------------------------------------------------
    def update_cycle_phase(
        self, profile: AthleteProfile, cycle_data: Dict[str, Any]
    ) -> AthleteProfile:
        """
        Update cycle phase from health data sync.
        Disables cycle model if on hormonal contraceptive.
        """
        if not profile.health.cycle_tracking_enabled:
            profile.health.current_cycle_phase = CyclePhase.NOT_TRACKED
            return profile

        # Hormonal contraceptive → disable cycle phase model
        if profile.health.contraceptive_type in (
            ContraceptiveType.COMBINED_PILL,
            ContraceptiveType.IMPLANT,
            ContraceptiveType.HORMONAL_IUD,
        ):
            profile.health.current_cycle_phase = CyclePhase.NOT_TRACKED
            logger.info(
                "Cycle tracking disabled — hormonal contraceptive (%s)",
                profile.health.contraceptive_type.value,
            )
            return profile

        # Update from synced data
        phase_str = cycle_data.get("phase", "unknown")
        try:
            profile.health.current_cycle_phase = CyclePhase(phase_str)
        except ValueError:
            profile.health.current_cycle_phase = CyclePhase.UNKNOWN

        profile.health.cycle_day = cycle_data.get("cycle_day")
        return profile

    def get_cycle_training_notes(self, profile: AthleteProfile) -> Optional[str]:
        """
        Generate cycle-phase-specific training notes for LLM context.
        Returns None if cycle tracking is disabled.
        """
        phase = profile.health.current_cycle_phase
        if phase in (CyclePhase.NOT_TRACKED, CyclePhase.UNKNOWN):
            return None

        notes = {
            CyclePhase.MENSTRUAL: (
                "Menstrual phase (days 1-5): Possible fatigue, cramping. "
                "Reduce high-intensity volume if symptomatic. Iron-rich nutrition."
            ),
            CyclePhase.FOLLICULAR: (
                "Follicular phase (days 6-13): Rising estrogen — favourable for "
                "high-intensity work, strength gains, and neuromuscular training."
            ),
            CyclePhase.OVULATION: (
                "Ovulation (~day 14): Peak strength and power potential. "
                "Good window for FTP/CSS testing or race-pace work. "
                "Note: slightly elevated injury risk (ligament laxity)."
            ),
            CyclePhase.EARLY_LUTEAL: (
                "Early luteal phase (days 15-21): Rising progesterone increases "
                "core temperature and ventilation. May feel harder at same intensity. "
                "Higher carb needs. Endurance work is fine, high-intensity may feel worse."
            ),
            CyclePhase.LATE_LUTEAL: (
                "Late luteal phase (days 22-28): PMS symptoms possible. "
                "Prioritise sleep and recovery. Reduce volume if needed. "
                "This is a natural recovery/adaptation window — don't fight it."
            ),
        }
        return notes.get(phase)

    # -----------------------------------------------------------------------
    # Profile diff — detect changes that require pipeline reconfig
    # -----------------------------------------------------------------------
    def detect_significant_changes(
        self, old: AthleteProfile, new: AthleteProfile
    ) -> List[str]:
        """
        Detect profile changes that require pipeline reconfiguration.
        E.g. FTP change → recalculate all power-based targets.
        """
        changes = []
        if old.ftp != new.ftp:
            changes.append(f"FTP changed: {old.ftp}W → {new.ftp}W")
        if old.css != new.css:
            changes.append(f"CSS changed: {old.css} → {new.css}")
        if old.lthr_run != new.lthr_run:
            changes.append(f"LTHR (run) changed: {old.lthr_run} → {new.lthr_run}")
        if old.lthr_bike != new.lthr_bike:
            changes.append(f"LTHR (bike) changed: {old.lthr_bike} → {new.lthr_bike}")
        if old.weight_kg != new.weight_kg:
            changes.append(f"Weight changed: {old.weight_kg}kg → {new.weight_kg}kg")

        # Medication changes
        old_meds = {m.name for m in old.health.medications if m.active}
        new_meds = {m.name for m in new.health.medications if m.active}
        added = new_meds - old_meds
        removed = old_meds - new_meds
        if added:
            changes.append(f"Medications added: {', '.join(added)}")
        if removed:
            changes.append(f"Medications removed: {', '.join(removed)}")

        return changes
