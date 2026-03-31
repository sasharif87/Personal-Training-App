# backend/orchestration/llm_client.py
"""
Ollama LLM client — three prompt types for the three-tier planning system.

  generate_monthly_plan(context)   — full mesocycle (expensive, run 1×/month)
  generate_weekly_review(context)  — coming week adjustment (run Sunday 3am)
  generate_morning_decision(context) — final primary + alt (run daily 3am)

All return structured dicts that parse into the relevant schema objects.
Forces JSON output mode so responses parse directly without cleanup.

System prompts are defined here alongside each method so they stay co-located
with the context shapes they were designed for.
"""

import json
import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_MONTHLY_SYSTEM_PROMPT = """You are a triathlon and endurance coach with deep knowledge of periodisation.
Generate a full month training plan as structured JSON. Respond ONLY with valid JSON. No preamble, no markdown, no text outside the JSON.

Rules:
- Produce 4 weeks of sessions. 6 training days per week, 1 rest day.
- Week 3 = peak load (highest TSS). Week 4 = recovery (60-70% of week 3 volume).
- For every threshold, VO2max, or race-pace session: include BOTH a primary AND a conditional_alt.
- The conditional_alt is what this session looks like if fatigue signals are elevated that morning.
- The alt must be meaningfully different — not just 10% intensity reduction. Reduce volume, not just intensity.
- Include cross-training (strength, mobility) as real scheduled sessions with structure.
- Load progression must be explicit in rationale fields.
- Every session needs: sport, title, description, rationale, estimated_tss, steps[].
- Every step needs: type, duration_sec or distance_m, target_value (FTP fraction or CSS fraction or HR fraction of LTHR), target_type (power|pace|hr), repeat, description."""

_WEEKLY_SYSTEM_PROMPT = """You are a triathlon coach reviewing a week of training before it begins.
Respond ONLY with valid JSON. Return the full revised week with a changes_rationale field.
If no changes are needed, return the week unchanged with changes_rationale: "No adjustments needed."
Preserve conditional_alt sessions from the monthly plan — do not remove them.
Only modify session targets, day ordering, or volume — do not change sports or add entirely new session types unless explicitly warranted by execution data."""

_MORNING_SYSTEM_PROMPT = """You are a triathlon coach reviewing today's planned session against overnight biometrics.
Respond ONLY with valid JSON.

Tasks:
1. Assess the signal conflict level: clear | mild | significant | high
2. Write final versions of both primary and alt (refine, do not regenerate from scratch)
3. Write a one-line signal_summary explaining what you saw and why (or why not) you recommend the alt
4. If HRV is missing, present the primary with an optional HR ceiling as a conservative guardrail

Output format:
{
  "conflict_level": "clear|mild|significant|high",
  "signal_summary": "one line for morning readout",
  "primary": { same Session schema },
  "alt": { same Session schema, or null if no alt warranted },
  "recommendation": "primary|alt|athlete_call"
}"""


# ---------------------------------------------------------------------------
# OllamaClient
# ---------------------------------------------------------------------------
class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.1:70b",
        timeout: int = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    # -----------------------------------------------------------------------
    # Monthly generation — full mesocycle
    # -----------------------------------------------------------------------
    def generate_monthly_plan(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a full 4-week training plan.
        Context shape: build_monthly_generation_context() output.
        Returns: MonthPlan-compatible dict.
        """
        prompt = f"{_MONTHLY_SYSTEM_PROMPT}\n\nContext:\n{json.dumps(context, indent=2)}"
        return self._call(prompt, stream=False)

    # -----------------------------------------------------------------------
    # Weekly review — adjust coming week
    # -----------------------------------------------------------------------
    def generate_weekly_review(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Review and adjust the coming week based on prior week execution.
        Context shape: build_weekly_review_context() output.
        Returns: WeekPlan-compatible dict with changes_rationale.
        """
        prompt = f"{_WEEKLY_SYSTEM_PROMPT}\n\nContext:\n{json.dumps(context, indent=2)}"
        return self._call(prompt, stream=False)

    # -----------------------------------------------------------------------
    # Morning decision — finalise primary + alt
    # -----------------------------------------------------------------------
    def generate_morning_decision(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Finalise today's primary and alt sessions against overnight biometrics.
        Context shape: build_morning_decision_context() output.
        Returns: {conflict_level, signal_summary, primary, alt, recommendation}
        """
        prompt = f"{_MORNING_SYSTEM_PROMPT}\n\nContext:\n{json.dumps(context, indent=2)}"
        return self._call(prompt, stream=False)

    # -----------------------------------------------------------------------
    # Legacy: single workout plan (kept for existing tests/pipeline)
    # -----------------------------------------------------------------------
    def generate_workout_plan(self, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"""You are a triathlon coach. Generate a structured week of workouts.
Context: {json.dumps(context)}
Return JSON only matching the WeekPlan schema."""
        return self._call(prompt, stream=False)

    # -----------------------------------------------------------------------
    # Core HTTP call
    # -----------------------------------------------------------------------
    def _call(self, prompt: str, stream: bool = False) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "format": "json",
            "stream": stream,
        }
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Ollama request failed: %s", exc)
            raise

        raw = response.json().get("response", "{}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse Ollama response as JSON: %s\nRaw: %s", exc, raw[:500])
            raise


# ---------------------------------------------------------------------------
# Context builders — one per prompt tier
# ---------------------------------------------------------------------------

def build_monthly_generation_context(
    athlete_state: Dict,
    block: Dict,
    race_calendar: list,
    prior_month_summary: Optional[Dict] = None,
    retrieved_history: Optional[list] = None,
) -> Dict[str, Any]:
    return {
        "prompt_type": "monthly_generation",
        "athlete": athlete_state,
        "block": block,
        "race_calendar": race_calendar,
        "prior_month_summary": prior_month_summary or {},
        "retrieved_history": retrieved_history or [],
    }


def build_weekly_review_context(
    coming_week: Dict,
    prior_week_execution: Dict,
    fitness_state: Dict,
) -> Dict[str, Any]:
    return {
        "prompt_type": "weekly_review",
        "coming_week": coming_week,
        "prior_week_execution": prior_week_execution,
        "current_state": fitness_state,
        "instruction": (
            "Review the coming week sessions against prior week execution. "
            "Adjust targets, reorder days, or modify volumes if fatigue drifted from model. "
            "Do NOT regenerate the full month. Return only the revised week with changes_rationale."
        ),
    }


def build_morning_decision_context(
    today_session: Dict,
    biometrics: Dict,
    yesterday_execution: Optional[Dict],
    conflict_assessment: Optional[Dict] = None,
) -> Dict[str, Any]:
    hrv_today = biometrics.get("hrv_this_morning")
    hrv_baseline = biometrics.get("hrv_7d_avg")
    hrv_pct = None
    if hrv_today and hrv_baseline and hrv_baseline > 0:
        hrv_pct = round(((hrv_today - hrv_baseline) / hrv_baseline) * 100, 1)

    return {
        "prompt_type": "morning_decision",
        "today_planned": today_session,
        "biometrics": {
            **biometrics,
            "hrv_pct_vs_baseline": hrv_pct,
            "hrv_available": hrv_today is not None,
        },
        "yesterday": yesterday_execution or {},
        "conflict_assessment": conflict_assessment or {},
    }
