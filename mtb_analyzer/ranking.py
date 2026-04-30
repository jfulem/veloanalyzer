import json
import os
import re
import time
from datetime import datetime, timedelta

from rich.progress import Progress, SpinnerColumn, TextColumn
from thefuzz import fuzz, process

from .config import (
    CACHE_DIR, CACHE_MAX_AGE_DAYS, HEADERS, XCODATA_BASE, console,
)
from .models import Rider
from .utils import cell_direct_text, fetch, normalize_rider_name


def cache_path(uci_cat: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    year = datetime.now().year
    return os.path.join(CACHE_DIR, f"ranking_{uci_cat}_{year}.json")


def get_latest_ranking_date(uci_cat: str) -> tuple:
    """
    Returns (year, date_slug) of the most recent ranking published on xcodata.com.
    Falls back to the most recent Tuesday if the page can't be fetched.
    """
    try:
        soup = fetch(f"{XCODATA_BASE}/rankings/{uci_cat}/")
        for sel in soup.find_all("select"):
            for opt in sel.find_all("option"):
                href = opt.get("value", "")
                m = re.search(r"/rankings/\w+/(\d{4})/(\d{4}-\d{2}-\d{2})/", href)
                if m:
                    return m.group(1), m.group(2)
    except Exception:
        pass
    # Fallback: last Tuesday (xcodata publishes on Tuesdays)
    today = datetime.now().date()
    days_since_tuesday = (today.weekday() - 1) % 7
    latest = today - timedelta(days=days_since_tuesday)
    return str(latest.year), latest.strftime("%Y-%m-%d")


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
    """Downloads all pages of the UCI ranking from xcodata.com and saves to cache."""
    year, date = get_latest_ranking_date(uci_cat)
    console.print(f"\n[cyan]Downloading UCI ranking ({uci_cat}, {date}) from xcodata.com...[/cyan]")
    cache = {"by_name": {}, "by_id": {}, "fetched_at": datetime.now().isoformat(), "ranking_date": date}

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console) as progress:
        task = progress.add_task("Loading ranking pages...", total=None)
        page = 1
        while True:
            url = f"{XCODATA_BASE}/rankings/{uci_cat}/{year}/{date}/{page}/?country="
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
                circle      = cols[0].find("div", class_="circle")
                rank_text   = circle.get_text(strip=True) if circle else cell_direct_text(cols[0])
                rider_cell  = cols[1].get_text(strip=True)
                points_text = cell_direct_text(cols[3])

                rank_match = re.match(r"^(\d+)", rank_text)
                if not rank_match:
                    continue
                rank = int(rank_match.group(1))

                pts_match = re.match(r"^(\d+)", points_text)
                points = int(pts_match.group(1)) if pts_match else 0

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
            time.sleep(0.3)

    total = len(cache["by_name"])
    console.print(f"[green]✓ Loaded {total} riders from UCI ranking ({uci_cat})[/green]")
    save_cache(uci_cat, cache)
    return cache


def get_uci_cache(uci_cat: str, force_refresh: bool = False) -> dict:
    if not force_refresh and cache_is_fresh(uci_cat):
        console.print(f"[dim]Using cached UCI ranking ({uci_cat})[/dim]")
        return load_cache(uci_cat)
    return build_uci_cache(uci_cat)


def lookup_rider(rider: Rider, cache: dict) -> Rider:
    """Looks up UCI rank for a rider. Tries exact name match first, then fuzzy."""
    by_name = cache.get("by_name", {})
    if not by_name:
        return rider

    key = rider.full_name.lower()
    if key in by_name:
        entry = by_name[key]
        rider.uci_rank         = entry["rank"]
        rider.uci_points       = entry["points"]
        rider.match_confidence = 100
        return rider

    key2 = f"{rider.last_name} {rider.first_name}".lower()
    if key2 in by_name:
        entry = by_name[key2]
        rider.uci_rank         = entry["rank"]
        rider.uci_points       = entry["points"]
        rider.match_confidence = 100
        return rider

    all_names = list(by_name.keys())
    if all_names:
        best_match, score = process.extractOne(key, all_names, scorer=fuzz.token_sort_ratio)
        if score >= 82:
            entry = by_name[best_match]
            rider.uci_rank         = entry["rank"]
            rider.uci_points       = entry["points"]
            rider.match_confidence = score
        else:
            rider.uci_rank         = None
            rider.uci_points       = 0
            rider.match_confidence = score

    return rider
