import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from thefuzz import fuzz, process

from .config import (
    CACHE_DIR, CACHE_MAX_AGE_DAYS, DATARIDE_BASE, FLAG, HEADERS, ISO2_TO_IOC, XCODATA_BASE,
    console,
)
from .models import Rider
from .utils import cell_direct_text, fetch, normalize_country, normalize_rider_name


_DATARIDE_DISC_ID      = 7    # MTB
_DATARIDE_XCO_TYPE_ID  = 92   # Cross-country Olympic
_DATARIDE_RANK_TYPE_ID = 1    # Individual ranking
_DATARIDE_CATEGORY_IDS = {"MJ": 24, "WJ": 25, "ME": 22, "WE": 23}
_DATARIDE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Referer": f"{DATARIDE_BASE}/iframe/rankings/7",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}


def cache_path(uci_cat: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    year = datetime.now().year
    return os.path.join(CACHE_DIR, f"ranking_{uci_cat}_{year}.json")




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
_DISC_RE = re.compile(r'\b(XCO|XCC|XCR|XCM)\b', re.IGNORECASE)


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
    """Extract IOC country code from a flag <img> tag (xcodata src or alt text)."""
    src = img.get("src", "").lower()
    m = re.search(r"/([a-z]{2,3})\.(?:png|gif|svg)", src)
    if m:
        code = m.group(1).upper()
        if code in FLAG:
            return code
        if code in ISO2_TO_IOC:
            return ISO2_TO_IOC[code]
    alt = img.get("alt", "").strip()
    if alt.upper() in FLAG:
        return alt.upper()
    if alt:
        normed = normalize_country(alt)
        if normed in FLAG:   # must be a known IOC code, not a fallback abbreviation
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
            disc_m = _DISC_RE.search(race_name)
            results.append({
                "race_id":   race_id,
                "race_name": race_name,
                "date":      date_str,
                "location":  location,
                "rank":      int(rank_text),
                "cat":       cells[2].get_text(strip=True),
                "disc":      disc_m.group(1).upper() if disc_m else "",
            })
        country = _country_from_soup(soup)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"country": country, "results": results}, f, ensure_ascii=False)
        time.sleep(0.2)
        return results
    except Exception:
        return []


def fetch_rider_country(slug: str) -> str:
    """Return the cached IOC country code for a rider (empty string if unknown or invalid)."""
    if not slug:
        return ""
    path = _rider_cache_path(slug)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        country = data.get("country", "")
        return country if country in FLAG else ""
    return ""


def fetch_rider_history_uci(object_id: int, uci_cat: str, cache: dict) -> list:
    """Fetch UCI race result history for a rider from dataride.uci.ch."""
    if not object_id:
        return []
    path = _rider_cache_path(f"uci_{object_id}")
    if os.path.exists(path):
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        if _rider_history_is_fresh(mtime):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    data = {
        "individualId":       object_id,
        "rankingId":          cache.get("ranking_id", 0),
        "momentId":           cache.get("moment_id", 0),
        "groupId":            cache.get("group_id", 0),
        "baseRankingTypeId":  _DATARIDE_RANK_TYPE_ID,
        "disciplineSeasonId": cache.get("season_id", 0),
        "disciplineId":       _DATARIDE_DISC_ID,
        "categoryId":         _DATARIDE_CATEGORY_IDS.get(uci_cat, 0),
        "raceTypeId":         _DATARIDE_XCO_TYPE_ID,
        "countryId": 0, "teamId": 0,
        "take": 200, "skip": 0, "page": 1, "pageSize": 200,
    }
    try:
        r = requests.post(
            f"{DATARIDE_BASE}/iframe/IndividualEventRankings/",
            data=data, headers=_DATARIDE_HEADERS, timeout=20,
        )
        r.raise_for_status()
        items = r.json().get("data", [])
        results = [
            {
                "race_id":   str(item.get("ResultId", "")),
                "race_name": item.get("CompetitionName", ""),
                "date":      item.get("Date", ""),
                "location":  "",
                "rank":      item.get("Rank"),
                "time":      "",
                "cat":       uci_cat,
                "disc":      "XCO",
            }
            for item in items
            if item.get("Rank") is not None
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False)
        time.sleep(0.2)
        return results
    except Exception:
        return []


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
        soup = fetch(f"{XCODATA_BASE}/race/{race_id}", retries=1, timeout=10)
        result: dict = {}

        title = soup.find("title")
        name = title.get_text(strip=True).split(" | ")[0].strip() if title else ""
        result["_name"] = name

        def _process_table(table, disc: str) -> None:
            for row in table.find_all("tr")[1:]:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                rank_text = cells[0].get_text(strip=True)
                if not rank_text.isdigit():
                    continue
                link = cells[1].find("a", href=True)
                if not link:
                    continue
                m = re.search(r"(/rider/[^/]+/)", link["href"])
                if not m:
                    continue
                slug = m.group(1)
                time_val = cell_direct_text(cells[2]).strip() if len(cells) > 2 else ""
                entry = {"rank": int(rank_text), "time": time_val}
                if disc:
                    result[f"{slug}|{disc}"] = entry
                if slug not in result:
                    result[slug] = entry

        # Strategy 1: Bootstrap tab-panes with IDs like "results_XCO_ME".
        # The discipline is explicitly encoded in the pane ID — most reliable.
        panes = soup.find_all("div", class_="tab-pane")
        if panes:
            for pane in panes:
                pane_id = pane.get("id", "").upper()
                # Pane IDs look like "results_XCO_ME" — use substring, not \b
                if "XCC" in pane_id:
                    disc = "xcc"
                elif "XCO" in pane_id:
                    disc = "xco"
                elif "XCR" in pane_id:
                    disc = "xcr"
                else:
                    disc = ""
                for table in pane.find_all("table"):
                    _process_table(table, disc)
        else:
            # Strategy 2: Fallback — walk headings and tables in document order.
            title_disc = _DISC_RE.search(name)
            current_disc = title_disc.group(1).lower() if title_disc else ""
            for elem in soup.find_all(lambda t: t.name in ("h1","h2","h3","h4","h5","table")):
                if elem.name != "table":
                    m = _DISC_RE.search(elem.get_text(strip=True))
                    if m:
                        current_disc = m.group(1).lower()
                else:
                    _process_table(elem, current_disc)
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
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)
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
            page_name = page.get("_name", "")
            disc_m = _DISC_RE.search(page_name)
            disc = disc_m.group(1).lower() if disc_m else ""
            disc_key = f"{rider.xcodata_slug}|{disc}" if disc else ""
            slug_data = (page.get(disc_key) if disc_key else None) or page.get(rider.xcodata_slug)
            if slug_data is not None:
                info = all_known[rid]
                rank = slug_data["rank"] if isinstance(slug_data, dict) else slug_data
                time_val = slug_data.get("time", "") if isinstance(slug_data, dict) else ""
                new_results.append({
                    "race_id":   rid,
                    "race_name": page.get("_name") or info["race_name"],
                    "date":      page.get("_date") or info["date"],
                    "location":  page.get("_location") or info["location"],
                    "rank":      rank,
                    "time":      time_val,
                    "cat":       "",
                    "disc":      disc.upper(),
                })
        if new_results:
            rider.race_results = new_results + rider.race_results


def enrich_times_from_race_pages(riders: list) -> None:
    """
    Backfill 'time' into race results that came from rider profile pages
    (which don't include time) by reading already-cached race pages.
    Makes no network requests — only reads files already on disk.
    """
    for rider in riders:
        if not rider.xcodata_slug:
            continue
        for res in rider.race_results:
            if res.get("time"):
                continue
            rid = res.get("race_id")
            if not rid:
                continue
            path = _race_page_cache_path(rid)
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    page = json.load(f)
                disc = res.get("disc", "").lower()
                disc_key = f"{rider.xcodata_slug}|{disc}" if disc else ""
                slug_data = (page.get(disc_key) if disc_key else None) or page.get(rider.xcodata_slug)
                if isinstance(slug_data, dict):
                    res["time"] = slug_data.get("time", "")
            except Exception:
                pass


def _parse_dataride_name(display_name: str) -> str:
    """Convert 'LASTNAME Firstname' (dataride.uci.ch format) to 'Firstname Lastname' title case."""
    parts = display_name.split()
    i = next(
        (j for j, p in enumerate(parts) if p != p.upper() or not any(c.isalpha() for c in p)),
        len(parts),
    )
    if i == 0 or i == len(parts):
        return display_name.title()
    lastname  = " ".join(p.title() for p in parts[:i])
    firstname = " ".join(parts[i:])
    return f"{firstname} {lastname}"


def _dataride_get_ranking_params(uci_cat: str) -> tuple:
    """Return (season_id, ranking_id, moment_id) for the given UCI category."""
    year = datetime.now().year
    r = requests.get(
        f"{DATARIDE_BASE}/iframe/GetDisciplineSeasons/",
        params={"disciplineId": _DATARIDE_DISC_ID},
        headers=_DATARIDE_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    seasons = r.json()
    season_id = next((s["Id"] for s in seasons if s["Year"] == year), None)
    if not season_id:
        raise RuntimeError(f"No dataride season found for year {year}")

    cat_id = _DATARIDE_CATEGORY_IDS[uci_cat]
    data = {
        "disciplineId": _DATARIDE_DISC_ID,
        "take": 10, "skip": 0, "page": 1, "pageSize": 10,
        "filter[logic]": "and",
        "filter[filters][0][field]": "RaceTypeId",
        "filter[filters][0][value]": _DATARIDE_XCO_TYPE_ID,
        "filter[filters][1][field]": "CategoryId",
        "filter[filters][1][value]": cat_id,
        "filter[filters][2][field]": "SeasonId",
        "filter[filters][2][value]": season_id,
    }
    r = requests.post(
        f"{DATARIDE_BASE}/iframe/RankingsDiscipline/",
        data=data,
        headers=_DATARIDE_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    result = r.json()
    ranking = result[0]["Rankings"][0]
    return season_id, ranking["Id"], ranking["MomentId"], result[0]["GroupId"]


def _dataride_fetch_all_riders(season_id: int, ranking_id: int, moment_id: int,
                                cat_id: int) -> list:
    """Fetch the complete paginated rider list from dataride.uci.ch."""
    riders: list = []
    skip = 0
    page_size = 100
    while True:
        data = {
            "rankingId": ranking_id,
            "disciplineId": _DATARIDE_DISC_ID,
            "rankingTypeId": _DATARIDE_RANK_TYPE_ID,
            "take": page_size,
            "skip": skip,
            "page": (skip // page_size) + 1,
            "pageSize": page_size,
            "filter[logic]": "and",
            "filter[filters][0][field]": "RaceTypeId",
            "filter[filters][0][value]": _DATARIDE_XCO_TYPE_ID,
            "filter[filters][1][field]": "CategoryId",
            "filter[filters][1][value]": cat_id,
            "filter[filters][2][field]": "SeasonId",
            "filter[filters][2][value]": season_id,
            "filter[filters][3][field]": "MomentId",
            "filter[filters][3][value]": moment_id,
            "filter[filters][4][field]": "CountryId",
            "filter[filters][4][value]": 0,
            "filter[filters][5][field]": "IndividualName",
            "filter[filters][5][value]": "",
            "filter[filters][6][field]": "TeamName",
            "filter[filters][6][value]": "",
        }
        r = requests.post(
            f"{DATARIDE_BASE}/iframe/ObjectRankings/",
            data=data,
            headers=_DATARIDE_HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        result = r.json()
        total = result.get("total", 0)
        items = result.get("data", [])
        riders.extend(items)
        skip += len(items)
        if skip >= total or not items:
            break
        time.sleep(0.2)
    return riders


def build_uci_cache(uci_cat: str) -> dict:
    """Downloads the full UCI XCO ranking from dataride.uci.ch and saves to cache."""
    console.print(f"\n[cyan]Downloading UCI ranking ({uci_cat}) from dataride.uci.ch...[/cyan]")
    cat_id = _DATARIDE_CATEGORY_IDS.get(uci_cat)
    if not cat_id:
        console.print(f"[yellow]Unknown UCI category: {uci_cat}[/yellow]")
        return load_cache(uci_cat)

    try:
        season_id, ranking_id, moment_id, group_id = _dataride_get_ranking_params(uci_cat)
        raw_riders = _dataride_fetch_all_riders(season_id, ranking_id, moment_id, cat_id)
    except Exception as e:
        console.print(f"[yellow]Failed to fetch UCI ranking ({uci_cat}): {e}[/yellow]")
        return load_cache(uci_cat)

    by_name: dict = {}
    for item in raw_riders:
        name = _parse_dataride_name(item.get("DisplayName", ""))
        if not name:
            continue
        country = item.get("NationName", "").strip()
        by_name[name.lower()] = {
            "rank":      item["Rank"],
            "points":    item.get("Points", 0),
            "name":      name,
            "slug":      "",
            "country":   country,
            "object_id": item.get("ObjectId", 0),
        }

    if not by_name:
        console.print(f"[yellow]No riders found for {uci_cat}, keeping existing cache[/yellow]")
        return load_cache(uci_cat)

    cache = {
        "by_name":      by_name,
        "by_id":        {},
        "fetched_at":   datetime.now().isoformat(),
        "ranking_date": datetime.now().strftime("%Y-%m-%d"),
        "ranking_id":   ranking_id,
        "moment_id":    moment_id,
        "group_id":     group_id,
        "season_id":    season_id,
    }
    save_cache(uci_cat, cache)
    console.print(f"[green]✓ Loaded {len(by_name)} riders ({uci_cat})[/green]")
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
        rider.uci_object_id    = entry.get("object_id", 0)
        rider.match_confidence = confidence
        if not rider.country and entry.get("country"):
            rider.country = entry["country"]
        # Use the UCI canonical name (title-case, correct diacritics) as the
        # display name whenever it differs from what the start list provided.
        canonical = entry.get("name", "")
        if canonical and rider.full_name != canonical:
            rider.corrected_name = canonical

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
        else:
            rider.uci_rank         = None
            rider.uci_points       = 0
            rider.match_confidence = score

    return rider


# Czech Cup XCO (cpxcmtb.sportsoft.cz) category IDs used in the standings form
_CP_XCO_CATEGORY_IDS: dict[str, str] = {
    "MJ": "7",   # Junioři  (17–18)
    "WJ": "8",   # Juniorky (17–18)
    "ME": "9",   # Muži Elita / Pod 23
    "WE": "10",  # Ženy
}


def _cp_xco_cache_path(standings_url: str, category_id: str) -> str:
    m = re.search(r"/(\d{4})/", standings_url)
    year = m.group(1) if m else "unknown"
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"cp_xco_{year}_{category_id}.json")


def fetch_cp_xco_standings(standings_url: str, uci_cat: str) -> dict:
    """
    Fetches Czech Cup XCO standings for a UCI category from cpxcmtb.sportsoft.cz.

    The site is ASP.NET WebForms: a GET retrieves the ViewState, then a POST
    selects the desired category.  Points per race are summed; '---' means 0.

    Returns {ascii_full_name: total_points} keyed by diacritic-stripped lowercase
    'firstname lastname' so callers can do a direct dict lookup.
    """
    category_id = _CP_XCO_CATEGORY_IDS.get(uci_cat)
    if not category_id:
        return {}

    cache_file = _cp_xco_cache_path(standings_url, category_id)
    if os.path.exists(cache_file):
        mtime = datetime.fromtimestamp(os.path.getmtime(cache_file))
        if _rider_history_is_fresh(mtime):
            with open(cache_file, encoding="utf-8") as f:
                return json.load(f)

    try:
        resp = requests.get(standings_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        def _field(name: str) -> str:
            tag = soup.find("input", {"name": name})
            return tag["value"] if tag else ""

        resp2 = requests.post(
            standings_url,
            headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "__EVENTTARGET":        "",
                "__EVENTARGUMENT":      "",
                "__VIEWSTATE":          _field("__VIEWSTATE"),
                "__VIEWSTATEGENERATOR": _field("__VIEWSTATEGENERATOR"),
                "__EVENTVALIDATION":    _field("__EVENTVALIDATION"),
                "ctl00$ContentPlaceHolder1$Kategorie":    category_id,
                "ctl00$ContentPlaceHolder1$BtnKategorie": "Zobrazit",
            },
            timeout=20,
        )
        resp2.raise_for_status()
        soup2 = BeautifulSoup(resp2.text, "html.parser")

        tables = soup2.find_all("table")
        if not tables:
            return {}

        result: dict[str, int] = {}
        for row in tables[0].find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 7:
                continue
            rank_text = cells[0].get_text(strip=True).rstrip(".")
            if not rank_text.isdigit():
                continue

            name_raw = cells[1].get_text(strip=True)
            normalized = normalize_rider_name(name_raw)
            key = _strip_diacritics(normalized.lower())

            total = sum(
                int(c.get_text(strip=True))
                for c in cells[6:]
                if c.get_text(strip=True).isdigit()
            )
            result[key] = total

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        return result

    except Exception as e:
        console.print(f"[yellow]Could not fetch CP XCO standings: {e}[/yellow]")
        return {}


def enrich_cp_xco_points(riders: list, standings: dict) -> None:
    """Assign cp_xco_points from Czech Cup standings to unranked riders."""
    for rider in riders:
        if rider.uci_rank is not None:
            continue
        key = _strip_diacritics(rider.full_name.lower())
        if key in standings:
            rider.cp_xco_points = standings[key]
            continue
        # Try reversed order (start list may have last–first vs first–last)
        key_rev = _strip_diacritics(f"{rider.last_name} {rider.first_name}".lower())
        rider.cp_xco_points = standings.get(key_rev, 0)
