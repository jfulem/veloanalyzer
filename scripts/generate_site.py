#!/usr/bin/env python3
"""
Reads races.yml, fetches and enriches rider data, then writes docs/data.db
for the TypeScript SPA frontend to query via sql.js.
"""

import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtb_analyzer.config import console
from mtb_analyzer.export_db import export_db
from mtb_analyzer.parsers import parse_start_list
from mtb_analyzer.ranking import (build_uci_xco_history, enrich_cp_xco_points,
                                   fetch_cp_xco_standings, get_uci_cache, lookup_rider,
                                   supplement_from_uci_competition,
                                   _lookup_rider_history)

REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACES_FILE = os.path.join(REPO_ROOT, "races.yml")
DOCS_DIR   = os.path.join(REPO_ROOT, "docs")


def load_races() -> list:
    with open(RACES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f).get("races", [])


def fetch_riders(race: dict, uci_caches: dict) -> list:
    url          = race["url"]
    category     = race.get("category")
    uci_category = race.get("uci_category", "MJ")

    if uci_category not in uci_caches:
        uci_caches[uci_category] = get_uci_cache(uci_category)
    cache = uci_caches[uci_category]

    console.print(f"\n[cyan]Processing:[/cyan] {race.get('name', url)}")
    riders, _ = parse_start_list(url, category)

    if not riders:
        console.print("[yellow]  No riders found — skipping[/yellow]")
        return []

    console.print(f"[green]  ✓ {len(riders)} riders[/green]")
    console.print("[dim]  Looking up UCI rankings and building race histories...[/dim]")

    history_db = build_uci_xco_history(uci_category)
    for rider in riders:
        lookup_rider(rider, cache)
        rider.race_results = _lookup_rider_history(history_db, rider.first_name, rider.last_name)

    uci_comp_id = race.get("uci_competition_id")
    if uci_comp_id:
        race_year = int(race.get("date", "2026")[:4])
        supplement_from_uci_competition(riders, str(uci_comp_id), race_year, uci_category)

    cp_url = race.get("cp_xco_standings_url")
    if cp_url:
        standings = fetch_cp_xco_standings(cp_url, uci_category)
        enrich_cp_xco_points(riders, standings)

    return riders


def main():
    os.makedirs(DOCS_DIR, exist_ok=True)
    races = load_races()
    if not races:
        console.print("[yellow]No races defined in races.yml[/yellow]")
        return

    console.print(f"[bold cyan]Processing {len(races)} race(s)...[/bold cyan]")
    uci_caches   = {}
    race_configs = []
    rider_groups = []
    for race in races:
        riders = fetch_riders(race, uci_caches)
        race_configs.append(race)
        rider_groups.append(riders)

    db_path = os.path.join(DOCS_DIR, "data.db")
    export_db(race_configs, rider_groups, db_path)
    console.print(f"\n[green]✓ Database written to {db_path}[/green]")
    console.print("\n[bold green]Done.[/bold green]")


if __name__ == "__main__":
    main()
