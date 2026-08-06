"""Start list fetching and enrichment.

The single enrichment path shared by the scheduled ingest (scripts/ingest.py)
and, from phase 5, on-demand analysis jobs. Extracted verbatim from
scripts/generate_site.py so both callers cannot drift apart.
"""

from datetime import datetime, timezone

from .config import console
from .parsers import parse_start_list
from .ranking import (build_uci_xco_history, compute_points_from_history,
                      enrich_cp_xco_points, enrich_with_race_results,
                      fetch_cp_xco_standings, get_uci_cache, lookup_rider,
                      riders_from_uci_competition,
                      supplement_from_uci_competition,
                      _lookup_rider_history, _strip_diacritics)


def merge_riders(primary: list, extra: list) -> list:
    """Append riders from a second start list, skipping anyone already present
    (matched by diacritic-stripped first+last name)."""
    def key(r):
        return (_strip_diacritics(r.first_name).lower(), _strip_diacritics(r.last_name).lower())

    seen = {key(r) for r in primary}
    merged = list(primary)
    for r in extra:
        k = key(r)
        if k not in seen:
            merged.append(r)
            seen.add(k)
    return merged


def _rebuild_past_race_from_uci(race: dict, uci_category: str) -> list:
    """Fallback for a past race whose start list has gone from its source site.

    Only applies once the race has actually run and a uci_competition_id is
    configured — before that, an empty scrape means the organiser hasn't
    published the list yet, which is normal and must not be papered over.
    """
    uci_comp_id = race.get("uci_competition_id")
    race_date = race.get("date", "")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not uci_comp_id or not race_date or race_date >= today:
        return []

    console.print("[dim]  Start list unavailable — rebuilding from official UCI results...[/dim]")
    riders = riders_from_uci_competition(str(uci_comp_id), int(race_date[:4]), uci_category)
    if riders:
        console.print(f"[green]  ✓ Recovered {len(riders)} finishers from UCI[/green]")
    return riders


def fetch_riders(race: dict, uci_caches: dict) -> list:
    url          = race["url"]
    category     = race.get("category")
    uci_category = race.get("uci_category", "MJ")

    if uci_category not in uci_caches:
        uci_caches[uci_category] = get_uci_cache(uci_category)
    cache = uci_caches[uci_category]

    console.print(f"\n[cyan]Processing:[/cyan] {race.get('name', url)}")
    # A dead/unreachable organiser site must fall through to the UCI-results
    # rebuild below exactly like a start list that loaded but listed nobody —
    # a 404 or timeout is the most common way a site "goes", and is exactly
    # the scenario _rebuild_past_race_from_uci exists for. Left unguarded,
    # the exception would propagate straight past that fallback and only be
    # caught by the per-race handler in ingest.py, which protects the rest of
    # the run but never gives reconstruction a chance to run.
    try:
        riders, _ = parse_start_list(url, category)
    except Exception as exc:
        console.print(f"[yellow]  Start list fetch failed ({type(exc).__name__}) — trying UCI results[/yellow]")
        riders = []

    extra_url = race.get("extra_url")
    if extra_url:
        console.print(f"[dim]  Merging extra start list: {extra_url}[/dim]")
        try:
            extra_riders, _ = parse_start_list(extra_url, category)
            riders = merge_riders(riders, extra_riders)
        except Exception as exc:
            console.print(f"[yellow]  Extra start list fetch failed ({type(exc).__name__}) — skipping it[/yellow]")

    if not riders:
        riders = _rebuild_past_race_from_uci(race, uci_category)

    if not riders:
        console.print("[yellow]  No riders found — skipping[/yellow]")
        return []

    console.print(f"[green]  ✓ {len(riders)} riders[/green]")
    console.print("[dim]  Looking up UCI rankings and building race histories...[/dim]")

    history_db = build_uci_xco_history(uci_category)
    for rider in riders:
        lookup_rider(rider, cache)
        rider.race_results = _lookup_rider_history(history_db, rider.first_name, rider.last_name)
        if rider.uci_rank is None:
            rider.computed_points = compute_points_from_history(rider.race_results, uci_category)
        if not rider.country and rider.race_results:
            rider.country = next(
                (r.get("nationality", "") for r in rider.race_results if r.get("nationality")),
                "",
            )

    uci_comp_id = race.get("uci_competition_id")
    if uci_comp_id:
        race_year = int(race.get("date", "2026")[:4])
        supplement_from_uci_competition(riders, str(uci_comp_id), race_year, uci_category)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if race.get("date", "") < today:
            console.print("[dim]  Race is in the past — fetching official results...[/dim]")
            enrich_with_race_results(riders, str(uci_comp_id), race_year, uci_category)

    cp_url = race.get("cp_xco_standings_url")
    if cp_url:
        standings = fetch_cp_xco_standings(cp_url, uci_category)
        enrich_cp_xco_points(riders, standings)

    return riders
