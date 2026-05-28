#!/usr/bin/env python3
"""
Fetches the MTB race calendar from cycling.sportsoft.cz/mtb, extracts
upcoming races with their start list URLs, and merges new entries into
races.yml. Existing entries (matched by output filename) are never overwritten.
"""

import os
import re
import sys
import unicodedata
from datetime import datetime

import requests
import yaml
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mtb_analyzer.config import HEADERS, console

CALENDAR_URL = "https://cycling.sportsoft.cz/mtb"
RACES_FILE   = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "races.yml")

CATEGORIES = [
    {"category": "Men Juniors",   "uci_category": "MJ"},
    {"category": "Women Juniors", "uci_category": "WJ"},
    {"category": "Men Elite",     "uci_category": "ME"},
    {"category": "Women Elite",   "uci_category": "WE"},
]


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _parse_end_date(date_str: str) -> str:
    """
    Extract the last date from Czech formats and return YYYY-MM-DD.
    Handles: "31.5.2026", "6.-7.6.2026", "18.-19.7.2026"
    """
    # Find the last occurrence of a date pattern: digits.digits.4digits
    matches = re.findall(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", date_str)
    if not matches:
        return ""
    day, month, year = matches[-1]
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _is_upcoming(date_str: str) -> bool:
    if not date_str:
        return True
    try:
        cutoff = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=20)
        return datetime.now() <= cutoff
    except ValueError:
        return True


def _find_info_section(link_section) -> str:
    """Return text of the preceding sibling top-level section (race name/date block)."""
    el = link_section
    for _ in range(10):
        el = el.parent
        if el.name == "section" and "elementor-top-section" in " ".join(el.get("class", [])):
            break
    prev = el.find_previous_sibling("section")
    return prev.get_text(" ", strip=True) if prev else ""


def fetch_races() -> list[dict]:
    try:
        resp = requests.get(CALENDAR_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        console.print(f"[red]Error fetching calendar: {e}[/red]")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    races = []
    seen_urls: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "registrace.sportsoft.cz" not in href:
            continue
        if "startlist.aspx" not in href and "webstartlist.aspx" not in href:
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)

        info = _find_info_section(a)

        # Info text format: "DD.MM.YYYY - Race Name, CZ - UCI CN REGISTRACE SE..."
        # Must contain a date — skip non-race entries (e.g. depot registration)
        if not re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", info):
            continue

        date = _parse_end_date(info)

        # Extract name: text between first " - " and the ", CZ" country suffix
        name_match = re.search(r"\d[\d.\-]+\s*-\s*(.+?)\s*,\s*[A-Z]{2}\s*-", info)
        name = name_match.group(1).strip() if name_match else ""
        if not name:
            continue

        races.append({"name": name, "date": date, "url": href})
        console.print(f"  [dim]Found:[/dim] {name} ({date}) → {href}")

    return races


def load_races_yml() -> dict:
    with open(RACES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_races_yml(data: dict) -> None:
    with open(RACES_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def main() -> None:
    console.print(f"[cyan]Fetching race calendar from {CALENDAR_URL}...[/cyan]")
    discovered = fetch_races()

    if not discovered:
        console.print("[yellow]No races found on the calendar page.[/yellow]")
        return

    upcoming = [r for r in discovered if _is_upcoming(r["date"])]
    console.print(f"\nFound {len(discovered)} race(s), {len(upcoming)} upcoming.")

    if not upcoming:
        console.print("[dim]No upcoming races to add.[/dim]")
        return

    data = load_races_yml()
    existing: list[dict] = data.get("races", [])
    existing_outputs  = {e["output"]                         for e in existing if "output" in e}
    existing_url_cats = {(e["url"], e.get("category", ""))   for e in existing}

    added = 0
    for race in upcoming:
        year = race["date"][:4] if race["date"] else ""
        for cat in CATEGORIES:
            slug    = _slugify(race["name"])
            output  = f"{slug}-{cat['uci_category'].lower()}.html"

            if output in existing_outputs:
                continue
            if (race["url"], cat["category"]) in existing_url_cats:
                continue  # same race+category already present under a different filename

            entry = {
                "url":          race["url"],
                "name":         f"{race['name']} {year} — {cat['category']}".strip(),
                "date":         race["date"],
                "category":     cat["category"],
                "uci_category": cat["uci_category"],
                "output":       output,
            }
            existing.append(entry)
            existing_outputs.add(output)
            added += 1
            console.print(f"  [green]+[/green] {entry['name']} — {entry['category']}")

    if added == 0:
        console.print("[dim]No new entries to add.[/dim]")
        return

    data["races"] = existing
    save_races_yml(data)
    console.print(f"\n[bold green]✓ Added {added} entr{'y' if added == 1 else 'ies'} to races.yml[/bold green]")


if __name__ == "__main__":
    main()
