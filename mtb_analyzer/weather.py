"""Race-day conditions for a venue, from the Open-Meteo historical archive.

The sibling of geocode.py, and deliberately shaped like it — but with one rule
inverted, so read this before "fixing" the cache to match.

geocode.py caches a miss forever: a location string that Nominatim cannot
resolve will never resolve, so retrying it every ingest only burns rate limit.
Weather is the opposite. A miss here is always temporary:

  * the race has not happened yet, or happens today — Open-Meteo rejects a
    future start_date outright ("out of allowed range") and returns only
    partial figures for a day still in progress, so a max temperature read at
    10:00 would understate it. Both are skipped without a request;
  * the request failed. One bad minute must not become a permanent blank.

So a miss is never written to the cache, and every ingest retries it until it
resolves. That costs at most one request per unresolved venue-and-date per run
— around thirty, against a limit in the thousands.

Note the disk cache barely helps in CI: the workflow keys actions/cache on a
hash of races.yml, and on an exact key hit the cache is not re-saved, so
weather.json written during a run is discarded. Postgres is the real
persistence layer. Don't optimise around a cache that isn't there.

Data © Open-Meteo (CC-BY 4.0), ERA5 reanalysis. No API key required.
"""

import json
import os
import time
from datetime import date

import requests

from .config import CACHE_DIR, console

CACHE_PATH = os.path.join(CACHE_DIR, "weather.json")
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
# Open-Meteo's defaults are already °C / mm / km/h, so no unit parameters.
_DAILY_FIELDS = (
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
)
# Response field → the key we store, which matches the races column names
# minus their weather_ prefix.
_FIELD_MAP = {
    "temperature_2m_max": "temp_max_c",
    "temperature_2m_min": "temp_min_c",
    "precipitation_sum":  "precip_mm",
    "wind_speed_10m_max": "wind_kmh",
}


def _load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def _cache_key(lat: float, lon: float, on: date) -> str:
    # Three decimals is about 110 m — coarse enough that a competition's four
    # category rows share one entry even if their coordinates ever arrive from
    # different sources, fine enough that two venues never collide.
    return f"{lat:.3f},{lon:.3f}|{on.isoformat()}"


def weather(lat: float, lon: float, on: date) -> dict | None:
    """Conditions for the whole of `on` at this point, or None when they are
    not knowable yet.

    Returns {"temp_max_c", "temp_min_c", "precip_mm", "wind_kmh"}. Only a
    successful lookup is cached — see the module docstring.
    """
    if lat is None or lon is None or on is None:
        return None
    # A future date is a hard error from the API and today is still in
    # progress, so neither is worth a request. Tomorrow's ingest picks it up.
    if on >= date.today():
        return None

    key = _cache_key(lat, lon, on)
    cache = _load_cache()
    if key in cache:
        return cache[key]

    console.print(f"[dim]  Fetching weather for {key}...[/dim]")
    time.sleep(0.2)
    try:
        resp = requests.get(
            ARCHIVE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": on.isoformat(),
                "end_date": on.isoformat(),
                "daily": ",".join(_DAILY_FIELDS),
                "timezone": "auto",
            },
            timeout=15,
        )
        resp.raise_for_status()
        daily = resp.json()["daily"]
        # start_date == end_date, so every array holds exactly one day.
        values = {ours: daily[theirs][0] for theirs, ours in _FIELD_MAP.items()}
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
        console.print(f"[yellow]  ! Weather lookup failed for {key}: {exc}[/yellow]")
        return None

    # A null in any field means the archive has nothing for that day after all;
    # treat it as a miss so a later run tries again rather than storing a hole.
    if any(v is None for v in values.values()):
        console.print(f"[yellow]  ! No weather data yet for {key}[/yellow]")
        return None

    cache[key] = values
    _save_cache(cache)
    return values
