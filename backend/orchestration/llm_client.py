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
# OllamaClient — canonical LLM client with dual-host fallback
# ---------------------------------------------------------------------------
class OllamaClient:
    """
    Unified Ollama client with:
      - Dual-host fallback (primary → fallback URL)
      - Automatic reconnect if primary goes down
      - JSON-only output enforcement
      - Configurable temperature per prompt tier
    """

    def __init__(
        self,
        base_url: str = "",
        fallback_url: str = "",
        model: str = "",
        timeout: int = 300,
    ):
        import os
        self.primary_url = (
            base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        ).rstrip("/")
        self.fallback_url = (
            fallback_url or os.environ.get("OLLAMA_FALLBACK_URL", "")
        ).rstrip("/")
        self.model = model or os.environ.get("OLLAMA_MODEL", "llama3.1:70b")
        self.timeout = int(os.environ.get("LLM_TIMEOUT", str(timeout)))
        self._active_url = self._determine_route()

    def _determine_route(self) -> str:
        """Ping primary, fall back to secondary if unreachable."""
        if self._ping(self.primary_url):
            logger.info("Ollama connected: primary [%s]", self.primary_url)
            return self.primary_url
        if self.fallback_url and self._ping(self.fallback_url):
            logger.info("Ollama fallback active [%s]", self.fallback_url)
            return self.fallback_url
        logger.warning("No Ollama instances reachable — LLM calls will fail")
        return self.primary_url

    @staticmethod
    def _ping(url: str) -> bool:
        if not url:
            return False
        try:
            requests.get(f"{url}/api/tags", timeout=3)
            return True
        except Exception:
            return False

    # -----------------------------------------------------------------------
    # Monthly generation — full mesocycle
    # -----------------------------------------------------------------------
    def generate_monthly_plan(self, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"{_MONTHLY_SYSTEM_PROMPT}\n\nContext:\n{json.dumps(context, indent=2)}"
        return self._call(prompt, temperature=0.2)

    # -----------------------------------------------------------------------
    # Weekly review — adjust coming week
    # -----------------------------------------------------------------------
    def generate_weekly_review(self, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"{_WEEKLY_SYSTEM_PROMPT}\n\nContext:\n{json.dumps(context, indent=2)}"
        return self._call(prompt, temperature=0.3)

    # -----------------------------------------------------------------------
    # Morning decision — finalise primary + alt
    # -----------------------------------------------------------------------
    def generate_morning_decision(self, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"{_MORNING_SYSTEM_PROMPT}\n\nContext:\n{json.dumps(context, indent=2)}"
        return self._call(prompt, temperature=0.4)

    # -----------------------------------------------------------------------
    # Legacy: single workout plan (kept for existing tests/pipeline)
    # -----------------------------------------------------------------------
    def generate_workout_plan(self, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"""You are a triathlon coach. Generate a structured week of workouts.
Context: {json.dumps(context)}
Return JSON only matching the WeekPlan schema."""
        return self._call(prompt)

    # -----------------------------------------------------------------------
    # Generic JSON generation (replaces CoachingLLMClient.generate_json)
    # -----------------------------------------------------------------------
    def generate_json(self, prompt: str, temperature: float = 0.3) -> Dict[str, Any]:
        """Generic JSON prompt — for event extraction, free-form queries, etc."""
        return self._call(prompt, temperature=temperature)

    # -----------------------------------------------------------------------
    # Core HTTP call with automatic fallback
    # -----------------------------------------------------------------------
    def _call(
        self, prompt: str, stream: bool = False, temperature: float = 0.3
    ) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "format": "json",
            "stream": stream,
            "options": {"temperature": temperature},
        }

        # Try active URL first
        try:
            return self._send(self._active_url, payload)
        except Exception as exc:
            logger.error(
                "Ollama request to %s failed: %s", self._active_url, exc
            )

        # Failover to the other URL
        other_url = (
            self.fallback_url
            if self._active_url == self.primary_url
            else self.primary_url
        )
        if other_url and self._ping(other_url):
            logger.info("Switching Ollama route to %s", other_url)
            self._active_url = other_url
            try:
                return self._send(self._active_url, payload)
            except Exception as exc2:
                logger.error("Fallback also failed: %s", exc2)
                raise RuntimeError("All Ollama routes failed") from exc2

        raise RuntimeError(
            f"Ollama generation failed at {self._active_url} and no fallback available"
        )

    def _send(self, url: str, payload: dict) -> Dict[str, Any]:
        """HTTP POST → parse JSON response."""
        response = requests.post(
            f"{url}/api/generate",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()

        raw = response.json().get("response", "{}")
        # Safety: strip markdown fences if model hallucinates them
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.lstrip("`").removeprefix("json").strip().rstrip("`").strip()
        if not clean:
            return {}
        try:
            return json.loads(clean)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse Ollama response as JSON: %s\nRaw: %s",
                exc, raw[:500],
            )
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
    weather: Optional[Dict] = None,
) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
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
    if weather:
        ctx["weather"] = weather
    return ctx


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
