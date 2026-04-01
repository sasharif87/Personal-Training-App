# backend/planning/llm_prompts.py
"""
Repository of system prompts and JSON schemas used to orchestrate the
monthly, weekly, and daily LLM decision loops via Ollama.
"""

MONTHLY_SYSTEM_PROMPT = """
You are a triathlon and endurance coach. Generate a full month training plan.
Respond ONLY with valid JSON. No preamble, no markdown, no explanation outside the JSON.

Rules:
- Produce 4 weeks of sessions, 6 training days per week plus 1 rest day
- Week 3 should be peak load week; Week 4 should be recovery (60-70% of week 3 volume)
- For any threshold, VO2max, or race-pace session: include both a primary and a conditional_alt
- conditional_alt is what this session looks like if fatigue signals are elevated that morning
- The alt must be meaningfully different — not just 10% intensity reduction
- Include cross-training (strength, mobility) as scheduled sessions, not afterthoughts
- Load progression must be explicit in the rationale

Output format must exactly match the provided schema.
"""

MONTHLY_OUTPUT_SCHEMA = {
    "month_rationale": "Why this load arc for this block phase and athlete state",
    "block_phase": "build",
    "weeks": [
        {
            "week_number": 1,
            "week_rationale": "Establish load baseline for this block",
            "target_tss": 420,
            "days": [
                {
                    "day": "Monday",
                    "date": "YYYY-MM-DD",
                    "primary": {
                        "sport": "swim",
                        "title": "CSS Threshold Set",
                        "duration_min": 60,
                        "planned_tss": 65,
                        "planned_if": 0.85,
                        "structure": {
                            "warmup": {"duration_min": 10, "target": "easy"},
                            "main_sets": [
                                {
                                    "repeat": 8,
                                    "distance_m": 100,
                                    "target": "CSS pace",
                                    "rest_sec": 15,
                                    "description": "Hold CSS — no faster"
                                }
                            ],
                            "cooldown": {"duration_min": 10}
                        },
                        "session_notes": "Focus on stroke rate consistency across all 8 reps",
                        "alt_trigger": "HRV suppressed OR sleep < 0.65 OR body battery < 50"
                    },
                    "conditional_alt": {
                        "title": "CSS Threshold Set — Reduced Volume",
                        "duration_min": 45,
                        "planned_tss": 42,
                        "planned_if": 0.78,
                        "structure": {
                            "warmup": {"duration_min": 10, "target": "easy"},
                            "main_sets": [
                                {
                                    "repeat": 5,
                                    "distance_m": 100,
                                    "target": "CSS pace or slightly slower",
                                    "rest_sec": 20
                                }
                            ],
                            "cooldown": {"duration_min": 10}
                        },
                        "session_notes": "Same quality, less quantity. If still feeling off after warmup, stop at 3 reps and call it.",
                        "alt_rationale": "Preserves swim stimulus with reduced volume demand. Still threshold work, not junk miles."
                    }
                }
            ]
        }
    ]
}

WEEKLY_REVIEW_SYSTEM_PROMPT = """
You are a triathlon coach reviewing a week of training before it begins.
Respond ONLY with valid JSON. Return the full revised week with a changes_rationale field.
If no changes are needed, return the week unchanged with changes_rationale: "No adjustments needed."
Preserve conditional_alt sessions from the monthly plan — do not remove them.
"""

EVENT_EXTRACTION_PROMPT = """
Extract race event details from this page. Return JSON only. No preamble.

Required fields:
- name: string
- date: ISO 8601 date string (YYYY-MM-DD)
- location: city, state/country string
- sport: triathlon | running | cycling | multisport | obstacle
- format: Olympic | 70.3 | Ironman | marathon | half_marathon | 10k | 5k | gran_fondo | enduro | other
- distance_label: human readable e.g. "Olympic Distance" or "13.1 miles"

Optional fields (include if present):
- swim_distance_m: integer
- bike_distance_km: float
- run_distance_km: float
- elevation_gain_m: integer
- registration_deadline: ISO 8601 date string
- event_url: the source URL
"""
