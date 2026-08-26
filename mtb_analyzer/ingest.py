"""Scrape every race in races.yml and write the enriched result to Postgres.

Replaces the database half of scripts/generate_site.py. Lives in the package
rather than in scripts/ so the API process can schedule it as a plain import.
"""

import os

import yaml

from .config import console
from .db import bootstrap
from .geocode import geocode
from .pipeline import fetch_riders
from .ranking import build_uci_xco_country_archive, get_uci_xco_race_results_cache
from .store import save_all, save_uci_race_results

_HERE = os.path.dirname(os.path.abspath(__file__))
RACES_FILE = os.environ.get("RACES_FILE") or os.path.normpath(
    os.path.join(_HERE, "..", "races.yml")
)


def load_races() -> list:
    with open(RACES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f).get("races", [])


def load_discovery_countries() -> list:
    with open(RACES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f).get("discovery_countries", [])


def _resolve_locations(races: list) -> None:
    """Fill in lat/lon for every race that has a location: but no explicit
    lat:/lon: of its own (races.yml may supply GPS directly when a venue's
    address doesn't geocode cleanly). Geocoding is cached by location string,
    so races sharing a venue (one entry per category) only pay for one lookup."""
    for race in races:
        if race.get("lat") is not None and race.get("lon") is not None:
            continue
        coords = geocode(race.get("location", ""))
        if coords:
            race["lat"], race["lon"] = coords


def run() -> None:
    races = load_races()
    if not races:
        console.print("[yellow]No races defined in races.yml[/yellow]")
        return

    bootstrap()
    _resolve_locations(races)

    console.print(f"[bold cyan]Processing {len(races)} race(s)...[/bold cyan]")
    uci_caches   = {}
    race_configs = []
    rider_groups = []
    failed: list[str] = []
    for race in races:
        name = race.get("name", race.get("url", ""))
        try:
            riders = fetch_riders(race, uci_caches)
        except Exception as exc:  # noqa: BLE001
            # One unreachable timing site must not cost the other 49 races.
            # These are third-party servers that go down without warning; an
            # unhandled timeout here used to abort the whole run before
            # anything was written, so a single flaky host froze the entire
            # site's data.
            #
            # An empty result is safe: save_race keeps whatever is already
            # stored for the race and warns, rather than wiping it.
            console.print(f"[red]  ! {name}: scrape failed — {type(exc).__name__}: {exc}[/red]")
            failed.append(name)
            riders = []
        race_configs.append(race)
        rider_groups.append(riders)

    save_all(race_configs, rider_groups)
    total = sum(len(g) for g in rider_groups)
    console.print(
        f"\n[green]✓ Wrote {len(race_configs)} races / {total} entries to Postgres[/green]"
    )

    # build_uci_xco_history (called inside fetch_riders) already fetched and
    # cached full finisher lists for every UCI XCO event within its rolling
    # 12-month window. Broaden that with a country-scoped, multi-year sweep so
    # the archive page can browse further back than any one rider's history
    # needs — races.yml's own discovery_countries list is reused here as the
    # scope, not just as scouting for new starts lists to track. Must run
    # after every fetch_riders() call above (each one may have called
    # build_uci_xco_history for a category this hasn't touched yet), so it
    # only fills in gaps rather than being overwritten by a later one.
    discovery_countries = load_discovery_countries()
    if discovery_countries:
        console.print(f"[dim]  Broadening UCI XCO archive for {', '.join(discovery_countries)}...[/dim]")
        build_uci_xco_country_archive(discovery_countries)

    # Persist everything the two steps above cached so the frontend can show
    # complete race results when a user clicks on a race.
    console.print("[dim]  Saving UCI XCO race results...[/dim]")
    save_uci_race_results(get_uci_xco_race_results_cache())

    if failed:
        console.print(f"\n[yellow]{len(failed)} of {len(races)} races failed to scrape:[/yellow]")
        for name in failed:
            console.print(f"[yellow]  - {name}[/yellow]")
        # Only a total wipeout is worth failing the job over: that means
        # something systemic (no network, bad credentials), not one site
        # having a bad day. A partial failure still wrote good data, and
        # failing here every time a timing site hiccups would train everyone
        # to ignore a red build.
        if len(failed) == len(races):
            raise RuntimeError("every race failed to scrape — check connectivity")
