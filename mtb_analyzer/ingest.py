"""Scrape every race in races.yml and write the enriched result to Postgres.

Replaces the database half of scripts/generate_site.py. Lives in the package
rather than in scripts/ so the API process can schedule it as a plain import.
"""

import os

import yaml

from .config import console
from .db import bootstrap
from .pipeline import fetch_riders
from .store import save_all

_HERE = os.path.dirname(os.path.abspath(__file__))
RACES_FILE = os.environ.get("RACES_FILE") or os.path.normpath(
    os.path.join(_HERE, "..", "races.yml")
)


def load_races() -> list:
    with open(RACES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f).get("races", [])


def run() -> None:
    races = load_races()
    if not races:
        console.print("[yellow]No races defined in races.yml[/yellow]")
        return

    bootstrap()

    console.print(f"[bold cyan]Processing {len(races)} race(s)...[/bold cyan]")
    uci_caches   = {}
    race_configs = []
    rider_groups = []
    for race in races:
        riders = fetch_riders(race, uci_caches)
        race_configs.append(race)
        rider_groups.append(riders)

    save_all(race_configs, rider_groups)
    total = sum(len(g) for g in rider_groups)
    console.print(
        f"\n[green]✓ Wrote {len(race_configs)} races / {total} entries to Postgres[/green]"
    )
