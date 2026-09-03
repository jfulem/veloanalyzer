"""UCI ranking, race history and points estimation.

Discipline-aware: every entry point takes a `discipline` code from
mtb_analyzer.discipline (default XCO, so pre-existing callers are unchanged).
The "xco" in identifiers here is historical and now reads as "UCI competition
result" for whichever discipline was passed — see discipline.py.
"""

import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup
from thefuzz import fuzz, process

from .config import (
    CACHE_DIR, CACHE_MAX_AGE_DAYS, DATARIDE_BASE, FLAG, HEADERS, ISO2_TO_IOC, XCODATA_BASE,
    console,
)
from .discipline import CX, DEFAULT_DISCIPLINE, XCO
from .discipline import get as get_discipline
from .models import Rider
from .utils import cell_direct_text, fetch, normalize_country, normalize_rider_name


_DATARIDE_RANK_TYPE_ID = 1    # Individual ranking
# Same four IDs in every discipline — dataride's category table is global.
_DATARIDE_CATEGORY_IDS = {"MJ": 24, "WJ": 25, "ME": 22, "WE": 23}
_DATARIDE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Referer": f"{DATARIDE_BASE}/iframe/rankings/7",  # overridden per discipline
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

# UCI public website API (https://www.uci.org/api/...)
_UCI_BASE = "https://www.uci.org"
_UCI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
_UCI_CATEGORY_LABELS = {"MJ": "Men Junior", "WJ": "Women Junior", "ME": "Men Elite", "WE": "Women Elite"}

# U23 has no standalone official UCI ranking — U23-eligible riders are
# officially ranked (and their UCI-published results recorded) under Elite.
# "MU23"/"WU23" remain valid uci_category values everywhere else (start-list
# filtering, display, races.yml) since many start lists do register U23 as
# its own field, distinct from Elite. Only official-UCI-data lookups
# (ranking cache, race history, competition results) resolve through here.
_RANKING_CATEGORY_ALIAS = {"MU23": "ME", "WU23": "WE"}

# Cyclo-cross adds junior women to that list. Art. C1025 gives the discipline
# only three individual rankings — men elite + U23, women elite + U23 +
# *juniors*, and men juniors — and art. C0922 C confirms that a junior women's
# race is gridded on the women's ranking. The standalone Women Junior ranking
# dataride also publishes is not what decides where they line up, so it is not
# what this project reads.
_CX_RANKING_CATEGORY_ALIAS = {"MU23": "ME", "WU23": "WE", "WJ": "WE"}


def _ranking_category(uci_cat: str, discipline: str = DEFAULT_DISCIPLINE) -> str:
    if get_discipline(discipline).code == CX:
        return _CX_RANKING_CATEGORY_ALIAS.get(uci_cat, uci_cat)
    return _RANKING_CATEGORY_ALIAS.get(uci_cat, uci_cat)


# The categories the UCI publishes a standalone individual ranking for. Both
# disciplines start from the same four; _ranking_category then folds away any
# that are not their own ranking, which in cyclo-cross means junior women.
_RANKING_CATEGORIES = ("ME", "WE", "MJ", "WJ")


def ranking_category(uci_cat: str, discipline: str = DEFAULT_DISCIPLINE) -> str:
    """Public name for the alias map: which UCI ranking actually covers a
    start-list category. MU23 → ME everywhere; WJ → WE in cyclo-cross."""
    return _ranking_category(uci_cat, discipline)


def ranking_categories(discipline: str = DEFAULT_DISCIPLINE) -> tuple:
    """Distinct rankings to download and store for a discipline.

    Deduplicated *after* aliasing: in cyclo-cross WJ resolves to WE, so
    iterating the raw four would fetch the women's ranking twice and store the
    second copy under the wrong uci_cat — silently relabelling every woman a
    junior, since the two rows collide on (rider_id, discipline).
    """
    seen: list = []
    for uci_cat in _RANKING_CATEGORIES:
        resolved = _ranking_category(uci_cat, discipline)
        if resolved not in seen:
            seen.append(resolved)
    return tuple(seen)


def _event_categories(uci_cat: str, discipline: str = DEFAULT_DISCIPLINE) -> tuple:
    """UCI event categories to try, most specific first.

    Cyclo-cross junior women are the reason this is a list rather than a single
    value: a national championship or World Cup round runs them as their own
    event ("Women Junior"), while a class 1 or 2 cup round starts them with the
    women and U23 and publishes one combined classification. Both are their
    official result, so the exact event wins where it exists and the combined
    one stands in where it does not.
    """
    if get_discipline(discipline).code == CX and uci_cat == "WJ":
        return ("WJ", "WE")
    return (_ranking_category(uci_cat, discipline),)


def _event_code_for(details: dict, uci_cat: str,
                    discipline: str = DEFAULT_DISCIPLINE) -> str:
    """First event code among _event_categories, or "" when none is published."""
    events = details.get("events", {}) if details else {}
    for cat in _event_categories(uci_cat, discipline):
        code = events.get(cat)
        if code:
            return code
    return ""


def _disc_prefix(discipline: str) -> str:
    """Filename prefix for a discipline. XCO gets none, so the cache files
    written before cyclo-cross existed stay valid."""
    return "" if discipline == XCO else f"{discipline.lower()}_"


def cache_path(uci_cat: str, discipline: str = DEFAULT_DISCIPLINE) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    disc = get_discipline(discipline)
    year = disc.season_year()
    return os.path.join(
        CACHE_DIR, f"ranking_{_disc_prefix(disc.code)}{uci_cat}_{year}.json"
    )


def cache_is_fresh(uci_cat: str, discipline: str = DEFAULT_DISCIPLINE) -> bool:
    path = cache_path(uci_cat, discipline)
    if not os.path.exists(path):
        return False
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    return datetime.now() - mtime < timedelta(days=CACHE_MAX_AGE_DAYS)


def load_cache(uci_cat: str, discipline: str = DEFAULT_DISCIPLINE) -> dict:
    path = cache_path(uci_cat, discipline)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(uci_cat: str, data: dict, discipline: str = DEFAULT_DISCIPLINE):
    with open(cache_path(uci_cat, discipline), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_DATE_RE = re.compile(r'\d{2}(?:\s*-\s*\d{2})?\s+\w{3}\s+\d{4}')
_DISC_RE = re.compile(r'\b(XCO|XCC|XCR|XCM)\b', re.IGNORECASE)


# Letters NFD cannot decompose, because they are distinct letters rather than a
# base plus a combining mark. Without folding these by hand "Wojtyła" never
# meets "WOJTYLA" — the ł survives every normalisation and the names never match.
_LETTER_FOLD = str.maketrans({
    "ł": "l",  "Ł": "L",
    "ø": "o",  "Ø": "O",
    "đ": "d",  "Đ": "D",
    "ð": "d",  "Ð": "D",
    "æ": "ae", "Æ": "Ae",
    "œ": "oe", "Œ": "Oe",
    "þ": "th", "Þ": "Th",
    "ß": "ss",
    "ı": "i",  "İ": "I",
})


def _strip_diacritics(s: str) -> str:
    """Fold accents, special letters and case into a comparable ASCII form."""
    return "".join(c for c in unicodedata.normalize("NFD", s.translate(_LETTER_FOLD))
                   if unicodedata.category(c) != "Mn").lower()


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
            fetch(f"{XCODATA_BASE}{slug}", retries=1, timeout=5)
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


def _uci_catalog_cache_path(year: int, discipline: str = DEFAULT_DISCIPLINE) -> str:
    return os.path.join(
        CACHE_DIR, f"uci_calendar_{_disc_prefix(discipline)}{year}.json"
    )


def _uci_comp_dir(discipline: str = DEFAULT_DISCIPLINE) -> str:
    # Competition IDs are unique across disciplines, but the cached payload
    # (event codes per category) is fetched from a discipline-specific URL, so
    # the directories stay separate rather than risking a cross-discipline hit.
    suffix = "" if discipline == XCO else f"_{discipline.lower()}"
    d = os.path.join(CACHE_DIR, f"uci_comps{suffix}")
    os.makedirs(d, exist_ok=True)
    return d


def _uci_event_dir() -> str:
    # Event codes ("D2EV361123") are globally unique and the results endpoint
    # ignores its own discipline parameter, so one directory serves both.
    d = os.path.join(CACHE_DIR, "uci_events")
    os.makedirs(d, exist_ok=True)
    return d


def _parse_comp_end_date(dates_str: str) -> "datetime | None":
    """Parse the end date from a UCI competition dates string.
    Handles '13 Jun 2026' and '12 Jun - 13 Jun 2026' formats."""
    last = dates_str.split(" - ")[-1].strip()
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(last, fmt)
        except ValueError:
            pass
    return None


# {discipline: {uci_cat: {name_key: [race_result, ...]}}}
_uci_xco_history_cache: dict = {}
# Parallel cache: {discipline: {uci_cat: {xco_race_id: [finisher_row, ...]}}}
# A finisher_row has: comp_name, date_raw, date, race_class, rank, first_name,
# last_name, nationality, race_time, uci_pts.
_uci_xco_race_results_cache: dict = {}


def ranking_window_start(when: "datetime | None" = None, months_back: int = 12) -> datetime:
    """Start of the rolling window a result still scores in.

    Whole calendar months, not months x 30 days: the UCI drops a result on its
    anniversary (art. 4.16.008 for MTB, C1026 for cyclo-cross), and 12 x 30 is
    360 days, so the approximation expired results five days early and
    disagreed with the same window applied in the browser.

    Mirrored by rankingWindowStart() in frontend/src/utils.ts — the database
    keeps results for longer than they score, so both sides have to agree on
    where scoring stops.
    """
    when = when or datetime.now()
    year, month = when.year, when.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    day = when.day
    # 29 Feb has no anniversary in a common year; step back to the 28th rather
    # than overflowing into March.
    while True:
        try:
            return when.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def get_uci_xco_race_results_cache() -> dict:
    """Return the race-level finisher data collected by build_uci_xco_history.

    Shaped {discipline: {uci_cat: {xco_race_id: [finisher_row, ...]}}}. Only
    populated for the discipline/category pairs built during the current
    process lifetime.
    """
    return _uci_xco_race_results_cache


def build_uci_xco_history(uci_cat: str, months_back: int = 12,
                          discipline: str = DEFAULT_DISCIPLINE) -> dict:
    """
    Return {name_key: [race_result, ...]} for every UCI competition in this
    discipline in the past months_back months.  Includes ALL finishers with
    finish times (not just point-scorers like IndividualEventRankings).

    name_key is 'firstname lastname' lowercased.  Results are cached in memory
    for the duration of the process so multiple races of the same category
    only trigger one build.
    """
    disc = get_discipline(discipline)
    # In cyclo-cross this folds WJ into WE: junior women share the women's
    # ranking and, at every class 1/2 round, the women's race itself. Their own
    # event at a championship is picked up per-race by
    # supplement_from_uci_competition instead of widening the whole sweep.
    uci_cat = _ranking_category(uci_cat, disc.code)
    cached = _uci_xco_history_cache.get(disc.code, {}).get(uci_cat)
    if cached is not None:
        return cached

    # Deliberate deviation: the UCI computes the junior ranking over a calendar
    # year, not a rolling window. We use the rolling window for every category,
    # so junior point totals here are an estimate of form over the last 12
    # months rather than a reproduction of the official junior standings —
    # which is the more useful number for comparing start lists mid-season.
    now    = datetime.now()
    cutoff = ranking_window_start(now, months_back)
    by_name: dict = {}
    race_results_by_id: dict = {}  # {xco_race_id: [finisher_row, ...]}
    seen_comp_ids: set = set()

    # Season labels, not calendar years: a cyclo-cross season runs Aug → Feb
    # and the UCI files the whole span under the later year, so a 12-month
    # window can straddle two of them.
    for year in sorted({disc.season_year(cutoff), disc.season_year(now)}):
        catalog = _get_uci_competition_catalog(year, disc.code)
        for comp_id, entry in catalog.get("by_id", {}).items():
            if comp_id in seen_comp_ids:
                continue
            seen_comp_ids.add(comp_id)
            end_dt = _parse_comp_end_date(entry.get("dates", ""))
            if end_dt is None or end_dt < cutoff or end_dt > now:
                continue

            details = _get_competition_details(comp_id, year, disc.code)
            event_code = details.get("events", {}).get(uci_cat)
            if not event_code:
                continue
            race_class = details.get("class", "")

            event_results = _get_uci_event_results(event_code)
            if not event_results:
                continue

            comp_name  = entry.get("name", "")
            dates_str  = entry.get("dates", "")
            race_date  = dates_str.split(" - ")[-1].strip() if " - " in dates_str else dates_str
            xco_race_id = f"{race_date}|{comp_name}"

            race_finishers: list = []
            for er in event_results:
                fn = er.get("first_name", "").strip()
                ln = er.get("last_name",  "").strip()
                if not fn or not ln:
                    continue

                pts_raw = er.get("points", "")
                rank = int(er["rank"]) if er.get("rank") and str(er["rank"]).isdigit() else None
                uci_pts = int(pts_raw) if str(pts_raw).isdigit() else None
                result = {
                    "race_id":     xco_race_id,
                    "race_name":   comp_name,
                    "date":        race_date,
                    "location":    entry.get("venue", ""),
                    "rank":        rank,
                    "time":        er.get("time", ""),
                    "uci_pts":     uci_pts,
                    "nationality": er.get("nationality", ""),
                    "cat":         uci_cat,
                    "race_class":  race_class,
                    "disc":        disc.code,
                }
                key = f"{fn} {ln}".lower()
                by_name.setdefault(key, []).append(result)
                # Also index without diacritics so start-list spellings always match
                stripped = f"{_strip_diacritics(fn)} {_strip_diacritics(ln)}".lower()
                if stripped != key:
                    by_name.setdefault(stripped, []).append(result)

                race_finishers.append({
                    "comp_name":   comp_name,
                    "date_raw":    race_date,
                    "race_class":  race_class,
                    "rank":        rank,
                    "first_name":  fn,
                    "last_name":   ln,
                    "nationality": er.get("nationality", ""),
                    "race_time":   er.get("time", ""),
                    "uci_pts":     uci_pts,
                    "venue":       entry.get("venue", ""),
                    "country":     entry.get("country", ""),
                })

            if race_finishers:
                race_results_by_id[xco_race_id] = race_finishers

    _uci_xco_history_cache.setdefault(disc.code, {})[uci_cat] = by_name
    _uci_xco_race_results_cache.setdefault(disc.code, {})[uci_cat] = race_results_by_id
    return by_name


# Riders' own UCI ranking categories only — U23 riders already appear in the
# Elite results (the UCI has no standalone U23 XCO ranking), so sweeping
# MU23/WU23 separately would just re-fetch the same event codes for nothing.
_ARCHIVE_CATEGORIES = ("ME", "WE", "MJ", "WJ")


def build_uci_xco_country_archive(countries: list, years_back: int = 2,
                                  discipline: str = DEFAULT_DISCIPLINE) -> None:
    """
    Broaden the UCI XCO results archive with competitions from `countries`
    going back `years_back` years — beyond build_uci_xco_history's normal
    rolling-12-month / races.yml-categories-only scope, which exists to
    support rider history and points, not to be a general archive.

    Merges directly into the same in-process cache build_uci_xco_history
    populates (get_uci_xco_race_results_cache()), so callers persist the
    result the same way as always: save_uci_race_results(get_uci_xco_...()).
    Must run after build_uci_xco_history has been called for every races.yml
    category in this process (i.e. after the main races.yml scrape loop),
    or a later build_uci_xco_history call would overwrite what this adds.

    countries are races.yml discovery_countries: full English names like
    "Czech Republic", normalized to IOC codes via normalize_country().
    """
    disc = get_discipline(discipline)
    country_codes = {normalize_country(c) for c in countries}
    now    = datetime.now()
    cutoff = now - timedelta(days=years_back * 365)

    for year in range(disc.season_year(cutoff), disc.season_year(now) + 1):
        catalog = _get_uci_competition_catalog(year, disc.code)
        for comp_id, entry in catalog.get("by_id", {}).items():
            if entry.get("country") not in country_codes:
                continue
            end_dt = _parse_comp_end_date(entry.get("dates", ""))
            if end_dt is None or end_dt < cutoff or end_dt > now:
                continue

            comp_name   = entry.get("name", "")
            dates_str   = entry.get("dates", "")
            race_date   = dates_str.split(" - ")[-1].strip() if " - " in dates_str else dates_str
            xco_race_id = f"{race_date}|{comp_name}"

            details    = _get_competition_details(comp_id, year, disc.code)
            race_class = details.get("class", "")

            for uci_cat in _ARCHIVE_CATEGORIES:
                event_code = details.get("events", {}).get(uci_cat)
                if not event_code:
                    continue
                by_id = _uci_xco_race_results_cache.setdefault(
                    disc.code, {}).setdefault(uci_cat, {})
                if xco_race_id in by_id:
                    continue  # already collected by build_uci_xco_history

                event_results = _get_uci_event_results(event_code)
                if not event_results:
                    continue

                finishers = []
                for er in event_results:
                    fn = er.get("first_name", "").strip()
                    ln = er.get("last_name", "").strip()
                    if not fn or not ln:
                        continue
                    pts_raw = er.get("points", "")
                    finishers.append({
                        "comp_name":   comp_name,
                        "date_raw":    race_date,
                        "race_class":  race_class,
                        "rank":        int(er["rank"]) if er.get("rank") and str(er["rank"]).isdigit() else None,
                        "first_name":  fn,
                        "last_name":   ln,
                        "nationality": er.get("nationality", ""),
                        "race_time":   er.get("time", ""),
                        "uci_pts":     int(pts_raw) if str(pts_raw).isdigit() else None,
                        "venue":       entry.get("venue", ""),
                        "country":     entry.get("country", ""),
                    })

                if finishers:
                    by_id[xco_race_id] = finishers


def counting_result_ids(race_results: list, uci_cat: str,
                        discipline: str = DEFAULT_DISCIPLINE) -> set:
    """
    Which results actually contribute to a rider's ranking total, per art.
    4.16.008. Quotas apply *per bucket*, not to the field as a whole:

      HC / Continental Series / class 1 / 2 / 3 : best 5 each
      stage races (SHC, S1, S2)                 : best 3 combined
      XCO juniors series                        : best 4
      XCO juniors                               : best 4
      everything else                           : uncapped

    Cyclo-cross (art. C1029) instead counts everything for every category
    except the men's juniors, who get their best 6 class 1/2 results.

    Uncapped covers World Championships, World Cup rounds and Continental
    Championships. National Championships are uncapped too — a rider only
    starts their own, so the "one result" limit is self-enforcing.

    Returns the identity of each counting result as (race_id, uci_pts), which
    is what callers can match rows on.
    """
    buckets: dict = {}
    uncapped = set()
    for r in race_results:
        pts = r.get("uci_pts")
        if not pts:
            continue
        ident = (r.get("race_id", ""), pts)
        bucket = _points_bucket(uci_cat, r.get("race_class", ""),
                                r.get("race_name", ""), discipline)
        if bucket is None:
            uncapped.add(ident)
        else:
            buckets.setdefault(bucket, []).append((pts, ident))

    counting = set(uncapped)
    for bucket, entries in buckets.items():
        entries.sort(key=lambda e: e[0], reverse=True)
        for _, ident in entries[: _bucket_quota(bucket)]:
            counting.add(ident)
    return counting


def compute_points_from_history(race_results: list, uci_cat: str,
                                discipline: str = DEFAULT_DISCIPLINE) -> int:
    """
    Approximate a rider's current UCI ranking points total from their race
    history, applying the per-class quotas of art. 4.16.008. race_results is
    expected to already be limited to the relevant window, as returned by
    build_uci_xco_history.

    Junior totals are computed over the same rolling 12 months as everyone
    else, where the UCI uses a calendar year — see build_uci_xco_history. They
    are therefore a form estimate, not the official junior standing.
    """
    uci_cat = _ranking_category(uci_cat, discipline)
    counting = counting_result_ids(race_results, uci_cat, discipline)
    return sum(
        r["uci_pts"] for r in race_results
        if r.get("uci_pts") and (r.get("race_id", ""), r["uci_pts"]) in counting
    )


def _lookup_rider_history(history_db: dict, first_name: str, last_name: str) -> list:
    """Find a rider's results in the UCI XCO history database.
    Tries name in both orders, with and without diacritics."""
    fn = first_name.strip()
    ln = last_name.strip()
    sfn = _strip_diacritics(fn)
    sln = _strip_diacritics(ln)
    for key in (
        f"{fn} {ln}".lower(),
        f"{ln} {fn}".lower(),
        f"{sfn} {sln}".lower(),
        f"{sln} {sfn}".lower(),
    ):
        results = history_db.get(key)
        if results:
            return list(results)
    return []


def _parse_year_month(date_str: str) -> tuple:
    """Extract (year, month_int) from strings like '08 May 2026' or '08 May - 10 May 2026'."""
    _months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
               "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
    m = re.search(r'([A-Za-z]{3})\w*\s+(\d{4})', date_str)
    if not m:
        return (0, 0)
    return (int(m.group(2)), _months.get(m.group(1).lower(), 0))


def _get_uci_competition_catalog(year: int, discipline: str = DEFAULT_DISCIPLINE) -> dict:
    """
    `year` is the UCI's season label, not necessarily a calendar year: a
    cyclo-cross "2027" runs from August 2026 to February 2027. Use
    Discipline.season_year() to derive it from a date.

    Returns:
      {
        "by_id":   {comp_id: {"name": str, "year": int, "dates": str}},
        "by_name": {name_lower: [comp_id, ...]},   ← multiple rounds same name
      }
    Fetched from the UCI calendar API and cached weekly.
    """
    disc = get_discipline(discipline)
    path = _uci_catalog_cache_path(year, disc.code)
    if os.path.exists(path):
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        if datetime.now() - mtime < timedelta(days=7):
            with open(path, encoding="utf-8") as f:
                return json.load(f)

    by_id: dict = {}
    by_name: dict = {}
    seen: set = set()

    params = {"discipline": disc.calendar_discipline, "year": year}
    if disc.calendar_race_type:
        params["raceType"] = disc.calendar_race_type
    for endpoint in ("past", "upcoming"):
        try:
            r = requests.get(
                f"{_UCI_BASE}/api/calendar/{endpoint}",
                params=params,
                headers=_UCI_HEADERS,
                timeout=20,
            )
            r.raise_for_status()
            for month_group in r.json().get("items", []):
                for day_group in month_group.get("items", []):
                    for comp in day_group.get("items", []):
                        name = comp.get("name", "")
                        url = comp.get("detailsLink", {}).get("url", "")
                        m = re.search(r"/competition-details/(\d+)/\w+/(\d+)", url)
                        if not m or not name:
                            continue
                        comp_id = m.group(2)
                        if comp_id in seen:
                            continue
                        seen.add(comp_id)
                        comp_year = int(m.group(1))
                        by_id[comp_id] = {
                            "name": name,
                            "year": comp_year,
                            "dates": comp.get("dates", ""),
                            "venue": comp.get("venue", ""),
                            "country": comp.get("country", ""),
                        }
                        by_name.setdefault(name.lower(), [])
                        if comp_id not in by_name[name.lower()]:
                            by_name[name.lower()].append(comp_id)
        except Exception:
            pass

    catalog = {"by_id": by_id, "by_name": by_name}
    if by_id:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(catalog, f, ensure_ascii=False)
    return catalog


def _parse_competition_class(props: dict) -> str:
    """Pull the class code out of a competition-details payload.

    The UCI writes it as '2 - Class 2', 'CN - National Championships',
    'CS - Continental Series' — the code is the token before the dash.
    """
    blob = json.dumps(props, ensure_ascii=False)
    m = re.search(r'"(?:competitionClass|raceClass)"\s*:\s*"([^"]+)"', blob)
    if not m:
        return ""
    return m.group(1).split(" - ")[0].strip().upper()


# MTB XCO, art. 4.16.008: how many results count, per class. Anything absent
# from this map counts without limit — World Championships, World Cup rounds
# and Continental Championships have no cap, and a National Championship is
# effectively self-limiting since a rider only starts their own.
_CLASS_QUOTA = {
    "HC": 5,   # class HC one-day events
    "CS": 5,   # Continental Series one-day events
    "1":  5,   # class 1
    "2":  5,   # class 2
    "3":  5,   # class 3
}
# Stage races share a single quota "regardless the class".
_STAGE_CLASSES = frozenset({"SHC", "S1", "S2"})
_STAGE_QUOTA = 3
# Juniors are ranked on their own two buckets rather than per class.
_JUNIOR_SERIES_QUOTA = 4
_JUNIOR_QUOTA = 4

# Cyclo-cross, art. C1029 (UCI 5.1.049): "for every category except juniors,
# all results are taken into account". Only the men's junior ranking is
# capped, and on two buckets:
#   - junior race at a class 1 or class 2 event : best 6
#   - junior UCI World Cup round               : best 5
# Junior women are not capped here because the regulations rank them inside
# the women's classification (art. C1025), where nothing is capped — the
# separate Women Junior ranking dataride publishes is a display of the same
# uncapped points.
_CX_JUNIOR_QUOTA    = 6
_CX_JUNIOR_WC_QUOTA = 5
# The cyclo-cross calendar writes class codes with the letter ("C1", "C2"),
# unlike MTB's bare "1"/"2" — worth remembering when reading _CLASS_QUOTA.


def _is_junior_series(race_name: str) -> bool:
    """The UCI Junior Series is not a class code — it is appended to the
    competition name ('VTT Chabrières + UCI XCO Junior Series')."""
    return "junior series" in (race_name or "").lower()


def _points_bucket(uci_cat: str, race_class: str, race_name: str,
                   discipline: str = DEFAULT_DISCIPLINE) -> "str | None":
    """Which quota bucket a result falls into, or None when it is uncapped."""
    disc = get_discipline(discipline)
    cls = (race_class or "").upper()

    if disc.code == CX:
        # Tested before the uncapped-class check, unlike XCO below: in
        # cyclo-cross the junior World Cup is itself capped (best 5), so
        # letting CDM short-circuit to "uncapped" would be wrong.
        if _ranking_category(uci_cat, disc.code) != "MJ":
            # Every other category counts every result — see _CX_JUNIOR_QUOTA.
            return None
        if cls == "CDM":
            return "CXJWC"
        if cls in disc.uncapped_classes:
            return None
        # Class 1 and class 2 share one best-6 bucket. An unclassified junior
        # round falls here too: it is far likelier to be a domestic C1/C2 than
        # an unlabelled World Cup, which the CDM branch already caught.
        return "CXJ"

    # Checked before the junior split: World Cups and championships are
    # uncapped for juniors too, and putting the junior branch first would have
    # swept a junior's World Cup results into their best-4 quota.
    if cls in disc.uncapped_classes:
        return None
    if cls in _STAGE_CLASSES:
        return "STAGE"
    if _ranking_category(uci_cat, disc.code) in ("MJ", "WJ"):
        # Junior ranking has two capped buckets and no per-class split. An
        # unclassified event still belongs in one of them — several Junior
        # Series rounds carry no class code at all.
        return "JS" if _is_junior_series(race_name) else "J"
    return cls if cls in _CLASS_QUOTA else None


def _bucket_quota(bucket: str) -> int:
    if bucket == "STAGE":
        return _STAGE_QUOTA
    if bucket == "JS":
        return _JUNIOR_SERIES_QUOTA
    if bucket == "J":
        return _JUNIOR_QUOTA
    if bucket == "CXJ":
        return _CX_JUNIOR_QUOTA
    if bucket == "CXJWC":
        return _CX_JUNIOR_WC_QUOTA
    return _CLASS_QUOTA.get(bucket, 0)


# One competition can carry several disciplines' events, and the UCI names them
# two different ways in the same feed: an abbreviation somewhere in the label
# ("XCC Men Elite") on some competitions, and the discipline spelled out after
# a dash ("Men Elite - Cross-country short circuit") on others — including
# every World Cup round. Matching only the abbreviations meant a World Cup's
# 22-minute short-track result, worth 30 points, was stored and displayed as
# that rider's cross-country result, which is worth 250.
# Stage races are deliberately absent: XCS is cross-country, not a sibling
# discipline, and _STAGE_QUOTA exists precisely to score it. Excluding it here
# would silently drop results the points rules expect to see.
_SIBLING_EVENT_PHRASES = (
    "short circuit", "eliminator", "marathon", "team relay", "point to point",
    "point-to-point", "time trial", "downhill", "enduro", "four cross",
    "four-cross", "pump track", "qualifying", "e-mtb",
)
_SIBLING_EVENT_WORDS = frozenset({
    "xcc", "xce", "xcm", "xcr", "xcp", "xct",
    "dhi", "dhp", "dho", "edr", "4x",
})
# The discipline we do want, in both spellings.
_WANTED_EVENT_PHRASES = ("cross-country olympic", "cross country olympic")
_WANTED_EVENT_WORDS = frozenset({"xco"})


def _label_discipline(label: str) -> str:
    """Classify a results-accordion label as 'wanted', 'other' or 'plain'.

    'plain' means the label names no discipline at all ("Men Elite"), which is
    what a single-discipline competition publishes — and what every cyclo-cross
    competition publishes, since its only sibling is a mixed team relay whose
    label never matches a category we map.
    """
    low = label.lower()
    words = set(re.findall(r"[a-z0-9]+", low))
    if words & _WANTED_EVENT_WORDS or any(p in low for p in _WANTED_EVENT_PHRASES):
        return "wanted"
    if words & _SIBLING_EVENT_WORDS or any(p in low for p in _SIBLING_EVENT_PHRASES):
        return "other"
    return "plain"


def _get_competition_details(competition_id: str, year: int,
                             discipline: str = DEFAULT_DISCIPLINE) -> dict:
    """
    Returns {"events": {uci_cat: event_code}, "class": "<code>"} for a
    competition by parsing its UCI detail page. Cached per competition.

    The class drives the points quotas in art. 4.16.008, and it comes off the
    very same page as the event codes, so capturing it costs no extra request.
    The cache file carries a version suffix: v1 stored only the event code
    mapping (a stale one would silently yield no class), and v2 could name the
    wrong discipline's event entirely (see _label_discipline).
    """
    disc = get_discipline(discipline)
    # v3: v2 files were written by a label filter that missed the spelled-out
    # discipline names, so many of them name a short-track or downhill event
    # where they claim a cross-country one. They cannot be repaired in place —
    # the code is all that was kept — so the version moves and they are refetched.
    path = os.path.join(_uci_comp_dir(disc.code), f"{competition_id}.v3.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    try:
        r = requests.get(
            f"{_UCI_BASE}/competition-details/{year}/{disc.calendar_discipline}/{competition_id}",
            headers={**_UCI_HEADERS, "Accept": "text/html"},
            timeout=15,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        el = soup.find(attrs={"data-component": "CompetitionDetailsModule"})
        if not el:
            return {}
        props = json.loads(el["data-props"])
        comp_class = _parse_competition_class(props)
        comp_name = props.get("competitionName", "")
        label_to_cat = {v.lower(): k for k, v in _UCI_CATEGORY_LABELS.items()}
        # Sort longest first so "women elite" is tried before "men elite" (substring of it)
        sorted_labels = sorted(label_to_cat, key=len, reverse=True)
        # Two-pass: a group whose label names the discipline we want beats a
        # plain one, and a group naming a sibling discipline is skipped.
        wanted_codes: dict = {}
        plain_codes: dict = {}
        for group in props.get("results", {}).get("accordion", []):
            label = group.get("label", "")
            kind = _label_discipline(label)
            if kind == "other":
                continue
            cat = next((label_to_cat[lbl] for lbl in sorted_labels
                        if lbl in label.lower()), None)
            if not cat:
                continue
            for result in group.get("results", []):
                code = result.get("eventCode", "")
                if code:
                    if kind == "wanted":
                        wanted_codes[cat] = code
                    else:
                        plain_codes.setdefault(cat, code)
                    break
        event_codes = {**plain_codes, **wanted_codes}
        details = {"events": event_codes, "class": comp_class, "name": comp_name}
        # Don't cache an empty result: it usually just means the UCI hasn't
        # published category entries for this competition yet (checked too
        # early), and this cache has no TTL — caching {} would make it stick
        # forever even once results appear.
        if event_codes:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(details, f, ensure_ascii=False)
        time.sleep(0.3)
        return details
    except Exception:
        return {}


def _get_competition_event_codes(competition_id: str, year: int,
                                 discipline: str = DEFAULT_DISCIPLINE) -> dict:
    """Backwards-compatible view over _get_competition_details."""
    return _get_competition_details(competition_id, year, discipline).get("events", {})


def _normalize_race_time(raw: str) -> str:
    """
    Normalize UCI time values to HH:MM:SS.
    Handles: Excel fraction-of-day floats, sub-second decimals (1:07:05.75),
    and stray period separators (1.03:20 → 1:03:20).
    Non-time strings (OVL, DNF, …) are returned as-is.
    """
    if not raw:
        return ""
    # Excel fraction-of-day
    try:
        val = float(raw)
        total_sec = round(val * 86400)
        h, rem = divmod(total_sec, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    except ValueError:
        pass
    # Strip sub-second precision: "1:07:05.75" → "1:07:05"
    t = re.sub(r"(\d{2})\.\d+$", r"\1", raw)
    # Fix stray period used as separator: "1.03:20" → "1:03:20"
    t = re.sub(r"^(\d+)\.(\d{2}:\d{2})$", r"\1:\2", t)
    return t


def _get_uci_event_results(event_code: str) -> list:
    """
    Returns the full result list for an event from the UCI website.
    Each item: {rank, first_name, last_name, time, nationality, points}.
    Cached per event_code (file in uci_events/).
    """
    path = os.path.join(_uci_event_dir(), f"{event_code}.json")
    if os.path.exists(path):
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        if _rider_history_is_fresh(mtime):
            with open(path, encoding="utf-8") as f:
                return json.load(f)

    try:
        r = requests.get(
            f"{_UCI_BASE}/api/calendar/results/{event_code}",
            params={"discipline": "MTB", "raceType": "A", "raceName": "General Classification"},
            headers=_UCI_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        raw = r.json().get("results", [])
        results = [
            {
                "rank":        item["values"].get("rank"),
                "first_name":  item["values"].get("firstname", ""),
                "last_name":   item["values"].get("lastname", ""),
                "time":        _normalize_race_time(item["values"].get("result", "")),
                "nationality": item["values"].get("nationality", ""),
                "points":      item["values"].get("points", ""),
            }
            for item in raw
            if item.get("headerType") == "rider"
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False)
        time.sleep(0.2)
        return results
    except Exception:
        return []


def _enrich_results_with_times(results: list, uci_cat: str, catalog: dict,
                               discipline: str = DEFAULT_DISCIPLINE) -> None:
    """
    For each result, look up the UCI event code from the competition catalog,
    then fetch the full event results to fill in 'time'. Modifies results in-place.
    """
    by_id = catalog.get("by_id", {})
    by_name = catalog.get("by_name", {})
    default_year = get_discipline(discipline).season_year()

    for res in results:
        if res.get("time"):
            continue
        comp_name = res.get("race_name", "")
        result_date = res.get("date", "")
        result_ym = _parse_year_month(result_date)

        comp_ids = by_name.get(comp_name.lower(), [])
        if not comp_ids:
            continue

        # When multiple rounds share the same name, pick by year+month of the result date
        comp_id = None
        comp_year = default_year
        if len(comp_ids) == 1:
            comp_id = comp_ids[0]
            comp_year = by_id.get(comp_id, {}).get("year", default_year)
        else:
            for cid in comp_ids:
                entry = by_id.get(cid, {})
                if result_ym != (0, 0) and _parse_year_month(entry.get("dates", "")) == result_ym:
                    comp_id = cid
                    comp_year = entry.get("year", default_year)
                    break
            if not comp_id:
                # Fallback: first entry whose year matches
                for cid in comp_ids:
                    if by_id.get(cid, {}).get("year") == result_ym[0]:
                        comp_id = cid
                        comp_year = result_ym[0]
                        break

        if not comp_id:
            continue

        details = _get_competition_details(comp_id, comp_year, discipline)
        event_code = _event_code_for(details, uci_cat, discipline)
        if not event_code:
            continue
        event_results = _get_uci_event_results(event_code)
        if not event_results:
            continue

        rank = res.get("rank")
        time_val = ""
        if rank is not None:
            for er in event_results:
                try:
                    if int(er.get("rank", -1)) == int(rank):
                        time_val = er.get("time", "")
                        break
                except (ValueError, TypeError):
                    pass
        res["time"] = time_val


def _loose_name(s: str) -> str:
    """Diacritic-stripped, lowercased, hyphens treated as spaces.

    The two sources disagree about compound given names — a start list writes
    'Victor Alexandru' where the UCI writes 'Victor-Alexandru' — and about
    accents. Normalising both to the same shape is what lets them meet.
    """
    return " ".join(_strip_diacritics(s).replace("-", " ").lower().split())


def _build_event_name_map(event_results: list) -> dict:
    """Map lowercase 'first last' / 'last first' / UCI-caps name variants to
    their event result dict, for matching start-list riders against a UCI
    event's official results.

    Diacritic-stripped variants are included as a fallback because timing sites
    routinely publish plain ASCII ("Vit Lisy") where the UCI publishes the
    accented form ("Vít LISÝ"). Without them the winner of a race can simply
    fail to match and end up with no result at all.

    The UCI results API returns no rider ID — only name, rank, time, age and
    nationality — so name matching is the only option here.
    """
    name_map: dict = {}
    for er in event_results:
        fn = er.get("first_name", "").strip()
        ln = er.get("last_name", "").strip()
        for key in (
            f"{fn} {ln}".lower(),
            f"{ln} {fn}".lower(),
            f"{fn.upper()} {ln.upper()}",   # UCI all-caps variant
        ):
            name_map[key] = er

    # Looser keys are added in a second pass, and only when unambiguous: if two
    # riders in the same event collapse to the same loose key, matching either
    # would be a coin flip, so neither is added.
    loose: dict = {}

    def _add(key: str, er: dict) -> None:
        if not key.strip():
            return
        if key in loose and loose[key] is not er:
            loose[key] = None             # ambiguous — drop it
        else:
            loose.setdefault(key, er)

    for er in event_results:
        fn = _loose_name(er.get("first_name", ""))
        ln = _loose_name(er.get("last_name", ""))
        _add(f"{fn} {ln}", er)
        _add(f"{ln} {fn}", er)
        # Start lists sometimes carry a middle name the UCI omits ("Boldizsár
        # Béla Szalay" vs "Boldizsár SZALAY"), so key on the first given name
        # alone as well.
        first = fn.split()[0] if fn.split() else ""
        _add(f"{first} {ln}", er)
        _add(f"{ln} {first}", er)

    for key, er in loose.items():
        # Never let a loose key shadow an exact one.
        if er is not None:
            name_map.setdefault(key, er)

    return name_map


def _match_rider_in_event_map(rider, name_map: dict) -> "dict | None":
    fn = rider.first_name.strip()
    ln = rider.last_name.strip()
    for key in (
        f"{fn} {ln}".lower(),
        f"{ln} {fn}".lower(),
        f"{fn.upper()} {ln.upper()}",
        f"{fn.lower()} {ln.upper()}",
    ):
        er = name_map.get(key)
        if er:
            return er
    # Fall back to the looser forms only after every exact spelling has been
    # tried: accent- and hyphen-insensitive first, then dropping any middle
    # name. Both sides get truncated because either source may be the one
    # carrying it.
    s_fn = _loose_name(fn)
    s_ln = _loose_name(ln)
    first = s_fn.split()[0] if s_fn.split() else ""
    for key in (
        f"{s_fn} {s_ln}",
        f"{s_ln} {s_fn}",
        f"{first} {s_ln}",
        f"{s_ln} {first}",
    ):
        er = name_map.get(key)
        if er:
            return er
    return None


def enrich_with_race_results(riders: list, competition_id: str, year: int, uci_cat: str,
                             discipline: str = DEFAULT_DISCIPLINE) -> None:
    """
    Fetch the official UCI final classification for a specific (already-run)
    competition and attach each matched rider's finishing rank/time as
    result_rank/result_time. Used for past races so the site can display the
    actual results instead of the pre-race start-list order.
    """
    details = _get_competition_details(competition_id, year, discipline)
    event_code = _event_code_for(details, uci_cat, discipline)
    if not event_code:
        return

    event_results = _get_uci_event_results(event_code)
    if not event_results:
        return

    name_map = _build_event_name_map(event_results)

    for rider in riders:
        er = _match_rider_in_event_map(rider, name_map)
        if not er:
            continue
        rank_raw = er.get("rank")
        rider.result_rank = int(rank_raw) if rank_raw and str(rank_raw).isdigit() else None
        rider.result_time = er.get("time", "")


def riders_from_uci_competition(competition_id: str, year: int, uci_cat: str,
                                discipline: str = DEFAULT_DISCIPLINE) -> list:
    """
    Reconstruct a past race's field from its official UCI classification.

    Timing sites take start lists down once an event is over, which otherwise
    leaves past races with nothing to show. The UCI keeps the final
    classification, so for a race that has already run the finishers are a
    better source than the organiser's site — it cannot rot.

    Returns [] when the UCI has no distinct event for this exact category,
    rather than falling back to a related one — this is the one place the
    fallback chain in _event_code_for() must not apply. U23 has no standalone
    UCI event, and cyclo-cross junior women have none at a class 1/2 round;
    borrowing the Elite or combined-women finishers here would invent a field
    that never started, rather than merely reading a rider's result out of the
    race she actually rode.
    """
    event_codes = _get_competition_event_codes(competition_id, year, discipline)
    event_code = event_codes.get(uci_cat)
    if not event_code:
        console.print(
            f"[dim]  No standalone UCI {uci_cat} event — cannot rebuild from results[/dim]"
        )
        return []

    event_results = _get_uci_event_results(event_code)
    if not event_results:
        return []

    riders = []
    for er in event_results:
        first = (er.get("first_name") or "").strip()
        last  = (er.get("last_name") or "").strip()
        if not (first or last):
            continue
        rank_raw = er.get("rank")
        riders.append(Rider(
            first_name=first,
            # The UCI publishes surnames in caps; match the casing the start
            # list parsers produce via normalize_rider_name().
            last_name=last.title() if last.isupper() else last,
            country=normalize_country(er.get("nationality", "")),
            result_rank=int(rank_raw) if rank_raw and str(rank_raw).isdigit() else None,
            result_time=er.get("time", ""),
        ))
    return riders


def supplement_from_uci_competition(
    riders: list, competition_id: str, year: int, uci_cat: str,
    discipline: str = DEFAULT_DISCIPLINE
) -> None:
    """
    Fetch the full event results for a specific UCI competition and supplement
    each rider's race history with their result if it isn't already present.
    Used for races where the rider may have placed outside the points-scoring zone
    (so their result won't appear in IndividualEventRankings).
    Modifies rider.race_results in-place.
    """
    details = _get_competition_details(competition_id, year, discipline)
    event_code = _event_code_for(details, uci_cat, discipline)
    if not event_code:
        return

    event_results = _get_uci_event_results(event_code)
    if not event_results:
        return

    name_map = _build_event_name_map(event_results)

    # Derive race metadata from the competition catalog (already cached)
    catalog = _get_uci_competition_catalog(year, discipline)
    comp_entry = catalog.get("by_id", {}).get(competition_id, {})
    comp_name = comp_entry.get("name", f"UCI Competition {competition_id}")
    comp_dates = comp_entry.get("dates", "")
    # Use end date of range as the canonical date for the race_id key
    comp_date = comp_dates.split(" - ")[-1] if " - " in comp_dates else comp_dates

    existing_key = f"{comp_date}|{comp_name}"

    for rider in riders:
        er = _match_rider_in_event_map(rider, name_map)
        if not er:
            continue

        # Skip if the rider already has a result for this competition in their history.
        # Check by name (not race_id) because dataride and UCI may use different dates.
        already_there = any(
            r.get("race_name") == comp_name
            for r in getattr(rider, "race_results", [])
        )
        if already_there:
            continue

        rider.race_results = list(getattr(rider, "race_results", []))
        rider.race_results.append({
            "race_id":   existing_key,
            "race_name": comp_name,
            "date":      comp_date,
            "location":  comp_entry.get("venue", ""),
            "rank":      int(er["rank"]) if er.get("rank") and str(er["rank"]).isdigit() else None,
            "time":      er.get("time", ""),
            "cat":       _ranking_category(uci_cat, discipline),
            "disc":      get_discipline(discipline).code,
        })


def supplement_from_rider_histories(riders: list, uci_cat: str,
                                    discipline: str = DEFAULT_DISCIPLINE) -> None:
    """
    Supplement all riders with zero-point results from every competition that
    appears in any rider's IndividualEventRankings history.

    IndividualEventRankings only returns point-scoring results.  If Rider A
    scored points at competition X but Rider B got zero points, Rider B's
    result is absent from their history — breaking H2H comparisons.  This
    function closes that gap by re-fetching full event results for each
    competition any rider in the list is known to have attended.
    """
    # Collect unique (race_name, year) pairs from all riders' histories
    pairs: set = set()
    for rider in riders:
        for res in getattr(rider, "race_results", []):
            rn = res.get("race_name", "")
            rd = res.get("date", "")
            if not rn:
                continue
            ym = _parse_year_month(rd)
            year = ym[0] if ym[0] else datetime.now().year
            pairs.add((rn, year))

    if not pairs:
        return

    catalogs = {y: _get_uci_competition_catalog(y, discipline)
                for y in {y for _, y in pairs}}

    supplemented_ids: set = set()
    for race_name, year in pairs:
        comp_ids = catalogs[year].get("by_name", {}).get(race_name.lower(), [])
        for comp_id in comp_ids:
            if comp_id not in supplemented_ids:
                supplement_from_uci_competition(
                    riders, comp_id, year, uci_cat, discipline)
                supplemented_ids.add(comp_id)


def fetch_rider_history_uci(object_id: int, uci_cat: str, cache: dict,
                            discipline: str = DEFAULT_DISCIPLINE) -> list:
    """Fetch UCI race result history for a rider from dataride.uci.ch.

    Superseded by build_uci_xco_history(): IndividualEventRankings only returns
    races where the rider actually scored, so a low-ranked rider who starts
    everything comes back with an empty history. Kept for the times it fills in
    below, and parameterised by discipline so it can never quietly answer a
    cyclo-cross question with MTB data.
    """
    if not object_id:
        return []
    disc = get_discipline(discipline)
    path = _rider_cache_path(f"uci_{_disc_prefix(disc.code)}{object_id}")
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
        "disciplineId":       disc.dataride_discipline_id,
        "categoryId":         _DATARIDE_CATEGORY_IDS.get(uci_cat, 0),
        "raceTypeId":         disc.dataride_race_type_id,
        "countryId": 0, "teamId": 0,
        "take": 200, "skip": 0, "page": 1, "pageSize": 200,
    }
    try:
        r = requests.post(
            f"{DATARIDE_BASE}/iframe/IndividualEventRankings/",
            data=data, headers=_dataride_headers(disc), timeout=20,
        )
        r.raise_for_status()
        items = r.json().get("data", [])
        results = [
            {
                # Shared race key: same for all riders in the same competition
                "race_id":   f"{item.get('Date', '')}|{item.get('CompetitionName', '')}",
                "race_name": item.get("CompetitionName", ""),
                "date":      item.get("Date", ""),
                "location":  "",
                "rank":      item.get("Rank"),
                "time":      "",
                "cat":       uci_cat,
                "disc":      disc.code,
            }
            for item in items
            if item.get("Rank") is not None
        ]
        # Enrich with times from UCI calendar API
        catalog = _get_uci_competition_catalog(disc.season_year(), disc.code)
        _enrich_results_with_times(results, uci_cat, catalog, disc.code)
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


def _parse_dotnet_date(raw: str) -> "datetime | None":
    """Parse dataride's '/Date(1222034400000)/' (ms since epoch) format."""
    m = re.search(r"/Date\((-?\d+)\)/", raw or "")
    if not m:
        return None
    try:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def _parse_dataride_name(display_name: str) -> tuple:
    """Convert 'LASTNAME Firstname' (dataride.uci.ch format) to (firstname, lastname), title case.

    Tokens with no letters are dropped first. The Elite rankings prefix
    U23-eligible riders with '*', and left in place that marker does double
    damage: it stays in the name, and it satisfies the "first non-uppercase
    token" test at index 0, so the function bails out and returns the name
    still in LASTNAME-first order. Nearly half the Elite field is marked this
    way, so those riders matched nothing and showed as unranked with zero
    points.
    """
    parts = [p for p in display_name.split() if any(c.isalpha() for c in p)]
    i = next(
        (j for j, p in enumerate(parts) if p != p.upper() or not any(c.isalpha() for c in p)),
        len(parts),
    )
    if i == 0 or i == len(parts):
        # No reliable ALL-CAPS/mixed-case split point — best effort, keeping
        # this function's own "first token is the surname" convention.
        titled = [p.title() for p in parts]
        if not titled:
            return display_name.title(), ""
        return " ".join(titled[1:]), titled[0]
    lastname  = " ".join(p.title() for p in parts[:i])
    firstname = " ".join(parts[i:])
    return firstname, lastname


def _dataride_headers(disc) -> dict:
    return {**_DATARIDE_HEADERS,
            "Referer": f"{DATARIDE_BASE}/iframe/rankings/{disc.dataride_discipline_id}"}


def _dataride_get_ranking_params(uci_cat: str,
                                 discipline: str = DEFAULT_DISCIPLINE) -> tuple:
    """Return (season_id, ranking_id, moment_id, group_id) for a UCI category.

    A race-type filter is only sent when the discipline splits its rankings by
    race type (MTB does: XCO, XCM, DHI...). Cyclo-cross rankings carry
    RaceTypeId 0, and sending the filter anyway silently returns the *road*
    world ranking instead — Pogačar at the top of a cyclo-cross start list.
    """
    disc = get_discipline(discipline)
    year = disc.season_year()
    r = requests.get(
        f"{DATARIDE_BASE}/iframe/GetDisciplineSeasons/",
        params={"disciplineId": disc.dataride_discipline_id},
        headers=_dataride_headers(disc),
        timeout=15,
    )
    r.raise_for_status()
    seasons = r.json()
    season_id = next((s["Id"] for s in seasons if s["Year"] == year), None)
    if not season_id:
        # A cyclo-cross season is only published once the UCI opens it, so
        # early in the autumn the current label may not exist yet. Fall back to
        # the most recent one — art. C0922 says exactly that: use the previous
        # season's final ranking until this season's is published.
        newest = max(seasons, key=lambda s: s["Year"], default=None)
        if not newest:
            raise RuntimeError(
                f"No dataride seasons for {disc.label} (looked for {year})"
            )
        console.print(
            f"[dim]  {disc.label} season {year} not published yet — "
            f"using {newest['Year']}[/dim]"
        )
        season_id = newest["Id"]

    cat_id = _DATARIDE_CATEGORY_IDS[uci_cat]
    filters = [("CategoryId", cat_id), ("SeasonId", season_id)]
    if disc.dataride_race_type_id:
        filters.insert(0, ("RaceTypeId", disc.dataride_race_type_id))
    data = {
        "disciplineId": disc.dataride_discipline_id,
        "take": 10, "skip": 0, "page": 1, "pageSize": 10,
        "filter[logic]": "and",
    }
    for i, (field_, value) in enumerate(filters):
        data[f"filter[filters][{i}][field]"] = field_
        data[f"filter[filters][{i}][value]"] = value
    r = requests.post(
        f"{DATARIDE_BASE}/iframe/RankingsDiscipline/",
        data=data,
        headers=_dataride_headers(disc),
        timeout=15,
    )
    r.raise_for_status()
    result = r.json()
    if not result or not result[0].get("Rankings"):
        raise RuntimeError(f"No {disc.label} ranking published for {uci_cat}")
    # The individual ranking (RankingTypeId 1) — the nation ranking shares the
    # same group and would otherwise win whenever it is listed first.
    rankings = result[0]["Rankings"]
    ranking = next((rk for rk in rankings
                    if rk.get("RankingTypeId") == _DATARIDE_RANK_TYPE_ID), rankings[0])
    return season_id, ranking["Id"], ranking["MomentId"], result[0]["GroupId"]


def _dataride_fetch_all_riders(season_id: int, ranking_id: int, moment_id: int,
                                cat_id: int,
                                discipline: str = DEFAULT_DISCIPLINE) -> list:
    """Fetch the complete paginated rider list from dataride.uci.ch."""
    disc = get_discipline(discipline)
    riders: list = []
    skip = 0
    page_size = 100
    while True:
        filters = [
            ("CategoryId", cat_id),
            ("SeasonId", season_id),
            ("MomentId", moment_id),
            ("CountryId", 0),
            ("IndividualName", ""),
            ("TeamName", ""),
        ]
        if disc.dataride_race_type_id:
            filters.insert(0, ("RaceTypeId", disc.dataride_race_type_id))
        data = {
            "rankingId": ranking_id,
            "disciplineId": disc.dataride_discipline_id,
            "rankingTypeId": _DATARIDE_RANK_TYPE_ID,
            "take": page_size,
            "skip": skip,
            "page": (skip // page_size) + 1,
            "pageSize": page_size,
            "filter[logic]": "and",
        }
        for i, (field_, value) in enumerate(filters):
            data[f"filter[filters][{i}][field]"] = field_
            data[f"filter[filters][{i}][value]"] = value
        r = requests.post(
            f"{DATARIDE_BASE}/iframe/ObjectRankings/",
            data=data,
            headers=_dataride_headers(disc),
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


def build_uci_cache(uci_cat: str, discipline: str = DEFAULT_DISCIPLINE) -> dict:
    """Downloads the full UCI ranking from dataride.uci.ch and saves to cache."""
    disc = get_discipline(discipline)
    console.print(
        f"\n[cyan]Downloading UCI {disc.label} ranking ({uci_cat}) "
        f"from dataride.uci.ch...[/cyan]"
    )
    cat_id = _DATARIDE_CATEGORY_IDS.get(uci_cat)
    if not cat_id:
        console.print(f"[yellow]Unknown UCI category: {uci_cat}[/yellow]")
        return load_cache(uci_cat, disc.code)

    try:
        season_id, ranking_id, moment_id, group_id = _dataride_get_ranking_params(
            uci_cat, disc.code)
        raw_riders = _dataride_fetch_all_riders(
            season_id, ranking_id, moment_id, cat_id, disc.code)
    except Exception as e:
        console.print(
            f"[yellow]Failed to fetch UCI {disc.label} ranking ({uci_cat}): {e}[/yellow]")
        return load_cache(uci_cat, disc.code)

    by_name: dict = {}
    for item in raw_riders:
        first_name, last_name = _parse_dataride_name(item.get("DisplayName", ""))
        name = f"{first_name} {last_name}".strip()
        if not name:
            continue
        country = item.get("NationName", "").strip()
        dob = _parse_dotnet_date(item.get("BirthDate", ""))
        by_name[name.lower()] = {
            "rank":      item["Rank"],
            "points":    item.get("Points", 0),
            "name":      name,
            "first_name": first_name,
            "last_name":  last_name,
            "slug":      "",
            "country":   country,
            "team":      (item.get("TeamName") or "").strip(),
            "object_id": item.get("ObjectId", 0),
            # The rider's actual UCI ID (distinct from ObjectId, which is
            # dataride's own internal key) and birth year. Every ranked rider
            # carries both — this is the UCI's own identity record, so it is a
            # far more reliable source than any one start list.
            "uci_id":     str(item["UciId"]) if item.get("UciId") else "",
            "birth_year": str(dob.year) if dob else "",
        }

    if not by_name:
        console.print(
            f"[yellow]No {disc.label} riders found for {uci_cat}, "
            f"keeping existing cache[/yellow]")
        return load_cache(uci_cat, disc.code)

    cache = {
        "by_name":      by_name,
        "by_id":        {},
        "fetched_at":   datetime.now().isoformat(),
        "ranking_date": datetime.now().strftime("%Y-%m-%d"),
        "ranking_id":   ranking_id,
        "moment_id":    moment_id,
        "group_id":     group_id,
        "season_id":    season_id,
        "discipline":   disc.code,
    }
    save_cache(uci_cat, cache, disc.code)
    console.print(f"[green]✓ Loaded {len(by_name)} {disc.label} riders ({uci_cat})[/green]")
    return cache


def get_uci_cache(uci_cat: str, force_refresh: bool = False,
                  discipline: str = DEFAULT_DISCIPLINE) -> dict:
    disc = get_discipline(discipline)
    uci_cat = _ranking_category(uci_cat, disc.code)
    if not force_refresh and cache_is_fresh(uci_cat, disc.code):
        console.print(f"[dim]Using cached UCI {disc.label} ranking ({uci_cat})[/dim]")
        return load_cache(uci_cat, disc.code)
    return build_uci_cache(uci_cat, disc.code)


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
        # Backfill identity from the UCI's own ranking record — but only on an
        # exact name match. A fuzzy match can pick the wrong person entirely
        # (two similarly-named riders), and propagating uci_id from that would
        # silently merge two different humans' race histories under one
        # identity in store.py — a worse failure than the duplicate-rider
        # forks this is meant to fix. Only fill blanks: a value the start list
        # already supplied is left alone rather than overwritten.
        if confidence == 100:
            if not rider.uci_id and entry.get("uci_id"):
                rider.uci_id = entry["uci_id"]
            if not rider.birth_year and entry.get("birth_year"):
                rider.birth_year = entry["birth_year"]
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


# Bumped when the parse changes shape. v1 summed every numeric cell after the
# club column, which swept up the sheet's own "Celkem" and returned exactly
# double the real total; the sort order never noticed, so nothing looked wrong.
# A stale v1 file would keep serving those doubled numbers until its weekday
# TTL happened to expire, hence a new filename rather than a silent fix.
_CUP_CACHE_VERSION = "v2"


def _cup_cache_path(standings_url: str, category_id: str,
                    discipline: str = DEFAULT_DISCIPLINE) -> str:
    m = re.search(r"/(\d{4})/", standings_url)
    year = m.group(1) if m else "unknown"
    os.makedirs(CACHE_DIR, exist_ok=True)
    prefix = "cp_xco" if discipline == XCO else f"cup_{discipline.lower()}"
    return os.path.join(
        CACHE_DIR, f"{prefix}_{_CUP_CACHE_VERSION}_{year}_{category_id}.json"
    )


def _cup_row_total(cells: list, total_idx: int) -> int:
    """Season total for one standings row.

    Prefers the sheet's own "Celkem" column, whose index the header gives us —
    it already reflects whatever best-N rule the series applies. Falls back to
    summing everything after the club column only when the header had no
    "Celkem", and then stops before the last two cells (the total itself and
    the "Detail" link) so the total is not counted twice.
    """
    if total_idx is not None and total_idx < len(cells):
        text = cells[total_idx]
        return int(text) if text.isdigit() else 0
    return sum(int(c) for c in cells[5:-2] if c.isdigit())


def fetch_cup_standings(standings_url: str, uci_cat: str,
                        discipline: str = DEFAULT_DISCIPLINE) -> dict:
    """
    Fetch Czech Cup standings for a UCI category from a sportsoft results page
    (cpxcmtb.sportsoft.cz for MTB XCO, cpcx.sportsoft.cz for cyclo-cross).

    The site is ASP.NET WebForms: a GET retrieves the ViewState, then a POST
    selects the desired category.  The layouts differ slightly between the two
    series (MTB carries an extra blank column), so the columns are read off the
    header rather than by fixed index.

    Returns {ascii_full_name: total_points} keyed by diacritic-stripped
    lowercase 'firstname lastname' so callers can do a direct dict lookup.
    """
    disc = get_discipline(discipline)
    category_id = disc.cup_category_ids.get(uci_cat)
    if not category_id:
        return {}

    cache_file = _cup_cache_path(standings_url, category_id, disc.code)
    if os.path.exists(cache_file):
        mtime = datetime.fromtimestamp(os.path.getmtime(cache_file))
        if _rider_history_is_fresh(mtime):
            with open(cache_file, encoding="utf-8") as f:
                return json.load(f)

    try:
        # A session, not bare requests: these sites bounce the first request
        # through ?AspxAutoDetectCookieSupport=1 and only serve the page once
        # the cookie comes back, so without a cookie jar every GET redirects.
        session = requests.Session()
        resp = session.get(standings_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        def _field(name: str) -> str:
            tag = soup.find("input", {"name": name})
            return tag["value"] if tag else ""

        resp2 = session.post(
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

        table = tables[0]
        header = table.find("tr")
        headings = [th.get_text(strip=True).lower()
                    for th in header.find_all(["th", "td"])] if header else []
        total_idx = headings.index("celkem") if "celkem" in headings else None

        result: dict[str, int] = {}
        for row in table.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < 7:
                continue
            rank_text = cells[0].rstrip(".")
            if not rank_text.isdigit():
                continue

            normalized = normalize_rider_name(cells[1])
            key = _strip_diacritics(normalized.lower())
            result[key] = _cup_row_total(cells, total_idx)

        # An empty table is not a fact worth caching: early in a season the
        # current page exists but nobody has scored yet, and fetch_first_cup_
        # standings() is relying on that emptiness to fall through to last
        # season. Caching it would keep the fallback in place for days after
        # the first round has actually been ridden and scored.
        if result:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        return result

    except Exception as e:
        console.print(f"[yellow]Could not fetch {disc.label} cup standings: {e}[/yellow]")
        return {}


def fetch_first_cup_standings(urls, uci_cat: str,
                              discipline: str = DEFAULT_DISCIPLINE) -> dict:
    """First non-empty standings among `urls`, tried in order.

    races.yml lists the current season's page first and the previous season's
    after it. Early in a cyclo-cross season the current page exists but is
    empty — nobody has scored yet — and the grid for round one is set by last
    season's final standings anyway (art. C0919), so falling through to it is
    both the correct rule and the only source with data.
    """
    if isinstance(urls, str):
        urls = [urls]
    for url in urls or []:
        standings = fetch_cup_standings(url, uci_cat, discipline)
        if standings:
            return standings
    return {}


def fetch_cp_xco_standings(standings_url: str, uci_cat: str) -> dict:
    """Backwards-compatible MTB-only alias for fetch_cup_standings."""
    return fetch_cup_standings(standings_url, uci_cat, XCO)


def enrich_cup_points(riders: list, standings: dict, ranked_too: bool = False) -> None:
    """Assign cp_xco_points from the domestic cup standings.

    By default only unranked riders get a value: in MTB XCO the UCI ranking
    decides the grid and the cup standing is just the last tie-break, so
    filling it in for ranked riders would be noise. `ranked_too` is for
    cyclo-cross, where the cup standing *is* the grid (art. C0919) and every
    entrant's standing matters regardless of their UCI rank.
    """
    for rider in riders:
        if rider.uci_rank is not None and not ranked_too:
            continue
        key = _strip_diacritics(rider.full_name.lower())
        if key in standings:
            rider.cp_xco_points = standings[key]
            continue
        # Try reversed order (start list may have last–first vs first–last)
        key_rev = _strip_diacritics(f"{rider.last_name} {rider.first_name}".lower())
        rider.cp_xco_points = standings.get(key_rev, 0)


def enrich_cp_xco_points(riders: list, standings: dict) -> None:
    """Backwards-compatible alias for enrich_cup_points."""
    enrich_cup_points(riders, standings)
