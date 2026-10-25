"""Burgundy Weather Agent — a San Diego-style weatherman.

Provides forecasts from public weather data (wttr.in, no API key required)
based on a US zip code or a browser-provided latitude/longitude.
"""

from __future__ import annotations

from typing import Any, Dict, List

import requests

from Agents.app import AgentBase


def _safe_get(d: Dict[str, Any], *keys: str, default: str = "") -> str:
    cur: Any = d
    for key in keys:
        if isinstance(cur, dict):
            cur = cur.get(key, default)
        elif isinstance(cur, list) and cur:
            cur = cur[0]
        else:
            return default
    if isinstance(cur, list):
        if not cur:
            return default
        cur = cur[0]
    if isinstance(cur, dict):
        if "value" in cur:
            return str(cur.get("value", default))
        return default
    if cur is None:
        return default
    return str(cur)


def _resolve_location(
    location: str = "",
    zip_code: str = "",
    zipcode: str = "",
    postal_code: str = "",
    latitude: float = 0.0,
    longitude: float = 0.0,
    lat: float = 0.0,
    lon: float = 0.0,
) -> str:
    zip_code = (zip_code or zipcode or postal_code or "").strip()
    latitude = latitude or lat
    longitude = longitude or lon
    if zip_code:
        return zip_code
    if latitude and longitude:
        return f"{latitude},{longitude}"
    if location and location.strip():
        return location.strip()
    return ""


def _format_forecast(data: Dict[str, Any], units: str = "imperial") -> str:
    use_metric = str(units).lower().startswith("m")
    temp_key = "temp_C" if use_metric else "temp_F"
    feels_key = "FeelsLikeC" if use_metric else "FeelsLikeF"
    wind_key = "windspeedKmph" if use_metric else "windspeedMiles"
    deg = "°C" if use_metric else "°F"
    wind_unit = "km/h" if use_metric else "mph"

    current = (data.get("current_condition") or [{}])[0]
    area = (data.get("nearest_area") or [{}])[0]
    place = _safe_get(area, "areaName")
    region = _safe_get(area, "region")
    country = _safe_get(area, "country")
    where = ", ".join(p for p in (place, region, country) if p)

    desc = (_safe_get(current, "weatherDesc") or "n/a").strip()
    temp = current.get(temp_key, "?")
    feels = current.get(feels_key, "?")
    humidity = current.get("humidity", "?")
    wind = current.get(wind_key, "?")
    visibility = current.get("visibility" if use_metric else "visibilityMiles", "?")

    lines = []
    if where:
        lines.append(f"Weather for {where}:")
    lines.append(
        f"Currently: {desc}, {temp}{deg} (feels like {feels}{deg}), "
        f"humidity {humidity}%, wind {wind} {wind_unit}, visibility {visibility}."
    )

    days = data.get("weather") or []
    if days:
        lines.append("Forecast:")
        for day in days[:3]:
            date = day.get("date", "?")
            if use_metric:
                lo, hi = day.get("mintempC", "?"), day.get("maxtempC", "?")
            else:
                lo, hi = day.get("mintempF", "?"), day.get("maxtempF", "?")
            hourly = day.get("hourly") or []
            mid = hourly[len(hourly) // 2] if hourly else {}
            day_desc = (_safe_get(mid, "weatherDesc") if isinstance(mid, dict) else "").strip() or "n/a"
            rain = mid.get("chanceofrain", "?") if isinstance(mid, dict) else "?"
            lines.append(
                f"  {date}: {lo}{deg}–{hi}{deg}, {day_desc or 'n/a'}, "
                f"rain chance {rain}%."
            )

    lines.append("Stay classy, San Diego!")
    return "\n".join(lines)


def _fetch_weather(location: str, units: str = "imperial") -> str:
    if not location:
        return "Please provide a zip code or latitude/longitude (browser location)."

    url = f"https://wttr.in/{location}"
    try:
        resp = requests.get(
            url,
            params={"format": "j1"},
            headers={"User-Agent": "burundy-weather-agent/1.0"},
            timeout=15,
        )
    except requests.RequestException as e:
        return f"Weather data unavailable: {e}"

    if resp.status_code != 200:
        return f"Weather service returned status {resp.status_code}."

    try:
        data = resp.json()
    except ValueError:
        return "Weather service returned invalid data."

    if not isinstance(data, dict) or "current_condition" not in data:
        return "Weather service returned an unexpected response."

    return _format_forecast(data, units=units)


def get_weather_forecast(
    location: str = "",
    zip_code: str = "",
    zipcode: str = "",
    postal_code: str = "",
    latitude: float = 0.0,
    longitude: float = 0.0,
    lat: float = 0.0,
    lon: float = 0.0,
    units: str = "imperial",
) -> str:
    """Fetch a public weather forecast for a zip code or lat/lon location."""
    loc = _resolve_location(
        location=location,
        zip_code=zip_code,
        zipcode=zipcode,
        postal_code=postal_code,
        latitude=latitude,
        longitude=longitude,
        lat=lat,
        lon=lon,
    )
    return _fetch_weather(loc, units=units)


def get_weather(
    location: str = "",
    zip_code: str = "",
    zipcode: str = "",
    postal_code: str = "",
    latitude: float = 0.0,
    longitude: float = 0.0,
    lat: float = 0.0,
    lon: float = 0.0,
    units: str = "imperial",
) -> str:
    """Alias for get_weather_forecast."""
    return get_weather_forecast(
        location=location,
        zip_code=zip_code,
        zipcode=zipcode,
        postal_code=postal_code,
        latitude=latitude,
        longitude=longitude,
        lat=lat,
        lon=lon,
        units=units,
    )


def get_forecast(
    location: str = "",
    zip_code: str = "",
    zipcode: str = "",
    postal_code: str = "",
    latitude: float = 0.0,
    longitude: float = 0.0,
    lat: float = 0.0,
    lon: float = 0.0,
    units: str = "imperial",
) -> str:
    """Alias for get_weather_forecast."""
    return get_weather_forecast(
        location=location,
        zip_code=zip_code,
        zipcode=zipcode,
        postal_code=postal_code,
        latitude=latitude,
        longitude=longitude,
        lat=lat,
        lon=lon,
        units=units,
    )


def get_current_weather(
    location: str = "",
    zip_code: str = "",
    zipcode: str = "",
    postal_code: str = "",
    latitude: float = 0.0,
    longitude: float = 0.0,
    lat: float = 0.0,
    lon: float = 0.0,
    units: str = "imperial",
) -> str:
    """Alias for get_weather_forecast."""
    return get_weather_forecast(
        location=location,
        zip_code=zip_code,
        zipcode=zipcode,
        postal_code=postal_code,
        latitude=latitude,
        longitude=longitude,
        lat=lat,
        lon=lon,
        units=units,
    )


def get_weather_by_zip(zip_code: str = "", units: str = "imperial") -> str:
    """Fetch a public weather forecast for a US zip code."""
    return get_weather_forecast(zip_code=zip_code, units=units)


def get_weather_by_location(latitude: float = 0.0, longitude: float = 0.0, units: str = "imperial") -> str:
    """Fetch a public weather forecast for a browser-provided latitude/longitude."""
    return get_weather_forecast(latitude=latitude, longitude=longitude, units=units)


def get_forecast_by_zip(zip_code: str = "", units: str = "imperial") -> str:
    """Alias for get_weather_by_zip."""
    return get_weather_by_zip(zip_code=zip_code, units=units)


def get_forecast_by_location(latitude: float = 0.0, longitude: float = 0.0, units: str = "imperial") -> str:
    """Alias for get_weather_by_location."""
    return get_weather_by_location(latitude=latitude, longitude=longitude, units=units)


def weather(location: str = "", zip_code: str = "", latitude: float = 0.0, longitude: float = 0.0, units: str = "imperial") -> str:
    """Short alias for get_weather_forecast."""
    return get_weather_forecast(location=location, zip_code=zip_code, latitude=latitude, longitude=longitude, units=units)


def forecast(location: str = "", zip_code: str = "", latitude: float = 0.0, longitude: float = 0.0, units: str = "imperial") -> str:
    """Short alias for get_weather_forecast."""
    return get_weather_forecast(location=location, zip_code=zip_code, latitude=latitude, longitude=longitude, units=units)


class BurgundyAgent(AgentBase):
    name = "Burgundy (Weather Agent)"
    description = "A San Diego-style weatherman providing forecasts from public data by zip code or browser location."
    system_prompt = (
        "You are Ron Burgundy, a charismatic San Diego weatherman. You deliver "
        "forecasts with confidence, charm, and a touch of bravado. Always use the "
        "available weather tools to fetch real public forecast data for the user's "
        "zip code or browser-provided latitude/longitude before answering. Never "
        "invent numbers. Present current conditions and the short-term forecast "
        "clearly, then sign off with: Stay classy [Local City]!"
    )
    model = "qwen2.5"
    tools = [
        get_weather_forecast,
        get_weather,
        get_forecast,
        get_current_weather,
        get_weather_by_zip,
        get_weather_by_location,
        get_forecast_by_zip,
        get_forecast_by_location,
        weather,
        forecast,
    ]


# Convenient aliases for differing import expectations.
BurgundyWeatherAgent = BurgundyAgent
RonBurgundyAgent = BurgundyAgent
RonBurgundyWeatherAgent = BurgundyAgent
SanDiegoWeathermanAgent = BurgundyAgent
SanDiegoWeatherAgent = BurgundyAgent
WeatherAgent = BurgundyAgent
BurgundyWeathermanAgent = BurgundyAgent
Burgundy = BurgundyAgent


if __name__ == "__main__":
    agent = BurgundyAgent()
    print("Burgundy Weather Agent Online. Type 'exit' to quit.")
    messages = [{"role": "system", "content": agent.system_prompt}]
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ("exit", "quit"):
                break
            result = agent.execute(user_input, conversation_history=messages)
            messages.append({"role": "user", "content": user_input})
            messages.append({"role": "assistant", "content": result.content})
            print(f"\nAgent: {result.content}")
        except KeyboardInterrupt:
            break
