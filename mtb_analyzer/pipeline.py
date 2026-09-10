"""Start list fetching and enrichment.

The single enrichment path shared by the scheduled ingest (scripts/ingest.py)
and, from phase 5, on-demand analysis jobs. Extracted verbatim from
scripts/generate_site.py so both callers cannot drift apart.
"""

from datetime import datetime, timezone

from .config import console
from .discipline import get as get_discipline
from .discipline import normalize as normalize_discipline
from .parsers import parse_start_list
from .ranking import (build_uci_xco_history, compute_points_from_history,
                      enrich_cup_points, enrich_with_race_results,
                      fetch_first_cup_standings, get_uci_cache, lookup_rider,
                      ranking_category, riders_from_uci_competition,
                      supplement_from_uci_competition, unmatched_finishers,
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


def _has_official_results(race: dict) -> bool:
    """Whether this race's official UCI classification can be read yet.

    Needs a uci_competition_id and a date already past: before the race runs,
    an empty scrape means the organiser hasn't published the start list yet,
    which is normal and must not be papered over with results that don't exist.
    """
    race_date = race.get("date", "")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return bool(race.get("uci_competition_id")) and bool(race_date) and race_date < today


def _rebuild_past_race_from_uci(race: dict, uci_category: str, discipline: str) -> list:
    """Fallback for a past race whose start list has gone from its source site."""
    if not _has_official_results(race):
        return []
    uci_comp_id = race["uci_competition_id"]

    console.print("[dim]  Start list unavailable — rebuilding from official UCI results...[/dim]")
    riders = riders_from_uci_competition(
        str(uci_comp_id), _competition_year(race, discipline), uci_category, discipline)
    if riders:
        console.print(f"[green]  ✓ Recovered {len(riders)} finishers from UCI[/green]")
    return riders


def _competition_year(race: dict, discipline: str) -> int:
    """The UCI's season label for this race's date.

    For MTB that is simply the calendar year the race falls in. A cyclo-cross
    season spans the new year and the UCI files it under the later one, so a
    race on 5 December 2026 belongs to season 2027 — get it wrong and every
    competition lookup misses.
    """
    date_str = race.get("date", "")
    try:
        when = datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        when = datetime.now()
    return get_discipline(discipline).season_year(when)


def _filter_by_birth_year(riders: list, race: dict) -> list:
    """Narrow a start list to the birth years in races.yml `birth_years:`.

    Cyclo-cross does not run a separate junior women's race — juniors, U23 and
    elite women all start together, and the organiser's start list has one
    course for all three. Naming the two junior birth years is the only way to
    pull that category out of the combined list.
    """
    wanted = race.get("birth_years")
    if not wanted:
        return riders
    wanted = {str(y) for y in wanted}
    kept = [r for r in riders if (r.birth_year or "").strip() in wanted]
    dropped = len(riders) - len(kept)
    console.print(
        f"[dim]  Birth-year filter {sorted(wanted)}: kept {len(kept)}, dropped {dropped}[/dim]"
    )
    return kept


def _merge_missing_finishers(riders: list, race: dict, uci_category: str,
                             discipline: str) -> list:
    """Add anyone who finished a past race but was never on its start list.

    A start list is a snapshot taken beforehand; the official classification is
    the record of who actually rode. A rider who entered on the day, or after
    the organiser last republished, appears only in the second — and the page
    then contradicts itself, showing a field whose winner is missing while the
    archive lists her first. That is exactly what happened to Lia Schrievers,
    who won the women's race at ČP XCO NMNM 2026 without ever reaching the
    scraped start list.

    Runs after the birth-year filter, not before it: riders reconstructed from
    UCI results carry no birth year (the results feed publishes none), so the
    filter would drop every one of them. It does not need to — the UCI event
    read here is the one for this exact category, so its finishers are already
    the right riders, and unmatched_finishers refuses to substitute a related
    event for a missing one.

    Only ever additive. A start-list rider the UCI has no result for stays (a
    DNS is still information), and who counts as already present is decided by
    the same matcher that attaches results to the riders we do have, so the
    start list's own spelling, team and UCI ID keep priority.
    """
    if not _has_official_results(race):
        return riders

    finishers = unmatched_finishers(
        riders, str(race["uci_competition_id"]), _competition_year(race, discipline),
        uci_category, discipline)
    if not finishers:
        return riders

    merged = merge_riders(riders, finishers)
    added = len(merged) - len(riders)
    if added:
        console.print(
            f"[green]  + {added} finisher(s) in the official results but not on "
            f"the start list[/green]"
        )
    return merged


def fetch_riders(race: dict, uci_caches: dict) -> list:
    url          = race["url"]
    category     = race.get("category")
    uci_category = race.get("uci_category", "MJ")
    discipline   = normalize_discipline(race.get("discipline"))
    disc         = get_discipline(discipline)

    # Keyed by the *resolved* ranking, not the start-list category: several
    # categories share one ranking (MU23 with ME, and in cyclo-cross WJ with
    # WE), and keying on the raw name would download the same ranking twice
    # and leave ingest.py unable to find what it already has.
    cache_key = (discipline, ranking_category(uci_category, discipline))
    if cache_key not in uci_caches:
        uci_caches[cache_key] = get_uci_cache(uci_category, discipline=discipline)
    cache = uci_caches[cache_key]

    console.print(f"\n[cyan]Processing:[/cyan] {race.get('name', url)} [dim]({disc.label})[/dim]")
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
        riders = _rebuild_past_race_from_uci(race, uci_category, discipline)

    riders = _filter_by_birth_year(riders, race)
    riders = _merge_missing_finishers(riders, race, uci_category, discipline)

    if not riders:
        console.print("[yellow]  No riders found — skipping[/yellow]")
        return []

    console.print(f"[green]  ✓ {len(riders)} riders[/green]")
    console.print("[dim]  Looking up UCI rankings and building race histories...[/dim]")

    history_db = build_uci_xco_history(uci_category, discipline=discipline)
    for rider in riders:
        lookup_rider(rider, cache)
        rider.race_results = _lookup_rider_history(history_db, rider.first_name, rider.last_name)
        rider.computed_points = compute_points_from_history(
            rider.race_results, uci_category, discipline)
        if not rider.country and rider.race_results:
            rider.country = next(
                (r.get("nationality", "") for r in rider.race_results if r.get("nationality")),
                "",
            )

    uci_comp_id = race.get("uci_competition_id")
    if uci_comp_id:
        race_year = _competition_year(race, discipline)
        supplement_from_uci_competition(
            riders, str(uci_comp_id), race_year, uci_category, discipline)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if race.get("date", "") < today:
            console.print("[dim]  Race is in the past — fetching official results...[/dim]")
            enrich_with_race_results(
                riders, str(uci_comp_id), race_year, uci_category, discipline)

    # `cup_standings_url` may be a single URL or a list tried in order: see
    # fetch_first_cup_standings. cp_xco_standings_url is the older name, kept
    # so every MTB entry in races.yml keeps working unchanged.
    cup_urls = race.get("cup_standings_url") or race.get("cp_xco_standings_url")
    if cup_urls:
        standings = fetch_first_cup_standings(cup_urls, uci_category, discipline)
        enrich_cup_points(riders, standings)

    return riders
