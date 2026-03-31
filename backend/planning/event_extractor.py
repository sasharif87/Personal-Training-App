# backend/planning/event_extractor.py
"""
URL-based race event extraction and race calendar management.

extract_event_from_url  — fetch page, pass to LLM for structured extraction
classify_and_store      — store event with auto-calculated taper/recovery windows
export_race_calendar_md — regenerate human-readable markdown on every update

Uses the same LLM client (via Ollama) to parse HTML pages into structured
race event objects. The LLM does heavy lifting on unstructured event pages.
"""

import json
import logging
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CALENDAR_MD_PATH = os.environ.get("RACE_CALENDAR_MD", "/data/race_calendar.md")


# ---------------------------------------------------------------------------
# URL extraction — fetch page, LLM extracts structured data
# ---------------------------------------------------------------------------
def extract_event_from_url(url: str, llm_client) -> Dict[str, Any]:
    """
    Fetch race event page and use LLM to extract structured details.
    Handles most race registration sites (Active.com, iCal links, etc.).

    Args:
        url: Race event URL
        llm_client: OllamaClient instance for extraction

    Returns:
        Dict matching RaceEventFull schema structure
    """
    import requests
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError("beautifulsoup4 not installed — add 'beautifulsoup4' to requirements.txt")

    resp = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (AI Coach Event Extractor)"},
        timeout=15,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, "html.parser")

    # Strip non-content elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)[:5000]  # Token budget

    extraction_prompt = f"""Extract race event details from this page. Return JSON only. No preamble.

Required fields:
- name: string
- date: ISO 8601 date string (YYYY-MM-DD)
- location: city, state/country string
- sport: triathlon | running | cycling | multisport | obstacle | other
- format: Olympic | 70.3 | Ironman | marathon | half_marathon | 10k | 5k | gran_fondo | enduro | Triple Bypass | other
- distance_label: human-readable e.g. "Olympic Distance" or "13.1 miles"

Optional fields (include if present on page):
- swim_distance_m: integer
- bike_distance_km: float
- run_distance_km: float
- elevation_gain_m: integer
- registration_deadline: ISO 8601 date string

Page content:
{text}"""

    raw = llm_client.generate_monthly_plan(
        {"prompt_type": "extraction", "prompt": extraction_prompt}
    )

    if isinstance(raw, str):
        raw = json.loads(raw)

    # Enrich with source metadata
    raw["event_id"] = raw.get("event_id") or str(uuid.uuid4())
    raw["source_url"] = url
    raw["extracted_at"] = date.today().isoformat()

    return raw


# ---------------------------------------------------------------------------
# Classification and storage
# ---------------------------------------------------------------------------
def classify_and_store_event(
    event: Dict[str, Any],
    priority: str,
    postgres_client,
) -> Dict[str, Any]:
    """
    Store event with A/B/C priority and auto-computed taper/recovery windows.
    Updates the race calendar markdown after storage.
    """
    from backend.schemas.race_event import get_taper_recovery, RaceEventFull

    event_date_str = event.get("date") or event.get("event_date", "")
    event_format = event.get("format", "Other")
    taper_days, recovery_days = get_taper_recovery(priority, event_format)

    event_date = date.fromisoformat(event_date_str)
    event["priority"] = priority
    event["taper_start"] = (event_date - __import__("datetime").timedelta(days=taper_days)).isoformat()
    event["recovery_end"] = (event_date + __import__("datetime").timedelta(days=recovery_days)).isoformat()

    # Build the Postgres-ready dict
    race_record = {
        "event_id":        event.get("event_id", str(uuid.uuid4())),
        "name":            event.get("name", "Unknown Event"),
        "event_date":      event_date_str,
        "location":        event.get("location", ""),
        "sport":           event.get("sport", "triathlon"),
        "format":          event_format,
        "distance_label":  event.get("distance_label", ""),
        "priority":        priority,
        "swim_distance_m": event.get("swim_distance_m"),
        "bike_distance_km": event.get("bike_distance_km"),
        "run_distance_km": event.get("run_distance_km"),
        "elevation_gain_m": event.get("elevation_gain_m"),
        "taper_start":     event["taper_start"],
        "recovery_end":    event["recovery_end"],
        "source_url":      event.get("source_url", ""),
        "extracted_at":     event.get("extracted_at", date.today().isoformat()),
    }

    postgres_client.upsert_race(race_record)

    # Regenerate markdown
    try:
        all_races = postgres_client.get_upcoming_races()
        export_race_calendar_md(all_races)
    except Exception as exc:
        logger.warning("Failed to regenerate race calendar MD: %s", exc)

    logger.info("Stored race event '%s' (priority=%s) with taper=%dd recovery=%dd",
                race_record["name"], priority, taper_days, recovery_days)
    return race_record


# ---------------------------------------------------------------------------
# Race calendar markdown export
# ---------------------------------------------------------------------------
def export_race_calendar_md(
    races: List[Dict[str, Any]],
    output_path: Optional[str] = None,
) -> str:
    """
    Export current race calendar to Markdown file.
    Regenerated on every event add/update/reclassify.
    """
    output_path = output_path or _CALENDAR_MD_PATH

    priority_emoji = {"A": "🔴 A", "B": "🟡 B", "C": "🟢 C"}

    lines = [
        "# Race Calendar\n",
        f"_Last updated: {date.today().isoformat()}_\n",
        "",
        "| Date | Event | Format | Priority | Taper Starts | Recovery End |",
        "|---|---|---|---|---|---|",
    ]

    for e in races:
        p = priority_emoji.get(str(e.get("priority", "C")), e.get("priority", "?"))
        lines.append(
            f"| {e.get('event_date', '')} | {e.get('name', '')} | {e.get('format', '')} "
            f"| {p} | {e.get('taper_start', '')} | {e.get('recovery_end', '')} |"
        )

    lines.append("\n---\n")

    for e in races:
        lines.append(f"## {e.get('name', 'TBD')} — {e.get('event_date', '')}")
        lines.append(f"- **Location:** {e.get('location', 'TBC')}")
        lines.append(f"- **Format:** {e.get('format', '')} ({e.get('distance_label', '')})")
        lines.append(f"- **Priority:** {e.get('priority', 'C')}")
        if e.get("swim_distance_m"):
            lines.append(f"- **Swim:** {e['swim_distance_m']}m")
        if e.get("bike_distance_km"):
            lines.append(f"- **Bike:** {e['bike_distance_km']}km")
        if e.get("run_distance_km"):
            lines.append(f"- **Run:** {e['run_distance_km']}km")
        if e.get("elevation_gain_m"):
            lines.append(f"- **Elevation:** {e['elevation_gain_m']}m gain")
        lines.append(f"- **Taper window:** {e.get('taper_start', '?')} → {e.get('event_date', '')}")
        lines.append(f"- **Recovery window:** {e.get('event_date', '')} → {e.get('recovery_end', '?')}")
        if e.get("source_url"):
            lines.append(f"- **Source:** [{e['source_url']}]({e['source_url']})")
        lines.append("")

    content = "\n".join(lines)

    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(content, encoding="utf-8")
        logger.info("Race calendar written to %s", output_path)
    except OSError as exc:
        logger.error("Failed to write race calendar: %s", exc)

    return content
