# backend/data_ingestion/weather_service.py
"""
Weather-aware scheduling using Open-Meteo API.

Open-Meteo is free, no API key required, and provides 7-day hourly forecasts.

Rescheduling logic:
  - >32°C: move session early morning or relax pace 5-10%
  - >35°C: substitute indoor session (Zwift, treadmill)
  - Heavy rain: bike → Zwift substitute
  - Wind >40km/h: bike → Zwift or indoor trainer
  - Lightning/storms: no outdoor sessions

Weather data injected into weekly review context (Sunday night)
and morning decision context (daily).
"""

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"


class WeatherService:
    def __init__(self, latitude: float = 39.7392, longitude: float = -104.9903):
        """
        Default: Denver, CO. Override with athlete home location or vacation location.
        """
        self.latitude = latitude
        self.longitude = longitude

    def set_location(self, latitude: float, longitude: float) -> None:
        """Update location (e.g. during vacation/retreat)."""
        self.latitude = latitude
        self.longitude = longitude
        logger.info("Weather location updated to %.4f, %.4f", latitude, longitude)

    # -----------------------------------------------------------------------
    # Fetch — 7-day forecast
    # -----------------------------------------------------------------------
    def get_forecast(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Fetch daily weather forecast from Open-Meteo.
        Returns list of daily summaries.
        """
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "daily": ",".join([
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "windspeed_10m_max",
                "weathercode",
            ]),
            "timezone": "auto",
            "forecast_days": min(days, 16),
        }

        try:
            resp = requests.get(_OPEN_METEO_BASE, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.error("Open-Meteo API request failed: %s", exc)
            return []

        daily = data.get("daily", {})
        dates = daily.get("time", [])
        forecast = []

        for i, d in enumerate(dates):
            forecast.append({
                "date": d,
                "temp_max_c": daily.get("temperature_2m_max", [None])[i],
                "temp_min_c": daily.get("temperature_2m_min", [None])[i],
                "precipitation_mm": daily.get("precipitation_sum", [0])[i],
                "wind_max_kmh": daily.get("windspeed_10m_max", [0])[i],
                "weather_code": daily.get("weathercode", [0])[i],
                "conditions": _weather_code_to_text(daily.get("weathercode", [0])[i]),
            })

        return forecast

    # -----------------------------------------------------------------------
    # Fetch today's conditions
    # -----------------------------------------------------------------------
    def get_today(self) -> Dict[str, Any]:
        """Get today's weather summary."""
        forecast = self.get_forecast(days=1)
        return forecast[0] if forecast else {
            "date": date.today().isoformat(),
            "temp_max_c": None,
            "conditions": "unavailable",
        }

    # -----------------------------------------------------------------------
    # Session adjustment logic
    # -----------------------------------------------------------------------
    def get_session_adjustments(
        self, session: Dict[str, Any], weather: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Given a planned session and weather data, suggest adjustments.

        Returns:
          {
              "adjustments": [...],
              "substitute_indoor": bool,
              "time_recommendation": "early_morning" | None,
              "outdoor_ok": bool
          }
        """
        weather = weather or self.get_today()
        sport = session.get("sport", "")
        adjustments = []
        substitute_indoor = False
        time_rec = None
        outdoor_ok = True

        temp_max = weather.get("temp_max_c")
        wind = weather.get("wind_max_kmh", 0)
        precip = weather.get("precipitation_mm", 0)
        code = weather.get("weather_code", 0)

        # Temperature checks
        if temp_max is not None:
            if temp_max > 35:
                adjustments.append(f"Extreme heat ({temp_max}°C) — substitute indoor session")
                substitute_indoor = True
                outdoor_ok = False
            elif temp_max > 32:
                adjustments.append(f"Hot ({temp_max}°C) — move to early morning, relax pace 5-10%")
                time_rec = "early_morning"
            elif temp_max < -10:
                adjustments.append(f"Extreme cold ({temp_max}°C) — substitute indoor")
                substitute_indoor = True
                outdoor_ok = False

        # Wind checks (mainly affects cycling)
        if sport == "bike" and wind > 40:
            adjustments.append(f"High winds ({wind}km/h) — indoor trainer recommended")
            substitute_indoor = True

        # Precipitation checks
        if sport == "bike" and precip > 5:
            adjustments.append(f"Rain ({precip}mm) — Zwift substitute recommended")
            substitute_indoor = True

        # Storm/lightning (weather codes 95-99)
        if code >= 95:
            adjustments.append("⛈️ Thunderstorm forecast — no outdoor sessions")
            substitute_indoor = True
            outdoor_ok = False

        return {
            "adjustments": adjustments,
            "substitute_indoor": substitute_indoor,
            "time_recommendation": time_rec,
            "outdoor_ok": outdoor_ok,
            "weather_summary": f"{weather.get('conditions', 'N/A')}, "
                              f"{temp_max}°C, wind {wind}km/h, rain {precip}mm",
        }

    # -----------------------------------------------------------------------
    # Weekly forecast for context injection
    # -----------------------------------------------------------------------
    def get_weekly_weather_context(self) -> Dict[str, Any]:
        """
        Generate a week weather summary for the LLM weekly review context.
        Highlights any days that need attention.
        """
        forecast = self.get_forecast(days=7)
        if not forecast:
            return {"available": False, "message": "Weather data unavailable"}

        concern_days = []
        for day in forecast:
            temp = day.get("temp_max_c")
            wind = day.get("wind_max_kmh", 0)
            precip = day.get("precipitation_mm", 0)

            concerns = []
            if temp and temp > 30:
                concerns.append(f"hot ({temp}°C)")
            if temp and temp < -5:
                concerns.append(f"cold ({temp}°C)")
            if wind > 35:
                concerns.append(f"windy ({wind}km/h)")
            if precip > 5:
                concerns.append(f"rain ({precip}mm)")
            if day.get("weather_code", 0) >= 95:
                concerns.append("storms")

            if concerns:
                concern_days.append({
                    "date": day["date"],
                    "concerns": concerns,
                })

        return {
            "available": True,
            "forecast_days": len(forecast),
            "concern_days": concern_days,
            "summary": (
                "No weather concerns this week"
                if not concern_days
                else f"{len(concern_days)} day(s) may need schedule adjustments"
            ),
        }


# ---------------------------------------------------------------------------
# Weather code → text (WMO codes)
# ---------------------------------------------------------------------------
def _weather_code_to_text(code: int) -> str:
    """Convert WMO weather code to human-readable text."""
    codes = {
        0: "Clear sky",
        1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Rime fog",
        51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
        61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
        71: "Light snow", 73: "Moderate snow", 75: "Heavy snow",
        80: "Light showers", 81: "Moderate showers", 82: "Heavy showers",
        85: "Light snow showers", 86: "Heavy snow showers",
        95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm",
    }
    return codes.get(code, f"Code {code}")
