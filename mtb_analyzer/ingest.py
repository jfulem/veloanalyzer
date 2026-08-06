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
