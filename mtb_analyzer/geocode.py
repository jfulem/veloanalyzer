"""Resolve a race's free-text location to coordinates for the home page map.

Uses OpenStreetMap's Nominatim, the only free geocoder that doesn't need an
API key. Its usage policy (max 1 req/s, a real User-Agent, no bulk geocoding)
is fine for this: races.yml has on the order of twenty distinct venues, and
every lookup is cached to disk forever, so in steady state this makes zero
network calls — only a location string that's new or has changed pays for one.
"""

import json
import os
import time

import requests

from .config import CACHE_DIR, console

CACHE_PATH = os.path.join(CACHE_DIR, "geocode.json")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim explicitly asks that requests not be disguised as a browser.
GEOCODE_HEADERS = {"User-Agent": "veloanalyzer/1.0 (+https://www.veloanalyzer.com; josef.fulem@gmail.com)"}


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


def geocode(location: str) -> tuple[float, float] | None:
    """(lat, lon) for a free-text location, or None if it's blank or the
    geocoder found nothing. A None result is cached too, so an unresolvable
    string doesn't retry — and re-hit the rate limit — on every ingest."""
    location = (location or "").strip()
    if not location:
        return None

    cache = _load_cache()
    if location in cache:
        cached = cache[location]
        return (cached[0], cached[1]) if cached else None

    console.print(f"[dim]  Geocoding \"{location}\"...[/dim]")
    time.sleep(1)  # Nominatim usage policy: max one request per second.
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": location, "format": "json", "limit": 1},
            headers=GEOCODE_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
    except (requests.RequestException, ValueError) as exc:
        console.print(f"[yellow]  ! Geocoding failed for \"{location}\": {exc}[/yellow]")
        return None

    coords = (float(results[0]["lat"]), float(results[0]["lon"])) if results else None
    cache[location] = list(coords) if coords else None
    _save_cache(cache)
    if coords is None:
        console.print(f"[yellow]  ! No geocoding match for \"{location}\"[/yellow]")
    return coords
