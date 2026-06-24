#!/usr/bin/env python3
"""
Discovers upcoming UCI XCO competitions not yet tracked in races.yml.

The UCI calendar API gives competition metadata (name, dates, venue, country,
competition ID) but not the actual start-list registration URL — that lives on
a third-party site chosen by each organizer, which UCI's API doesn't expose.
So unlike sync_races.py (whose source links directly to start lists), this
script can't fully populate races.yml on its own. Instead it appends
commented-out stub entries — with everything UCI does know already filled
in — for a human to finish by finding the real start-list URL and
uncommenting.

Scope is controlled by the `discovery_countries:` list in races.yml.

Run manually: python scripts/discover_races.py
"""

import os
import re
import sys
import json
import time
from datetime import datetime, timezone

import requests
import yaml
from bs4 import BeautifulSoup
from thefuzz import fuzz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtb_analyzer.config import HEADERS, console
from mtb_analyzer.ranking import (_get_uci_competition_catalog, _parse_comp_end_date,
                                   _strip_diacritics)

REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACES_FILE = os.path.join(REPO_ROOT, "races.yml")

COUNTRY_TO_IOC = {
    "czech republic": "CZE",
    "slovakia":        "SVK",
    "austria":         "AUT",
    "hungary":         "HUN",
    "switzerland":     "SUI",
}

CATEGORIES = [
    {"category": "Men Elite",     "uci_category": "ME"},
    {"category": "Men Juniors",   "uci_category": "MJ"},
    {"category": "Women Elite",   "uci_category": "WE"},
    {"category": "Women Juniors", "uci_category": "WJ"},
]

FUZZY_MATCH_THRESHOLD = 70


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _strip_diacritics(text).lower()).strip("-")


def _get_organizer_website(comp_id: str, year: int) -> str:
    """Best-effort: fetch the UCI competition detail page for the organizer's
    website link, to speed up the manual "find the real start list" step."""
    try:
        r = requests.get(
            f"https://www.uci.org/competition-details/{year}/MTB/{comp_id}",
            headers={**HEADERS, "Accept": "text/html"},
            timeout=15,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        el = soup.find(attrs={"data-component": "CompetitionDetailsModule"})
        if not el:
            return ""
        props = json.loads(el["data-props"])
        website = props.get("competitionDetails", {}).get("website", {}).get("url", "")
        time.sleep(0.3)
        return website
    except Exception:
        return ""


def load_races_yml_raw() -> tuple[dict, str]:
    with open(RACES_FILE, encoding="utf-8") as f:
        raw = f.read()
    return yaml.safe_load(raw) or {}, raw


def _is_tracked(comp_id: str, comp_name: str, tracked_ids: set, tracked_names: list,
                 raw_text: str) -> bool:
    if comp_id in tracked_ids:
        return True
    # Already appended (but not yet uncommented) by a previous discovery run?
    if f"uci_competition_id: {comp_id}" in raw_text:
        return True
    key = _strip_diacritics(comp_name).lower()
    return any(fuzz.partial_ratio(key, name) >= FUZZY_MATCH_THRESHOLD for name in tracked_names)


def discover_candidates(countries: list, existing: list, raw_text: str) -> list:
    country_codes = {COUNTRY_TO_IOC.get(c.strip().lower(), c.strip()) for c in countries}
    tracked_ids   = {str(e["uci_competition_id"]) for e in existing if e.get("uci_competition_id")}
    tracked_names = [_strip_diacritics(e.get("name", "")).lower() for e in existing]

    now = datetime.now()
    candidates = []
    seen_ids: set = set()
    for year in sorted({now.year, now.year + 1}):
        catalog = _get_uci_competition_catalog(year)
        for comp_id, entry in catalog.get("by_id", {}).items():
            if comp_id in seen_ids or entry.get("country") not in country_codes:
                continue
            end_dt = _parse_comp_end_date(entry.get("dates", ""))
            if end_dt is None or end_dt < now:
                continue
            if _is_tracked(comp_id, entry["name"], tracked_ids, tracked_names, raw_text):
                continue
            seen_ids.add(comp_id)
            candidates.append({"comp_id": comp_id, "year": year, **entry})

    return sorted(candidates, key=lambda c: _parse_comp_end_date(c["dates"]) or now)


def build_stub_block(candidate: dict) -> str:
    end_dt   = _parse_comp_end_date(candidate["dates"])
    date_str = end_dt.strftime("%Y-%m-%d") if end_dt else ""
    website  = _get_organizer_website(candidate["comp_id"], candidate["year"])
    slug     = _slugify(candidate["name"])
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [f"# --- Discovered {today} — fill in url: and uncomment to activate ---"]
    if website:
        lines.append(f"# organizer site: {website}")
    for cat in CATEGORIES:
        output = f"{slug}-{cat['uci_category'].lower()}.html"
        lines += [
            '# - url: ""  # TODO: find start list URL',
            f"#   name: {candidate['name']} {candidate['year']} — {cat['category']}",
            f"#   date: '{date_str}'",
            f"#   category: {cat['category']}",
            f"#   uci_category: {cat['uci_category']}",
            f"#   uci_competition_id: {candidate['comp_id']}",
            f"#   output: {output}",
        ]
    return "\n".join(lines) + "\n"


def main() -> None:
    data, raw_text = load_races_yml_raw()
    countries = data.get("discovery_countries", [])
    if not countries:
        console.print("[yellow]No discovery_countries configured in races.yml — nothing to do.[/yellow]")
        return

    existing = data.get("races", []) or []
    console.print(f"[cyan]Scanning UCI XCO calendar for: {', '.join(countries)}...[/cyan]")
    candidates = discover_candidates(countries, existing, raw_text)

    if not candidates:
        console.print("[dim]No new competitions found.[/dim]")
        return

    console.print(f"\nFound {len(candidates)} new competition(s):")
    blocks = []
    for c in candidates:
        console.print(f"  [green]+[/green] {c['name']} ({c['dates']}, {c['venue']}) — id {c['comp_id']}")
        blocks.append(build_stub_block(c))

    with open(RACES_FILE, "a", encoding="utf-8") as f:
        f.write("\n" + "\n".join(blocks))

    console.print(f"\n[bold green]✓ Appended {len(candidates)} stub block(s) to races.yml[/bold green]")
    console.print("[dim]Review each block, find the real start-list URL, then uncomment.[/dim]")


if __name__ == "__main__":
    main()
