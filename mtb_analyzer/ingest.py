"""Scrape every race in races.yml and write the enriched result to Postgres.

Replaces the database half of scripts/generate_site.py. Lives in the package
rather than in scripts/ so the API process can schedule it as a plain import.
"""

import os

import yaml

from .config import console
from .db import bootstrap
from .discipline import DEFAULT_DISCIPLINE
from .discipline import get as get_discipline
from .discipline import normalize as normalize_discipline
from .geocode import geocode
from .pipeline import fetch_riders
from .ranking import (build_uci_xco_country_archive, build_uci_xco_history,
                      get_uci_cache, get_uci_xco_race_results_cache,
                      ranking_categories)
from .store import (parse_iso_date, save_all, save_ranked_rider_histories,
                    save_uci_race_results, save_uci_ranking)
from .weather import weather

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


def load_archive_disciplines() -> list:
    """Which disciplines get the multi-year, country-scoped archive sweep.

    Defaults to MTB XCO alone. The sweep is what fills the archive page's
    browsable back-catalogue, and it costs one competition-details request per
    event in every listed country for every year — worth it where there is
    history worth browsing, not something to switch on for a discipline by
    accident.
    """
    with open(RACES_FILE, encoding="utf-8") as f:
        configured = yaml.safe_load(f).get("archive_disciplines", [DEFAULT_DISCIPLINE])
    return [normalize_discipline(d) for d in configured]


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


def _resolve_weather(races: list) -> None:
    """Fill in race-day conditions for every race that has coordinates and has
    already run.

    Must come after _resolve_locations: it reads the lat/lon that one writes
    into the same dicts. Caching is by rounded coordinates and date, so a
    competition's four category rows pay for one lookup — the same arrangement
    geocoding has for venues.

    A race with no coordinates, or one still to come, is skipped silently and
    picked up by a later run; see weather.weather for why a miss is never
    cached.
    """
    for race in races:
        on = parse_iso_date(race.get("date", ""))
        values = weather(race.get("lat"), race.get("lon"), on)
        if not values:
            continue
        for field, value in values.items():
            race[f"weather_{field}"] = value


def _warn_on_course_mismatch(races: list) -> None:
    """Flag competitions whose category rows disagree about the course.

    lap_km and lap_elevation_m describe the circuit, so every category row of
    one competition repeats them — which means a typo in one of four hand-copied
    rows is invisible. Nothing else in the pipeline can catch that, since each
    row is otherwise self-consistent. laps is excluded: it is meant to differ.
    """
    by_comp: dict = {}
    for race in races:
        comp_id = race.get("uci_competition_id")
        if not comp_id:
            continue
        by_comp.setdefault(comp_id, []).append(race)

    for comp_id, group in by_comp.items():
        for field in ("lap_km", "lap_elevation_m"):
            seen = {r.get(field) for r in group if r.get(field) is not None}
            if len(seen) > 1:
                console.print(
                    f"[yellow]  ! Competition {comp_id}: category rows disagree on "
                    f"{field} ({', '.join(str(v) for v in sorted(seen))}) — "
                    f"the circuit is the same for all of them[/yellow]"
                )


def run() -> None:
    races = load_races()
    if not races:
        console.print("[yellow]No races defined in races.yml[/yellow]")
        return

    bootstrap()
    _resolve_locations(races)
    _resolve_weather(races)
    _warn_on_course_mismatch(races)

    console.print(f"[bold cyan]Processing {len(races)} race(s)...[/bold cyan]")
    # Keyed by (discipline, uci_category) — see pipeline.fetch_riders.
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

    # Bring in the full official UCI ranking for each category and fuse it
    # into the same `riders` table save_all just wrote to — so the Riders
    # page can show every officially ranked rider, not just the ones who
    # happen to have appeared on a tracked start list. Must run after
    # save_all() above: the fusion matches against whatever `riders` rows
    # already exist, and this run's own tracked riders need to be among them.
    #
    # Reuses uci_caches from the race loop above where possible — with
    # MTB_RANKING_CACHE_DAYS=0 (set for the scheduled ingest) get_uci_cache()
    # re-downloads on every call, and fetch_riders() already fetched each
    # category races.yml actually uses, so calling it again here would
    # double every ranking download for nothing.
    #
    # Scoped to the disciplines races.yml actually tracks: fetching a
    # cyclo-cross ranking for a purely MTB configuration would be four wasted
    # downloads and a table of riders nothing on the site can reach.
    tracked_disciplines = sorted({
        normalize_discipline(race.get("discipline")) for race in races
    })
    for discipline in tracked_disciplines:
        label = get_discipline(discipline).label
        # MU23/WU23 never have their own ranking, and in cyclo-cross neither do
        # junior women — ranking_categories() has already folded those away, so
        # this is the real list, not four names one of which is a duplicate.
        categories = ranking_categories(discipline)
        console.print(f"[dim]  Saving UCI {label} ranking ({'/'.join(categories)})...[/dim]")
        # Shared across this discipline's categories so a rider the UCI has
        # moved between two of them is written once — see
        # save_ranked_rider_histories.
        seen_riders: set = set()
        for uci_cat in categories:
            cache = (uci_caches.get((discipline, uci_cat))
                     or get_uci_cache(uci_cat, discipline=discipline))
            resolved = save_uci_ranking(
                uci_cat, list(cache.get("by_name", {}).values()), discipline)
            # Give the riders that ranking just fused in the same 12-month
            # history a tracked rider gets, so their profile page is not a
            # rank and an empty table. Memoized per (discipline, ranking
            # category): free for a category some races.yml race already swept,
            # a real sweep for one nothing tracked — which out of season is
            # every cyclo-cross category, since fetch_riders returns before
            # building a history when a start list is not published yet.
            history_db = build_uci_xco_history(uci_cat, discipline=discipline)
            save_ranked_rider_histories(resolved, history_db, discipline, seen_riders)

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
    archive_disciplines = [d for d in load_archive_disciplines() if d in tracked_disciplines]
    if discovery_countries:
        for discipline in archive_disciplines:
            label = get_discipline(discipline).label
            console.print(
                f"[dim]  Broadening UCI {label} archive for "
                f"{', '.join(discovery_countries)}...[/dim]"
            )
            build_uci_xco_country_archive(discovery_countries, discipline=discipline)

    # Persist everything the two steps above cached so the frontend can show
    # complete race results when a user clicks on a race.
    console.print("[dim]  Saving UCI race results...[/dim]")
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
