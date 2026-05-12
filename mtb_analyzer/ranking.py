import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta

from rich.progress import Progress, SpinnerColumn, TextColumn
from thefuzz import fuzz, process

from .config import (
    CACHE_DIR, CACHE_MAX_AGE_DAYS, FLAG, HEADERS, ISO2_TO_IOC, XCODATA_BASE, console,
)
from .models import Rider
from .utils import cell_direct_text, fetch, normalize_country, normalize_rider_name


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


_DATE_RE = re.compile(r'\d{2}(?:\s*-\s*\d{2})?\s+\w{3}\s+\d{4}')


def _strip_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def infer_rider_slug(first_name: str, last_name: str) -> str:
    """
    For riders not found in the UCI ranking, try to locate their xcodata profile
    by guessing the slug from the name (xcodata uses ASCII-ified, hyphenated slugs).
    Tries both 'first-last' and 'last-first' orderings.
    """
    def to_slug(name: str) -> str:
        s = _strip_diacritics(name.lower())
        return "/rider/" + re.sub(r"[^a-z0-9]+", "-", s).strip("-") + "/"

    for order in (f"{first_name} {last_name}", f"{last_name} {first_name}"):
        slug = to_slug(order)
        try:
            fetch(f"{XCODATA_BASE}{slug}")
            return slug
        except Exception:
            pass
    return ""


def _rider_cache_path(slug: str) -> str:
    riders_dir = os.path.join(CACHE_DIR, "riders")
    os.makedirs(riders_dir, exist_ok=True)
    safe = slug.strip("/").replace("/", "_")
    return os.path.join(riders_dir, f"{safe}.json")


def _flag_img_to_ioc(img) -> str:
    """Extract IOC country code from a flag <img> tag (flagcdn.com src or alt text)."""
    src = img.get("src", "").lower()
    m = re.search(r"/([a-z]{2})\.(?:png|gif|svg)", src)
    if m:
        iso2 = m.group(1).upper()
        if iso2 in ISO2_TO_IOC:
            return ISO2_TO_IOC[iso2]
    alt = img.get("alt", "").strip()
    if alt.upper() in FLAG:
        return alt.upper()
    if alt:
        normed = normalize_country(alt)
        if normed and normed != "UNK":
            return normed
    return ""


def _country_from_soup(soup) -> str:
    """Return the first IOC country code found via any flag image in soup."""
    for img in soup.find_all("img"):
        c = _flag_img_to_ioc(img)
        if c:
            return c
    return ""


def _rider_history_is_fresh(mtime: datetime) -> bool:
    """
    Weekday-aware freshness check for rider history / race-page caches.

    Outside July/August races only happen on weekends, so data fetched any time
    after the Monday of the current week is still current (no new results can
    appear Mon–Fri).  On weekends or during the summer the cache expires quickly.
    """
    now = datetime.now()
    month = now.month
    weekday = now.weekday()  # 0 = Mon, 6 = Sun

    if month in (7, 8):
        return now - mtime < timedelta(days=2)

    if weekday >= 5:  # Sat or Sun — race weekend
        return now - mtime < timedelta(days=1)

    # Mon–Fri outside summer: fresh if written on or after Monday 00:00 this week
    monday = (now - timedelta(days=weekday)).replace(hour=0, minute=0, second=0, microsecond=0)
    return mtime >= monday


def fetch_rider_history(slug: str) -> list:
    """Fetch race result history for a rider from their xcodata.com profile page.

    Cache format: {"country": "CZE", "results": [...]} — old plain-list caches are
    handled transparently (read as results, country treated as unknown).
    """
    if not slug:
        return []
    path = _rider_cache_path(slug)
    if os.path.exists(path):
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        if _rider_history_is_fresh(mtime):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else data.get("results", [])
    try:
        soup = fetch(f"{XCODATA_BASE}{slug}")
        tables = soup.find_all("table")
        if len(tables) < 3:
            return []
        results = []
        for row in tables[2].find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            rank_text = cells[0].get_text(strip=True)
            if not rank_text.isdigit():
                continue
            link      = cells[1].find("a", href=True)
            race_id   = ""
            race_name = ""
            if link:
                m = re.search(r"/race/(\d+)/", link["href"])
                race_id   = m.group(1) if m else ""
                race_name = link.get_text(strip=True)
            date_str = location = ""
            date_div = cells[1].find("div", class_="text-nowrap")
            if date_div:
                div_text = date_div.get_text(" ", strip=True)
                m = _DATE_RE.search(div_text)
                if m:
                    date_str = m.group(0).strip()
                    location = div_text[m.end():].strip()
            results.append({
                "race_id":   race_id,
                "race_name": race_name,
                "date":      date_str,
                "location":  location,
                "rank":      int(rank_text),
                "cat":       cells[2].get_text(strip=True),
            })
        country = _country_from_soup(soup)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"country": country, "results": results}, f, ensure_ascii=False)
        time.sleep(0.2)
        return results
    except Exception:
        return []


def fetch_rider_country(slug: str) -> str:
    """Return the cached IOC country code for a rider (empty string if unknown)."""
    if not slug:
        return ""
    path = _rider_cache_path(slug)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("country", "")
    return ""


def _race_page_cache_path(race_id: str) -> str:
    race_dir = os.path.join(CACHE_DIR, "race_pages")
    os.makedirs(race_dir, exist_ok=True)
    return os.path.join(race_dir, f"{race_id}.json")


def fetch_race_page(race_id: str) -> dict:
    """
    Fetch a race results page and return a mapping of rider_slug → rank,
    plus '_name', '_date', '_location' metadata keys.
    Cached with the standard TTL.
    """
    path = _race_page_cache_path(race_id)
    if os.path.exists(path):
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        if _rider_history_is_fresh(mtime):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    try:
        soup = fetch(f"{XCODATA_BASE}/race/{race_id}/")
        result: dict = {}
        for table in soup.find_all("table"):
            for row in table.find_all("tr")[1:]:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                rank_text = cells[0].get_text(strip=True)
                if not rank_text.isdigit():
                    continue
                link = cells[1].find("a", href=True)
                if link:
                    m = re.search(r"(/rider/[^/]+/)", link["href"])
                    if m:
                        result[m.group(1)] = int(rank_text)
        # Metadata from the Info table (last table: location / date / Website)
        title = soup.find("title")
        result["_name"] = title.get_text(strip=True).split(" | ")[0].strip() if title else ""
        all_tables = soup.find_all("table")
        if all_tables:
            info_rows = all_tables[-1].find_all("tr")
            cells_by_row = [[td.get_text(strip=True) for td in r.find_all("td")] for r in info_rows]
            texts = [c[0] for c in cells_by_row if c and c[0] and c[0] != "Website"]
            date_val = next((t for t in texts if _DATE_RE.search(t)), "")
            location = next((t for t in texts if t and not _DATE_RE.search(t)), "")
            result["_date"]     = date_val
            result["_location"] = location
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        time.sleep(0.2)
        return result
    except Exception:
        return {}


def supplement_history_from_race_pages(riders: list) -> None:
    """
    Supplement each rider's race history with results from race pages that were
    found in OTHER riders' profiles but are missing from their own.

    This covers the common xcodata lag where a race page is updated before the
    rider profile pages reflect it.
    """
    # Collect all race IDs known from any rider's profile
    all_known: dict[str, dict] = {}  # race_id → basic info from whoever has it
    for rider in riders:
        for res in rider.race_results:
            rid = res.get("race_id")
            if rid and rid not in all_known:
                all_known[rid] = {
                    "race_name": res.get("race_name", ""),
                    "date":      res.get("date", ""),
                    "location":  res.get("location", ""),
                }

    if not all_known:
        return

    for rider in riders:
        if not rider.xcodata_slug:
            continue
        existing_ids = {r["race_id"] for r in rider.race_results if r.get("race_id")}
        missing_ids  = [rid for rid in all_known if rid not in existing_ids]
        if not missing_ids:
            continue

        new_results = []
        for rid in missing_ids:
            page = fetch_race_page(rid)
            if rider.xcodata_slug in page:
                info = all_known[rid]
                new_results.append({
                    "race_id":   rid,
                    "race_name": page.get("_name") or info["race_name"],
                    "date":      page.get("_date") or info["date"],
                    "location":  page.get("_location") or info["location"],
                    "rank":      page[rider.xcodata_slug],
                    "cat":       "",
                })
        if new_results:
            rider.race_results = new_results + rider.race_results


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
                    slug     = link.get("href", "")
                else:
                    parts    = rider_cell.split(None, 1)
                    name_raw = parts[1] if len(parts) > 1 else rider_cell
                    slug     = ""

                country = _flag_img_to_ioc(cols[2].find("img")) if cols[2].find("img") else ""

                name_normalized = normalize_rider_name(name_raw)
                name_key = name_normalized.lower()
                cache["by_name"][name_key] = {
                    "rank": rank, "points": points, "name": name_normalized,
                    "slug": slug, "country": country,
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


def _strip_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()


def find_xcodata_slug(rider: Rider) -> str:
    """
    For riders not found in the UCI ranking, guess their xcodata slug from name.
    xcodata uses /rider/{first}-{last}/ (diacritics stripped, lowercase).
    Returns the slug if the profile has race results, otherwise "".
    """
    def slugify(s: str) -> str:
        return re.sub(r"\s+", "-", _strip_diacritics(s).lower().strip())

    first = slugify(rider.first_name)
    last  = slugify(rider.last_name)
    if not first or not last:
        return ""

    for slug in [f"/rider/{first}-{last}/", f"/rider/{last}-{first}/"]:
        if fetch_rider_history(slug):
            return slug
    return ""


def lookup_rider(rider: Rider, cache: dict) -> Rider:
    """Looks up UCI rank for a rider. Tries exact name match first, then fuzzy."""
    by_name = cache.get("by_name", {})
    if not by_name:
        return rider

    def _apply(entry: dict, confidence: int):
        rider.uci_rank         = entry["rank"]
        rider.uci_points       = entry["points"]
        rider.xcodata_slug     = entry.get("slug", "")
        rider.match_confidence = confidence
        if not rider.country and entry.get("country"):
            rider.country = entry["country"]

    for key in (
        rider.full_name.lower(),
        f"{rider.last_name} {rider.first_name}".lower(),
        _strip_diacritics(rider.full_name.lower()),
        _strip_diacritics(f"{rider.last_name} {rider.first_name}".lower()),
    ):
        if key in by_name:
            _apply(by_name[key], 100)
            return rider

    all_names = list(by_name.keys())
    if all_names:
        key_ascii = _strip_diacritics(rider.full_name.lower())
        best_match, score = process.extractOne(key_ascii, all_names, scorer=fuzz.token_sort_ratio)
        if score >= 82:
            _apply(by_name[best_match], score)
            entry_name = by_name[best_match]["name"]
            if _strip_diacritics(rider.full_name) != _strip_diacritics(entry_name):
                rider.corrected_name = entry_name
        else:
            rider.uci_rank         = None
            rider.uci_points       = 0
            rider.match_confidence = score

    return rider
