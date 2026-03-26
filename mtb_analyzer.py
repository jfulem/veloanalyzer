#!/usr/bin/env python3
"""
MTB Start List Analyzer
=======================
Fetches a race start list, enriches it with UCI ranking data and displays an overview.
Can also compare two races based on the quality of registered riders.

Usage:
  python mtb_analyzer.py --url "https://..." --category "Men Juniors"
  python mtb_analyzer.py --compare "https://race1..." "https://race2..."
  python mtb_analyzer.py --url "https://..." --category "Junior" --export results.html
  python mtb_analyzer.py --refresh-cache --uci-category MJ

UCI categories (--uci-category):
  MJ = Men Juniors   WJ = Women Juniors
  ME = Men Elite     WE = Women Elite

Export formats:
  --export results.html   → rich HTML report (auto-detected by extension)
  --export results.csv    → CSV spreadsheet
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, NavigableString
from thefuzz import fuzz, process
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

# ─────────────────────────── configuration ────────────────────────────────
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".mtb_cache")
CACHE_MAX_AGE_DAYS = 7
XCODATA_RANKING_BASE = "https://www.xcodata.com/rankings/{cat}/2026/2026-03-24/{page}/?country="
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

FLAG = {
    "AUT": "🇦🇹", "CZE": "🇨🇿", "SVK": "🇸🇰", "HUN": "🇭🇺",
    "ITA": "🇮🇹", "POL": "🇵🇱", "BEL": "🇧🇪", "GER": "🇩🇪",
    "IRL": "🇮🇪", "FRA": "🇫🇷", "SUI": "🇨🇭", "NED": "🇳🇱",
    "GBR": "🇬🇧", "ESP": "🇪🇸", "SWE": "🇸🇪", "NOR": "🇳🇴",
    "DEN": "🇩🇰", "USA": "🇺🇸", "CAN": "🇨🇦", "SLO": "🇸🇮",
    "CRO": "🇭🇷", "ROM": "🇷🇴", "POR": "🇵🇹", "AUS": "🇦🇺",
    "NZL": "🇳🇿", "RSA": "🇿🇦", "JPN": "🇯🇵", "BRA": "🇧🇷",
    "ARG": "🇦🇷", "COL": "🇨🇴", "CHI": "🇨🇱", "SRB": "🇷🇸",
    "BUL": "🇧🇬", "GRE": "🇬🇷", "ISR": "🇮🇱", "LUX": "🇱🇺",
    "MEX": "🇲🇽", "URU": "🇺🇾", "TUR": "🇹🇷", "UKR": "🇺🇦",
}

COUNTRY_NORMALIZE = {
    "österreich - austria": "AUT", "austria": "AUT", "österreich": "AUT",
    "czech republic": "CZE", "czechia": "CZE",
    "slovakia": "SVK", "slovensko": "SVK",
    "hungary": "HUN", "maďarsko": "HUN",
    "italy": "ITA", "itálie": "ITA",
    "poland": "POL", "polsko": "POL",
    "belgium": "BEL", "belgie": "BEL",
    "germany": "GER", "německo": "GER",
    "ireland": "IRL", "irsko": "IRL",
    "france": "FRA", "frankreich": "FRA",
    "switzerland": "SUI", "schweiz": "SUI",
    "netherlands": "NED", "holland": "NED",
    "great britain": "GBR", "united kingdom": "GBR",
    "spain": "ESP", "španělsko": "ESP",
    "sweden": "SWE", "dänemark": "DEN", "denmark": "DEN",
    "norway": "NOR", "norwegen": "NOR",
    "united states of america": "USA", "usa": "USA",
    "canada": "CAN",
    "slovenia": "SLO", "slovinsko": "SLO",
    "croatia": "CRO",
    "romania": "ROM",
    "portugal": "POR",
    "australia": "AUS",
    "new zealand": "NZL",
    "south africa": "RSA",
    "japan": "JPN",
    "brazil": "BRA",
    "argentina": "ARG",
    "colombia": "COL",
    "chile": "CHI",
    "serbia": "SRB",
    "bulgaria": "BUL",
    "greece": "GRE",
    "israel": "ISR",
    "luxembourg": "LUX",
    "mexico": "MEX",
    "turkey": "TUR",
    "ukraine": "UKR",
}


# ─────────────────────────── data classes ─────────────────────────────────
@dataclass
class Rider:
    first_name: str
    last_name: str
    country: str = ""
    uci_id: str = ""
    team: str = ""
    category: str = ""
    birth_year: str = ""
    start_nr: str = ""
    uci_rank: Optional[int] = None
    uci_points: Optional[int] = None
    match_confidence: int = 100  # 100 = matched via UCI ID, <100 = fuzzy name match %

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def flag(self):
        return FLAG.get(self.country, "  ")


# ─────────────────────────── category filter ──────────────────────────────
def category_matches(category_text: str, filter_str: str) -> bool:
    """
    Word-boundary aware category filter.

    The plain 'in' check causes 'Men Juniors' to match 'Women Juniors' because
    'men juniors' is a substring of 'wo·men juniors'.  This function requires
    every word in the filter to start at a word boundary in the category text,
    which correctly rejects that false-positive while still allowing singular/
    plural variants like 'Junior' matching 'Juniors'.

    Examples:
      category_matches("XCO Men Juniors (SO 29.3.)", "Men Juniors")   → True
      category_matches("XCO Women Juniors (SO 29.3.)", "Men Juniors") → False
      category_matches("XCO Men Elite (SO 29.3.)", "Elite")            → True
      category_matches("Men Juniors (U19m) - Bundesliga", "Junior")    → True
    """
    if not filter_str:
        return True
    haystack = re.sub(r"[^\w\s]", " ", category_text.lower())
    for word in filter_str.lower().split():
        # Word must start at a boundary but may have trailing chars (Junior→Juniors)
        if not re.search(rf"\b{re.escape(word)}", haystack):
            return False
    return True


# ─────────────────────────── HTTP helper ──────────────────────────────────
def fetch(url: str, retries: int = 3, delay: float = 1.0) -> BeautifulSoup:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                console.print(f"[red]Error fetching {url}: {e}[/red]")
                raise


def normalize_country(raw: str) -> str:
    key = raw.strip().lower()
    if key in COUNTRY_NORMALIZE:
        return COUNTRY_NORMALIZE[key]
    for k, v in COUNTRY_NORMALIZE.items():
        if k in key:
            return v
    # If already a 3-letter IOC/ISO code, return as-is
    if re.match(r"^[A-Z]{3}$", raw.strip()):
        return raw.strip()
    return raw[:3].upper() if raw else "UNK"


def cell_direct_text(tag) -> str:
    """
    Returns only the direct text of a BeautifulSoup tag, ignoring child elements.

    xcodata renders rank and points cells like:
      <td>31<span class="change">6</span></td>     → rank cell
      <td>168<span class="change">+ 19</span></td> → points cell

    get_text() concatenates everything: "316" or "168+ 19".
    This function reads only the NavigableString nodes directly inside the tag,
    giving the clean values "31" and "168".
    """
    return "".join(
        str(t) for t in tag.children if isinstance(t, NavigableString)
    ).strip()


# ─────────────────────────── UCI ranking cache ────────────────────────────
def cache_path(uci_cat: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"ranking_{uci_cat}_2026.json")


def cache_is_fresh(uci_cat: str) -> bool:
    path = cache_path(uci_cat)
    if not os.path.exists(path):
        return False
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    return datetime.now() - mtime < timedelta(days=CACHE_MAX_AGE_DAYS)


def load_cache(uci_cat: str) -> dict:
    path = cache_path(uci_cat)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(uci_cat: str, data: dict):
    with open(cache_path(uci_cat), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_uci_cache(uci_cat: str) -> dict:
    """
    Downloads all pages of the UCI ranking from xcodata.com and saves to cache.
    Returns a dict keyed by lowercase rider name -> {rank, points, name}.
    """
    console.print(f"\n[cyan]Downloading UCI ranking ({uci_cat}) from xcodata.com...[/cyan]")
    cache = {"by_name": {}, "by_id": {}, "fetched_at": datetime.now().isoformat()}

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console) as progress:
        task = progress.add_task("Loading ranking pages...", total=None)
        page = 1
        while True:
            url = XCODATA_RANKING_BASE.format(cat=uci_cat, page=page)
            try:
                soup = fetch(url)
            except Exception:
                break

            rows = soup.find_all("tr")
            found_any = False
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 4:
                    continue
                # Expected columns: Rank | Rider | Team | Points
                # Use cell_direct_text to avoid concatenating the position-change
                # indicator that xcodata renders in a child <span> inside the same <td>.
                # e.g. <td>31<span>6</span></td> → direct text = "31", not "316"
                rank_text   = cell_direct_text(cols[0])
                rider_cell  = cols[1].get_text(strip=True)
                points_text = cell_direct_text(cols[3])

                rank_match = re.match(r"^(\d+)", rank_text)
                if not rank_match:
                    continue
                rank = int(rank_match.group(1))

                # Points: direct text gives "168", ignoring "+19" change span
                pts_match = re.match(r"^(\d+)", points_text)
                points = int(pts_match.group(1)) if pts_match else 0

                # xcodata name format: "Country [LASTNAME Firstname]"
                link = cols[1].find("a")
                if link:
                    name_raw = link.get_text(strip=True)
                else:
                    parts = rider_cell.split(None, 1)
                    name_raw = parts[1] if len(parts) > 1 else rider_cell

                name_normalized = normalize_rider_name(name_raw)
                name_key = name_normalized.lower()

                cache["by_name"][name_key] = {
                    "rank": rank, "points": points, "name": name_normalized
                }
                found_any = True

            if not found_any:
                break

            next_links = soup.find_all("a", href=True)
            has_next = any(f"/{page + 1}/" in a["href"] for a in next_links)
            if not has_next:
                break

            progress.update(task, description=f"Page {page} done, continuing...")
            page += 1
            time.sleep(0.3)  # Be polite to the server

    total = len(cache["by_name"])
    console.print(f"[green]✓ Loaded {total} riders from UCI ranking ({uci_cat})[/green]")
    save_cache(uci_cat, cache)
    return cache


def normalize_rider_name(raw: str) -> str:
    """Converts 'LASTNAME Firstname' to 'Firstname Lastname', handles ALL-CAPS last names."""
    raw = raw.strip()
    # Remove country prefix if present, e.g. "Slovakia [ŠICHTA Michal]"
    bracket_match = re.search(r"\[(.+?)\]", raw)
    if bracket_match:
        raw = bracket_match.group(1)

    parts = raw.split()
    if not parts:
        return raw

    # xcodata stores names as "LASTNAME Firstname" — detect by ALL-CAPS first word
    if parts[0].isupper() and len(parts) > 1:
        last  = parts[0].title()
        first = " ".join(parts[1:])
        return f"{first} {last}"
    return raw


def get_uci_cache(uci_cat: str, force_refresh: bool = False) -> dict:
    if not force_refresh and cache_is_fresh(uci_cat):
        console.print(f"[dim]Using cached UCI ranking ({uci_cat})[/dim]")
        return load_cache(uci_cat)
    return build_uci_cache(uci_cat)


def lookup_rider(rider: Rider, cache: dict) -> Rider:
    """Looks up UCI rank for a rider. Tries exact name match first, then fuzzy match."""
    by_name = cache.get("by_name", {})

    if not by_name:
        return rider

    # 1. Exact name match
    key = rider.full_name.lower()
    if key in by_name:
        entry = by_name[key]
        rider.uci_rank        = entry["rank"]
        rider.uci_points      = entry["points"]
        rider.match_confidence = 100
        return rider

    # 2. Swapped name order (last first)
    key2 = f"{rider.last_name} {rider.first_name}".lower()
    if key2 in by_name:
        entry = by_name[key2]
        rider.uci_rank        = entry["rank"]
        rider.uci_points      = entry["points"]
        rider.match_confidence = 100
        return rider

    # 3. Fuzzy match as fallback (threshold: 82 %)
    all_names = list(by_name.keys())
    if all_names:
        best_match, score = process.extractOne(key, all_names, scorer=fuzz.token_sort_ratio)
        if score >= 82:
            entry = by_name[best_match]
            rider.uci_rank        = entry["rank"]
            rider.uci_points      = entry["points"]
            rider.match_confidence = score
        else:
            rider.uci_rank        = None
            rider.uci_points      = 0
            rider.match_confidence = score

    return rider


# ─────────────────────────── start list parsers ───────────────────────────
def detect_site(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "sportzeitnehmung" in host:
        return "sportzeitnehmung"
    if "runtix" in host:
        return "runtix"
    return "unknown"


def parse_sportzeitnehmung(url: str, category_filter: str = None) -> list:
    """Parses a sportzeitnehmung.at registrant list, following pagination (?start=N)."""
    riders   = []
    base_url = url.split("?")[0]
    page_num = 0

    while True:
        page_url = f"{base_url}?start={page_num * 20}" if page_num > 0 else base_url
        soup  = fetch(page_url)
        table = soup.find("table")
        if not table:
            break

        rows       = table.find_all("tr")
        new_riders = 0
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 6:
                continue
            first   = cols[0].get_text(strip=True)
            last    = cols[1].get_text(strip=True)
            race    = cols[2].get_text(strip=True)
            country = cols[4].get_text(strip=True)
            uci_id  = re.sub(r"\s+", "", cols[5].get_text(strip=True))
            team    = cols[6].get_text(strip=True) if len(cols) > 6 else ""

            if not first or not last:
                continue
            # ── FIX: use word-boundary matching so "Men Juniors" ≠ "Women Juniors" ──
            if not category_matches(race, category_filter):
                continue

            riders.append(Rider(
                first_name=first, last_name=last,
                country=normalize_country(country),
                uci_id=uci_id, team=team, category=race
            ))
            new_riders += 1

        if new_riders == 0:
            break

        links      = [a.get("href", "") for a in soup.find_all("a", href=True)]
        next_start = (page_num + 1) * 20
        has_next   = any(f"start={next_start}" in lnk for lnk in links)
        if not has_next:
            break
        page_num += 1
        time.sleep(0.3)

    return riders


def parse_runtix(url: str, category_filter: str = None) -> list:
    """
    Parses a runtix.com start list.
    Name formats: 'LASTNAME, Firstname'  or  'LASTNAME Firstname'.
    No UCI IDs available — ranking resolved via fuzzy name matching.
    """
    soup    = fetch(url)
    riders  = []
    current_category = ""

    for element in soup.find_all(["h2", "h3", "table"]):
        if element.name in ("h2", "h3"):
            current_category = element.get_text(strip=True)
            continue

        if element.name != "table":
            continue

        # ── FIX: word-boundary matching ──
        if not category_matches(current_category, category_filter):
            continue

        rows = element.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            start_nr = cols[0].get_text(strip=True)
            if not re.match(r"\d+", start_nr):
                continue

            name_cell = cols[1]
            lines = [l.strip() for l in name_cell.get_text("\n").split("\n") if l.strip()]
            if not lines:
                continue

            raw_name   = lines[0]
            team       = lines[1] if len(lines) > 1 else ""
            birth_year = cols[2].get_text(strip=True) if len(cols) > 2 else ""
            nationality= cols[3].get_text(strip=True) if len(cols) > 3 else ""

            first, last = parse_runtix_name(raw_name)

            riders.append(Rider(
                first_name=first, last_name=last,
                country=normalize_country(nationality),
                team=team, category=current_category,
                birth_year=birth_year, start_nr=start_nr
            ))

    return riders


def parse_runtix_name(raw: str) -> tuple:
    """'LASTNAME, Firstname'  or  'LASTNAME Firstname'  ->  (Firstname, Lastname)"""
    raw = raw.strip()
    if "," in raw:
        parts = raw.split(",", 1)
        last  = parts[0].strip().title()
        first = parts[1].strip().title()
    else:
        parts = raw.split()
        if not parts:
            return ("", "")
        if len(parts) >= 2:
            if parts[0].isupper() or parts[0] == parts[0].upper():
                last  = parts[0].title()
                first = " ".join(p.title() for p in parts[1:])
            else:
                first = parts[0]
                last  = " ".join(parts[1:])
        else:
            first = ""
            last  = parts[0].title()
    return (first, last)


def parse_start_list(url: str, category_filter: str = None) -> tuple:
    """Auto-detects the website format and returns (riders, race_name)."""
    site = detect_site(url)
    console.print(f"[dim]Detected format: {site} — {url}[/dim]")

    soup_title = fetch(url)
    race_name  = soup_title.title.get_text(strip=True) if soup_title.title else url

    if site == "sportzeitnehmung":
        riders = parse_sportzeitnehmung(url, category_filter)
    elif site == "runtix":
        riders = parse_runtix(url, category_filter)
    else:
        console.print("[yellow]Unknown website format — trying generic parser...[/yellow]")
        riders = parse_generic(soup_title, category_filter)

    return riders, race_name


def parse_generic(soup: BeautifulSoup, category_filter: str = None) -> list:
    """Generic fallback parser for unsupported websites — scans all tables for rider rows."""
    riders = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr")[1:]:
            cols  = row.find_all("td")
            if len(cols) < 2:
                continue
            texts = [c.get_text(strip=True) for c in cols]
            if texts[0] and texts[1] and not texts[0].isdigit():
                riders.append(Rider(first_name=texts[0], last_name=texts[1],
                                    country=texts[2] if len(texts) > 2 else ""))
    return riders


# ─────────────────────────── sorting helper ───────────────────────────────
def sort_riders(riders: list) -> list:
    ranked   = sorted([r for r in riders if r.uci_rank is not None], key=lambda r: r.uci_rank)
    unranked = sorted([r for r in riders if r.uci_rank is None],     key=lambda r: r.full_name)
    return ranked + unranked


# ─────────────────────────── terminal display ─────────────────────────────
def display_riders(riders: list, race_name: str, uci_cat: str):
    """Displays the rider table sorted by UCI ranking (ranked first, then unranked A-Z)."""
    sorted_riders = sort_riders(riders)

    table = Table(
        title=(f"[bold cyan]{race_name}[/bold cyan]\n"
               f"[dim]UCI category: {uci_cat} | Total starters: {len(riders)}[/dim]"),
        show_header=True, header_style="bold magenta",
        border_style="dim", show_lines=False
    )
    table.add_column("#",        style="dim",  width=4,  justify="right")
    table.add_column("Name",                   min_width=22)
    table.add_column("Country",                width=8)
    table.add_column("UCI rank",               width=9,  justify="right")
    table.add_column("UCI pts",                width=8,  justify="right")
    table.add_column("UCI ID",   style="dim",  width=13)
    table.add_column("Team",     style="dim",  min_width=20)

    for i, r in enumerate(sorted_riders, 1):
        rank_str = str(r.uci_rank) if r.uci_rank else "[dim]—[/dim]"
        pts_str  = str(r.uci_points) if r.uci_points else "[dim]0[/dim]"
        confidence = ""
        if r.match_confidence < 100 and r.uci_rank:
            confidence = f" [dim]({r.match_confidence}%)[/dim]"
        country_display = f"{r.flag} {r.country}"

        # Colour-code rows by ranking tier
        if   r.uci_rank and r.uci_rank <= 50:  name_style = "bold green"
        elif r.uci_rank and r.uci_rank <= 200:  name_style = "green"
        elif r.uci_rank:                        name_style = "yellow"
        else:                                   name_style = "white"

        table.add_row(
            str(i),
            f"[{name_style}]{r.full_name}[/{name_style}]{confidence}",
            country_display,
            rank_str, pts_str,
            r.uci_id or "—",
            r.team[:40] if r.team else "—"
        )

    console.print(table)
    display_country_stats(sorted_riders)


def display_country_stats(riders: list):
    """Displays a breakdown of starters by country with a bar chart."""
    country_counts = Counter(r.country for r in riders)

    table = Table(title="[bold]Starters by Country[/bold]",
                  show_header=True, header_style="bold blue",
                  border_style="dim", padding=(0, 1))
    table.add_column("Country",  min_width=12)
    table.add_column("Count",    justify="right", width=7)
    table.add_column("Bar",      min_width=20)

    total = len(riders)
    for country, count in sorted(country_counts.items(), key=lambda x: -x[1]):
        flag = FLAG.get(country, "  ")
        bar  = "█" * count
        pct  = f"{count / total * 100:.0f}%"
        table.add_row(f"{flag} {country}", str(count),
                      f"[cyan]{bar}[/cyan] [dim]{pct}[/dim]")

    console.print(table)


# ─────────────────────────── quality stats ────────────────────────────────
def race_quality_stats(riders: list) -> dict:
    """Computes quality statistics for a race start list."""
    ranked     = [r for r in riders if r.uci_rank is not None and r.uci_points]
    total_pts  = sum(r.uci_points for r in ranked)
    top10_pts  = sum(r.uci_points for r in sorted(ranked, key=lambda r: r.uci_rank)[:10])
    avg_rank   = (sum(r.uci_rank for r in ranked) / len(ranked)) if ranked else None
    best_rank  = min((r.uci_rank for r in ranked), default=None)

    return {
        "total":      len(riders),
        "ranked":     len(ranked),
        "top50":      sum(1 for r in ranked if r.uci_rank <= 50),
        "top100":     sum(1 for r in ranked if r.uci_rank <= 100),
        "top200":     sum(1 for r in ranked if r.uci_rank <= 200),
        "best_rank":  best_rank,
        "avg_rank":   avg_rank,
        "total_pts":  total_pts,
        "top10_pts":  top10_pts,
    }


# ─────────────────────────── comparison (terminal) ────────────────────────
def display_comparison(race1_data: tuple, race2_data: tuple, uci_cat: str):
    """Compares two races side by side and recommends the one with the stronger field."""
    riders1, name1, url1 = race1_data
    riders2, name2, url2 = race2_data
    stats1 = race_quality_stats(riders1)
    stats2 = race_quality_stats(riders2)

    def quality_score(s):
        return (s["top10_pts"] * 3 + s["top50"] * 10 +
                s["top100"] * 5 + s["top200"] * 2 + s["ranked"])

    score1 = quality_score(stats1)
    score2 = quality_score(stats2)

    console.print()
    console.rule("[bold yellow]⚔  RACE COMPARISON  ⚔[/bold yellow]")
    console.print()

    comp = Table(show_header=True, header_style="bold", border_style="blue", padding=(0, 2))
    comp.add_column("Metric",    style="bold",  min_width=30)
    comp.add_column("🏁 Race 1", justify="center", min_width=22, style="cyan")
    comp.add_column("🏁 Race 2", justify="center", min_width=22, style="magenta")

    def winner_style(v1, v2, higher_is_better=True):
        if v1 is None or v2 is None:
            return str(v1 or "—"), str(v2 or "—")
        better = (v1 > v2) if higher_is_better else (v1 < v2)
        s1 = f"[bold green]{v1}[/bold green]" if better     else str(v1)
        s2 = f"[bold green]{v2}[/bold green]" if not better else str(v2)
        return s1, s2

    rows_data = [
        ("Race name",                    name1[:45],  name2[:45],  None),
        ("URL",
         (url1[:50] + "...") if len(url1) > 50 else url1,
         (url2[:50] + "...") if len(url2) > 50 else url2, None),
        ("─" * 27,                       "",          "",          None),
        ("Total starters",               stats1["total"],      stats2["total"],      True),
        ("Riders in UCI ranking",         stats1["ranked"],     stats2["ranked"],     True),
        ("─" * 27,                       "",          "",          None),
        ("Riders in TOP 50",              stats1["top50"],      stats2["top50"],      True),
        ("Riders in TOP 100",             stats1["top100"],     stats2["top100"],     True),
        ("Riders in TOP 200",             stats1["top200"],     stats2["top200"],     True),
        ("─" * 27,                       "",          "",          None),
        ("Best UCI ranking",              stats1["best_rank"],  stats2["best_rank"],  False),
        ("Average rank (ranked riders)",
         f"{stats1['avg_rank']:.0f}" if stats1["avg_rank"] else "—",
         f"{stats2['avg_rank']:.0f}" if stats2["avg_rank"] else "—", False),
        ("─" * 27,                       "",          "",          None),
        ("Points of TOP 10 riders",       stats1["top10_pts"],  stats2["top10_pts"],  True),
        ("Total UCI points",              stats1["total_pts"],  stats2["total_pts"],  True),
        ("─" * 27,                       "",          "",          None),
        ("🏆 QUALITY SCORE",              score1,      score2,      True),
    ]

    for row in rows_data:
        label, v1, v2, higher = row
        if higher is None:
            comp.add_row(f"[dim]{label}[/dim]", str(v1), str(v2))
        else:
            try:
                s1, s2 = winner_style(int(str(v1).replace("—", "0")),
                                       int(str(v2).replace("—", "0")), higher)
            except (ValueError, TypeError):
                s1, s2 = str(v1), str(v2)
            comp.add_row(label, s1, s2)

    console.print(comp)
    console.print()

    if   score1 > score2:
        diff    = score1 - score2
        verdict = (f"[bold green]✅  RACE 1 has a stronger field[/bold green]\n"
                   f"[dim]{name1}[/dim]\n[dim](quality score higher by {diff})[/dim]")
    elif score2 > score1:
        diff    = score2 - score1
        verdict = (f"[bold green]✅  RACE 2 has a stronger field[/bold green]\n"
                   f"[dim]{name2}[/dim]\n[dim](quality score higher by {diff})[/dim]")
    else:
        verdict = "[yellow]⚖  Both races are of comparable quality[/yellow]"

    console.print(Panel(verdict, title="Verdict", border_style="green", padding=(1, 4)))
    console.print()

    for label, riders in [(f"TOP 5 — {name1[:40]}", riders1),
                           (f"TOP 5 — {name2[:40]}", riders2)]:
        top5 = sorted([r for r in riders if r.uci_rank], key=lambda r: r.uci_rank)[:5]
        if top5:
            top = Table(title=label, show_header=False, border_style="dim", padding=(0, 1))
            top.add_column("Rank",    width=6, justify="right")
            top.add_column("Name",    min_width=22)
            top.add_column("Points",  width=7, justify="right")
            top.add_column("Country", width=8)
            for r in top5:
                top.add_row(str(r.uci_rank), r.full_name,
                            str(r.uci_points), f"{r.flag} {r.country}")
            console.print(top)
            console.print()


# ─────────────────────────── CSV export ───────────────────────────────────
def export_csv(riders: list, path: str):
    """Exports the rider list to a CSV file, sorted by UCI ranking."""
    sorted_riders = sort_riders(riders)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["#", "First name", "Last name", "Country",
                          "UCI rank", "UCI points", "UCI ID",
                          "Team", "Category", "Birth year"])
        for i, r in enumerate(sorted_riders, 1):
            writer.writerow([i, r.first_name, r.last_name, r.country,
                              r.uci_rank or "", r.uci_points or 0,
                              r.uci_id, r.team, r.category, r.birth_year])
    console.print(f"[green]✓ CSV exported to {path}[/green]")


# ─────────────────────────── HTML export ──────────────────────────────────
def rank_tier(uci_rank: Optional[int]) -> str:
    """Returns a CSS class name based on the ranking tier."""
    if uci_rank and uci_rank <= 50:  return "tier-top50"
    if uci_rank and uci_rank <= 200: return "tier-top200"
    if uci_rank:                     return "tier-ranked"
    return "tier-unranked"


def export_html(riders: list, race_name: str, uci_cat: str, path: str,
                compare_data: tuple = None):
    """
    Exports a polished, self-contained HTML report.
    If compare_data=(riders2, name2, url2, url1) is provided, a comparison
    section is appended at the end of the file.
    """
    sorted_riders    = sort_riders(riders)
    country_counts   = Counter(r.country for r in sorted_riders)
    stats            = race_quality_stats(riders)
    generated_at     = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── rider rows ──────────────────────────────────────────────────────────
    def rider_row(i: int, r: Rider) -> str:
        tier       = rank_tier(r.uci_rank)
        rank_disp  = str(r.uci_rank)   if r.uci_rank   else "—"
        pts_disp   = str(r.uci_points) if r.uci_points else "0"
        conf_badge = ""
        if r.match_confidence < 100 and r.uci_rank:
            conf_badge = f'<span class="conf-badge">{r.match_confidence}%</span>'
        uci_id_disp = r.uci_id if r.uci_id else "—"
        team_disp   = r.team[:50] if r.team else "—"
        return (
            f'<tr class="{tier}">'
            f'<td class="num">{i}</td>'
            f'<td class="name">{r.full_name}{conf_badge}</td>'
            f'<td class="country">{r.flag} {r.country}</td>'
            f'<td class="rank">{rank_disp}</td>'
            f'<td class="pts">{pts_disp}</td>'
            f'<td class="uci-id">{uci_id_disp}</td>'
            f'<td class="team">{team_disp}</td>'
            f'</tr>\n'
        )

    rows_html = "".join(rider_row(i, r) for i, r in enumerate(sorted_riders, 1))

    # ── country bars ────────────────────────────────────────────────────────
    total = len(sorted_riders)
    max_count = max(country_counts.values(), default=1)
    country_rows = ""
    for country, count in sorted(country_counts.items(), key=lambda x: -x[1]):
        flag_str  = FLAG.get(country, "")
        pct       = count / total * 100
        bar_pct   = count / max_count * 100
        country_rows += (
            f'<tr>'
            f'<td class="c-flag">{flag_str} {country}</td>'
            f'<td class="c-count">{count}</td>'
            f'<td class="c-bar-cell">'
            f'  <div class="c-bar" style="width:{bar_pct:.1f}%"></div>'
            f'  <span class="c-pct">{pct:.0f}%</span>'
            f'</td>'
            f'</tr>\n'
        )

    # ── stat cards ──────────────────────────────────────────────────────────
    def stat_card(label: str, value, sub: str = "") -> str:
        sub_html = f'<div class="card-sub">{sub}</div>' if sub else ""
        return (f'<div class="stat-card">'
                f'<div class="card-val">{value}</div>'
                f'<div class="card-label">{label}</div>'
                f'{sub_html}</div>\n')

    avg_str = f"{stats['avg_rank']:.0f}" if stats["avg_rank"] else "—"
    stat_cards = (
        stat_card("Total starters",    stats["total"])  +
        stat_card("Ranked riders",     stats["ranked"]) +
        stat_card("Best UCI rank",     stats["best_rank"] or "—") +
        stat_card("Avg UCI rank",      avg_str, "(ranked only)") +
        stat_card("TOP 50",            stats["top50"]) +
        stat_card("TOP 100",           stats["top100"]) +
        stat_card("TOP 200",           stats["top200"]) +
        stat_card("Total UCI pts",     stats["total_pts"]) +
        stat_card("TOP-10 pts",        stats["top10_pts"], "(top 10 riders)")
    )

    # ── optional comparison section ─────────────────────────────────────────
    comparison_html = ""
    if compare_data:
        riders2, name2, url2, url1 = compare_data
        stats2 = race_quality_stats(riders2)

        def qs(s):
            return (s["top10_pts"]*3 + s["top50"]*10 +
                    s["top100"]*5 + s["top200"]*2 + s["ranked"])

        sc1, sc2 = qs(stats), qs(stats2)

        if   sc1 > sc2: verdict_txt = f"🏆 Race 1 has a stronger field (score +{sc1-sc2})"
        elif sc2 > sc1: verdict_txt = f"🏆 Race 2 has a stronger field (score +{sc2-sc1})"
        else:           verdict_txt = "⚖ Both races are of comparable quality"

        def cmp_row(label, v1, v2, higher=True):
            try:
                iv1, iv2 = int(str(v1).replace("—","0")), int(str(v2).replace("—","0"))
                c1 = ' class="win"' if (iv1>iv2 if higher else iv1<iv2) else ""
                c2 = ' class="win"' if (iv2>iv1 if higher else iv2<iv1) else ""
            except (ValueError, TypeError):
                c1 = c2 = ""
            return f'<tr><td>{label}</td><td{c1}>{v1}</td><td{c2}>{v2}</td></tr>\n'

        avg1 = f"{stats['avg_rank']:.0f}"  if stats["avg_rank"]  else "—"
        avg2 = f"{stats2['avg_rank']:.0f}" if stats2["avg_rank"] else "—"

        top5_r1 = sorted([r for r in riders  if r.uci_rank], key=lambda r: r.uci_rank)[:5]
        top5_r2 = sorted([r for r in riders2 if r.uci_rank], key=lambda r: r.uci_rank)[:5]

        def top5_html(top5):
            rows = ""
            for r in top5:
                rows += (f'<tr><td class="rank">{r.uci_rank}</td>'
                         f'<td class="name">{r.full_name}</td>'
                         f'<td class="pts">{r.uci_points}</td>'
                         f'<td class="country">{r.flag} {r.country}</td></tr>\n')
            return rows or '<tr><td colspan="4">No ranked riders</td></tr>'

        comparison_html = f"""
<section class="comparison">
  <h2>⚔ Race Comparison</h2>
  <div class="verdict-box">{verdict_txt}</div>

  <table class="cmp-table">
    <thead>
      <tr><th>Metric</th><th>🏁 Race 1</th><th>🏁 Race 2</th></tr>
    </thead>
    <tbody>
      {cmp_row("Race name",                   race_name[:50], name2[:50],          higher=None)}
      {cmp_row("Total starters",              stats["total"],      stats2["total"],      True)}
      {cmp_row("Riders in UCI ranking",        stats["ranked"],     stats2["ranked"],     True)}
      {cmp_row("Riders in TOP 50",             stats["top50"],      stats2["top50"],      True)}
      {cmp_row("Riders in TOP 100",            stats["top100"],     stats2["top100"],     True)}
      {cmp_row("Riders in TOP 200",            stats["top200"],     stats2["top200"],     True)}
      {cmp_row("Best UCI ranking",             stats["best_rank"] or "—", stats2["best_rank"] or "—", False)}
      {cmp_row("Avg rank (ranked only)",       avg1,                avg2,                 False)}
      {cmp_row("Points of TOP 10 riders",      stats["top10_pts"],  stats2["top10_pts"],  True)}
      {cmp_row("Total UCI points",             stats["total_pts"],  stats2["total_pts"],  True)}
      {cmp_row("🏆 Quality score",             sc1,                 sc2,                  True)}
    </tbody>
  </table>

  <div class="top5-grid">
    <div>
      <h3>TOP 5 — Race 1</h3>
      <table class="top5-table">
        <thead><tr><th>Rank</th><th>Name</th><th>Pts</th><th>Country</th></tr></thead>
        <tbody>{top5_html(top5_r1)}</tbody>
      </table>
    </div>
    <div>
      <h3>TOP 5 — Race 2</h3>
      <table class="top5-table">
        <thead><tr><th>Rank</th><th>Name</th><th>Pts</th><th>Country</th></tr></thead>
        <tbody>{top5_html(top5_r2)}</tbody>
      </table>
    </div>
  </div>
</section>
"""

    # ── full HTML document ───────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{race_name}</title>
<style>
  /* ── reset & base ─────────────────────────────── */
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: #0f1117;
    color: #e2e8f0;
    line-height: 1.5;
    padding: 2rem 1rem;
  }}
  a {{ color: #63b3ed; }}

  /* ── layout ───────────────────────────────────── */
  .container {{ max-width: 1200px; margin: 0 auto; }}

  /* ── header ───────────────────────────────────── */
  .page-header {{
    border-left: 4px solid #4299e1;
    padding: 1rem 1.5rem;
    margin-bottom: 2rem;
    background: #1a202c;
    border-radius: 0 8px 8px 0;
  }}
  .page-header h1 {{
    font-size: 1.6rem;
    color: #90cdf4;
    font-weight: 700;
    margin-bottom: .3rem;
  }}
  .page-header .meta {{
    font-size: .85rem;
    color: #718096;
  }}

  /* ── stat cards ───────────────────────────────── */
  .stats-grid {{
    display: flex;
    flex-wrap: wrap;
    gap: .75rem;
    margin-bottom: 2rem;
  }}
  .stat-card {{
    background: #1a202c;
    border: 1px solid #2d3748;
    border-radius: 8px;
    padding: .8rem 1.2rem;
    min-width: 110px;
    text-align: center;
  }}
  .card-val   {{ font-size: 1.7rem; font-weight: 700; color: #63b3ed; }}
  .card-label {{ font-size: .75rem; color: #a0aec0; margin-top: .2rem; }}
  .card-sub   {{ font-size: .7rem;  color: #718096; }}

  /* ── main rider table ─────────────────────────── */
  .section-title {{
    font-size: 1.1rem;
    font-weight: 600;
    color: #a0aec0;
    margin: 1.5rem 0 .6rem;
    text-transform: uppercase;
    letter-spacing: .08em;
  }}
  .rider-table-wrap {{ overflow-x: auto; margin-bottom: 2rem; }}
  table.rider-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: .88rem;
  }}
  table.rider-table thead tr {{
    background: #2d3748;
    color: #a0aec0;
    text-transform: uppercase;
    font-size: .75rem;
    letter-spacing: .06em;
  }}
  table.rider-table th, table.rider-table td {{
    padding: .55rem .75rem;
    text-align: left;
    border-bottom: 1px solid #2d3748;
    white-space: nowrap;
  }}
  table.rider-table td.num   {{ color: #718096; text-align: right; width: 40px; }}
  table.rider-table td.rank  {{ text-align: right; font-variant-numeric: tabular-nums; }}
  table.rider-table td.pts   {{ text-align: right; font-variant-numeric: tabular-nums; }}
  table.rider-table td.uci-id{{ color: #718096; font-size: .8rem; }}
  table.rider-table td.team  {{ color: #a0aec0; font-size: .82rem; }}

  /* tier colouring */
  tr.tier-top50  td.name {{ color: #68d391; font-weight: 600; }}
  tr.tier-top50  td.rank {{ color: #68d391; font-weight: 600; }}
  tr.tier-top200 td.name {{ color: #9ae6b4; }}
  tr.tier-top200 td.rank {{ color: #9ae6b4; }}
  tr.tier-ranked td.name {{ color: #f6e05e; }}
  tr.tier-ranked td.rank {{ color: #f6e05e; }}
  tr.tier-unranked td.rank {{ color: #4a5568; }}

  table.rider-table tbody tr:hover {{ background: #1e2738; }}

  .conf-badge {{
    display: inline-block;
    margin-left: .4rem;
    font-size: .7rem;
    background: #2d3748;
    color: #718096;
    border-radius: 4px;
    padding: 1px 5px;
    vertical-align: middle;
  }}

  /* ── country table ────────────────────────────── */
  table.country-table {{
    border-collapse: collapse;
    font-size: .88rem;
    margin-bottom: 2rem;
  }}
  table.country-table td {{ padding: .4rem .75rem; border-bottom: 1px solid #2d3748; }}
  td.c-flag   {{ white-space: nowrap; min-width: 80px; }}
  td.c-count  {{ text-align: right; min-width: 50px; color: #63b3ed; font-weight: 600; }}
  td.c-bar-cell {{ width: 260px; position: relative; }}
  .c-bar {{
    height: 14px;
    background: linear-gradient(90deg, #3182ce, #63b3ed);
    border-radius: 3px;
    display: inline-block;
    vertical-align: middle;
  }}
  .c-pct {{
    margin-left: .5rem;
    color: #718096;
    font-size: .78rem;
    vertical-align: middle;
  }}

  /* ── comparison section ───────────────────────── */
  .comparison {{ margin-top: 3rem; }}
  .comparison h2 {{
    font-size: 1.3rem;
    color: #f6ad55;
    margin-bottom: 1rem;
    padding-bottom: .5rem;
    border-bottom: 1px solid #2d3748;
  }}
  .verdict-box {{
    background: #1c3044;
    border: 1px solid #2b6cb0;
    border-radius: 8px;
    padding: 1rem 1.5rem;
    font-size: 1rem;
    font-weight: 600;
    color: #90cdf4;
    margin-bottom: 1.5rem;
  }}
  table.cmp-table {{
    width: 100%;
    max-width: 700px;
    border-collapse: collapse;
    font-size: .88rem;
    margin-bottom: 2rem;
  }}
  table.cmp-table th {{
    background: #2d3748;
    color: #a0aec0;
    text-transform: uppercase;
    font-size: .75rem;
    letter-spacing: .06em;
    padding: .55rem .9rem;
    text-align: center;
  }}
  table.cmp-table th:first-child {{ text-align: left; }}
  table.cmp-table td {{
    padding: .5rem .9rem;
    border-bottom: 1px solid #2d3748;
    text-align: center;
  }}
  table.cmp-table td:first-child {{ text-align: left; color: #a0aec0; }}
  table.cmp-table td.win {{ color: #68d391; font-weight: 700; }}

  .top5-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
    margin-top: 1rem;
  }}
  @media (max-width: 640px) {{ .top5-grid {{ grid-template-columns: 1fr; }} }}
  .top5-grid h3 {{ font-size: .95rem; color: #a0aec0; margin-bottom: .5rem; }}
  table.top5-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: .85rem;
  }}
  table.top5-table th {{
    background: #2d3748;
    color: #718096;
    text-transform: uppercase;
    font-size: .72rem;
    padding: .4rem .6rem;
    text-align: left;
  }}
  table.top5-table td {{
    padding: .4rem .6rem;
    border-bottom: 1px solid #2d3748;
  }}
  table.top5-table td.rank {{ color: #63b3ed; font-weight: 600; text-align: right; }}
  table.top5-table td.pts  {{ text-align: right; color: #a0aec0; }}

  /* ── legend ───────────────────────────────────── */
  .legend {{
    display: flex;
    gap: 1.2rem;
    flex-wrap: wrap;
    font-size: .78rem;
    margin-bottom: 1rem;
    color: #a0aec0;
  }}
  .legend span {{ display: flex; align-items: center; gap: .35rem; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
  .dot-top50  {{ background: #68d391; }}
  .dot-top200 {{ background: #9ae6b4; }}
  .dot-ranked {{ background: #f6e05e; }}
  .dot-none   {{ background: #4a5568; }}

  /* ── footer ───────────────────────────────────── */
  .footer {{
    margin-top: 3rem;
    font-size: .75rem;
    color: #4a5568;
    border-top: 1px solid #2d3748;
    padding-top: 1rem;
  }}

  /* ── search box ───────────────────────────────── */
  .search-wrap {{ margin-bottom: .75rem; }}
  #search {{
    background: #1a202c;
    border: 1px solid #2d3748;
    color: #e2e8f0;
    border-radius: 6px;
    padding: .45rem .8rem;
    font-size: .88rem;
    width: 280px;
    outline: none;
  }}
  #search:focus {{ border-color: #4299e1; }}
</style>
</head>
<body>
<div class="container">

  <header class="page-header">
    <h1>{race_name}</h1>
    <div class="meta">
      UCI category: <strong>{uci_cat}</strong> &nbsp;|&nbsp;
      Total starters: <strong>{len(riders)}</strong> &nbsp;|&nbsp;
      Generated: {generated_at} &nbsp;|&nbsp;
      Ranking data: <a href="https://www.xcodata.com" target="_blank">xcodata.com</a>
    </div>
  </header>

  <!-- stat cards -->
  <div class="stats-grid">
{stat_cards}
  </div>

  <!-- rider table -->
  <div class="section-title">Start List</div>

  <div class="legend">
    <span><span class="dot dot-top50"></span>TOP 50</span>
    <span><span class="dot dot-top200"></span>TOP 51–200</span>
    <span><span class="dot dot-ranked"></span>Ranked 201+</span>
    <span><span class="dot dot-none"></span>Unranked</span>
    <span style="margin-left:.5rem;font-style:italic">Badge (87%) = fuzzy name match confidence</span>
  </div>

  <div class="search-wrap">
    <input id="search" type="text" placeholder="🔍  Filter by name, country or team…" oninput="filterTable()">
  </div>

  <div class="rider-table-wrap">
    <table class="rider-table" id="riderTable">
      <thead>
        <tr>
          <th>#</th><th>Name</th><th>Country</th>
          <th>UCI rank</th><th>UCI pts</th><th>UCI ID</th><th>Team</th>
        </tr>
      </thead>
      <tbody>
{rows_html}
      </tbody>
    </table>
  </div>

  <!-- country breakdown -->
  <div class="section-title">Starters by Country</div>
  <table class="country-table">
    <tbody>
{country_rows}
    </tbody>
  </table>

{comparison_html}

  <div class="footer">
    MTB Start List Analyzer &nbsp;|&nbsp; Ranking data © xcodata.com &nbsp;|&nbsp; {generated_at}
  </div>
</div>

<script>
function filterTable() {{
  var q = document.getElementById('search').value.toLowerCase();
  var rows = document.querySelectorAll('#riderTable tbody tr');
  rows.forEach(function(row) {{
    row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    console.print(f"[green]✓ HTML report exported to {path}[/green]")


# ─────────────────────────── export dispatcher ────────────────────────────
def export_file(riders: list, race_name: str, uci_cat: str, path: str,
                compare_data: tuple = None):
    """Routes to HTML or CSV export based on file extension."""
    if path.lower().endswith(".html") or path.lower().endswith(".htm"):
        export_html(riders, race_name, uci_cat, path, compare_data=compare_data)
    else:
        export_csv(riders, path)


# ─────────────────────────── main entry point ─────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="MTB Start List Analyzer — fetches a start list and enriches it with UCI ranking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--url",
                        help="Start list URL")
    parser.add_argument("--compare", nargs=2, metavar=("URL1", "URL2"),
                        help="Compare two start lists side by side")
    parser.add_argument("--category", "-c", default=None,
                        help="Category filter, e.g. 'Men Juniors', 'Junior', 'Elite'")
    parser.add_argument("--uci-category", "-u", default="MJ",
                        choices=["MJ", "WJ", "ME", "WE"],
                        help="UCI ranking category to use (default: MJ = Men Juniors)")
    parser.add_argument("--refresh-cache", action="store_true",
                        help="Force re-download of UCI ranking (ignores local cache)")
    parser.add_argument("--export", metavar="file.html",
                        help="Export results to HTML (.html) or CSV (.csv)")
    parser.add_argument("--no-lookup", action="store_true",
                        help="Skip UCI ranking lookup (faster — start list only)")

    args = parser.parse_args()

    if not args.url and not args.compare and not args.refresh_cache:
        parser.print_help()
        sys.exit(0)

    console.print(Panel.fit(
        "[bold cyan]MTB Start List Analyzer[/bold cyan]\n"
        "[dim]Ranking data: xcodata.com[/dim]",
        border_style="cyan"
    ))

    # Load or refresh the UCI ranking cache
    uci_cache = {}
    if not args.no_lookup:
        uci_cache = get_uci_cache(args.uci_category, force_refresh=args.refresh_cache)

    if args.refresh_cache and not args.url and not args.compare:
        console.print("[green]Cache refreshed.[/green]")
        return

    def process_url(url):
        with console.status("[cyan]Fetching start list...[/cyan]"):
            riders, race_name = parse_start_list(url, args.category)

        if not riders:
            console.print("[red]No riders found — check your --category filter.[/red]")
            return [], race_name

        console.print(f"[green]✓ Found {len(riders)} riders[/green]")

        if not args.no_lookup and uci_cache:
            with Progress(SpinnerColumn(), TextColumn("Looking up UCI rankings..."),
                          console=console) as prog:
                task = prog.add_task("", total=len(riders))
                for rider in riders:
                    lookup_rider(rider, uci_cache)
                    prog.advance(task)

        return riders, race_name

    # ── Single race mode ──────────────────────────────────────────────────
    if args.url:
        riders, race_name = process_url(args.url)
        if riders:
            display_riders(riders, race_name, args.uci_category)
            if args.export:
                export_file(riders, race_name, args.uci_category, args.export)

    # ── Comparison mode ───────────────────────────────────────────────────
    elif args.compare:
        url1, url2 = args.compare
        riders1, name1 = process_url(url1)
        riders2, name2 = process_url(url2)

        if riders1:
            display_riders(riders1, name1, args.uci_category)
        if riders2:
            display_riders(riders2, name2, args.uci_category)

        if riders1 and riders2:
            display_comparison(
                (riders1, name1, url1),
                (riders2, name2, url2),
                args.uci_category
            )

        # Export: single HTML file contains both races + comparison
        if args.export:
            ext = os.path.splitext(args.export)[1].lower()
            if ext in (".html", ".htm"):
                # Embed race 2 data as compare_data inside the race 1 HTML
                export_html(riders1, name1, args.uci_category, args.export,
                            compare_data=(riders2, name2, url2, url1))
                console.print(f"[dim]Both races and comparison written to {args.export}[/dim]")
            else:
                # CSV: two separate files
                p1 = args.export.replace(".csv", "_race1.csv")
                p2 = args.export.replace(".csv", "_race2.csv")
                if riders1: export_csv(riders1, p1)
                if riders2: export_csv(riders2, p2)


if __name__ == "__main__":
    main()
