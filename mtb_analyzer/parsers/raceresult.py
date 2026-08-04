import re
from urllib.parse import urlparse

import requests

from ..config import HEADERS, ISO2_TO_IOC, console
from ..models import Rider
from ..utils import category_matches, normalize_category_name


def _find_col(fields: list, *needles: str) -> "int | None":
    """
    DataFields entries aren't always plain field names — some lists (e.g.
    combined age-group rankings) emit full RaceResult formula expressions
    like "if([CONTEST]=1 AND ...;[TS6.P1.YEAR];[TS1.P1.YEAR])" instead of a
    bare "YEAR". Substring search finds the right column either way; an
    exact-equality check would silently miss it and fall back to a wrong
    hardcoded index.
    """
    return next((i for i, f in enumerate(fields) if any(n in f for n in needles)), None)


def _total_rows(payload: dict) -> int:
    """Count entries across all groups/subgroups in a RRPublish list payload.
    Used to pick the actual full-roster list over a same-event live-commentary
    "preview" feed (e.g. RaceResult's LIVE-SPEAKER lists), which can be
    non-empty but only contain a tiny highlight subset of riders."""
    d = payload.get("data")
    if isinstance(d, list):
        return len(d)
    if not isinstance(d, dict):
        return 0
    total = 0
    for grp_val in d.values():
        if isinstance(grp_val, dict):
            total += sum(len(rows) for rows in grp_val.values() if isinstance(rows, list))
        elif isinstance(grp_val, list):
            total += len(grp_val)
    return total


def parse_raceresult(url: str, category_filter: str = None) -> list:
    """
    Parses a my.raceresult.com page via the internal JSON API.

    Two modes are auto-detected via /RRPublish/data/config:

    Results mode (showResults=true):
      Fetches /RRPublish/data/list.  Data is grouped by category → gender
      subgroup.  Row layout: [BIB, ID, rank, Name, flag_img, year, club, ...]
      Gender comes from subgroup name: männlich/M = Men, weiblich/W = Women.

    Participants mode (showParticipants=true, showResults=false):
      Fetches /{event_id}/participants/config for the list name, then
      /{event_id}/participants/list.  Data is grouped by contest name.
      Row layout determined by DataFields; gender (M/W) is a per-row field.
      Category is built as "{gender} {contest_name}" (e.g. "Men XCO UCI C1").

    Country is extracted from flag SVG URL (ISO 2-letter → IOC 3-letter).
    """
    parsed   = urlparse(url)
    event_id = parsed.path.strip("/").split("/")[0]
    origin   = f"{parsed.scheme}://{parsed.netloc}"

    try:
        resp = requests.get(f"{origin}/{event_id}/RRPublish/data/config",
                            headers=HEADERS, timeout=20)
        resp.raise_for_status()
        config = resp.json()
    except Exception:
        # Some newer raceresult.com events don't expose the legacy RRPublish
        # API at all (404) — only /{event_id}/participants/config. Try that
        # directly before giving up; it carries its own "key" field.
        try:
            p_resp = requests.get(f"{origin}/{event_id}/participants/config",
                                   params={"lang": "en"}, headers=HEADERS, timeout=20)
            p_resp.raise_for_status()
            p_config = p_resp.json()
        except Exception as e:
            console.print(f"[red]Error fetching raceresult config: {e}[/red]")
            return []
        return _parse_participants(origin, event_id, p_config.get("key", ""), category_filter)

    key = config.get("key", "")

    if config.get("showParticipants") and not config.get("showResults"):
        return _parse_participants(origin, event_id, key, category_filter)

    lists = config.get("lists", [])
    if not lists:
        console.print("[red]No lists found in raceresult config[/red]")
        return []

    # Check every list and use whichever has the most total rows — the full
    # roster list, not e.g. a same-event LIVE-SPEAKER feed that's technically
    # non-empty but only carries a small live-commentary highlight subset.
    data, best_count = None, 0
    for lst in lists:
        try:
            resp = requests.get(f"{origin}/{event_id}/RRPublish/data/list",
                                params={"listname": lst["Name"], "contest": "0",
                                        "r": "all", "l": "en", "key": key},
                                headers=HEADERS, timeout=30)
            resp.raise_for_status()
            candidate = resp.json()
        except Exception as e:
            console.print(f"[red]Error fetching raceresult data: {e}[/red]")
            continue
        count = _total_rows(candidate)
        if count > best_count:
            data, best_count = candidate, count

    if data is None:
        console.print("[yellow]No populated list found in raceresult data[/yellow]")
        return []

    fields = data.get("DataFields", [])
    name_col = _find_col(fields, "AnzeigeName")
    name_col = name_col if name_col is not None else 3
    team_col = _find_col(fields, "CLUB")
    team_col = team_col if team_col is not None else 6
    year_col = _find_col(fields, "YEAR")
    # NATION.UCINAME / NATION.IOCNAME contain the IOC alpha-3 code directly
    # (e.g. "GER"). NATION.FLAG contains an img tag/URL that needs
    # _flag_to_country() parsing.
    nat_col = _find_col(fields, "NATION.UCINAME", "NATION.IOCNAME")
    if nat_col is not None:
        nat_direct = True
    else:
        nat_col = _find_col("NATION.FLAG")
        nat_direct = False
        if nat_col is None:
            nat_col = 4

    riders = []
    for grp_key, grp_val in data.get("data", {}).items():
        # Groups with no gender subgroup (grp_val is a list) carry a trailing
        # rider-count suffix in their name, e.g. "Elite Men (2)" — strip it so
        # category_matches() isn't thrown off by the extra word.
        name_no_prefix = re.sub(r"^#\d+_", "", grp_key)
        name_no_count  = re.sub(r"\s*\(\d+\)\s*$", "", name_no_prefix)
        category_base  = normalize_category_name(name_no_count)
        subgroups = grp_val.items() if isinstance(grp_val, dict) else [(grp_key, grp_val)]

        for sub_key, rows in subgroups:
            sub_name  = re.sub(r"^#\d+_", "", sub_key)
            sub_lower = sub_name.lower()
            if "männlich" in sub_lower or "male" in sub_lower or sub_name.endswith(" M"):
                gender = "Men"
            elif "weiblich" in sub_lower or "female" in sub_lower or sub_name.endswith(" W"):
                gender = "Women"
            else:
                gender = ""
            category = f"{gender} {category_base}".strip() if gender else category_base

            if not category_matches(category, category_filter):
                continue

            for row in rows:
                if not isinstance(row, list) or len(row) <= name_col:
                    continue
                name_raw = str(row[name_col]).strip()
                if not name_raw:
                    continue
                if "," in name_raw:
                    last, first = (p.strip().title() for p in name_raw.split(",", 1))
                else:
                    parts = name_raw.split(None, 1)
                    last  = parts[0].title()
                    first = parts[1].title() if len(parts) > 1 else ""

                raw_nat = str(row[nat_col]) if len(row) > nat_col else ""
                country = raw_nat.strip() if nat_direct else _flag_to_country(raw_nat)
                birth_year = str(row[year_col]) if year_col is not None and len(row) > year_col else ""
                riders.append(Rider(
                    first_name=first, last_name=last,
                    country=country,
                    birth_year=birth_year,
                    team=str(row[team_col]) if len(row) > team_col else "",
                    category=category,
                    start_nr=str(row[0]).strip(),
                ))

    return riders


def _parse_participants(origin: str, event_id: str, key: str,
                        category_filter: str = None) -> list:
    """
    Participants-mode parser for events that publish startlists but not results.
    Uses /{event_id}/participants/config + /{event_id}/participants/list.
    Data is grouped by contest (e.g. 'XCO UCI C1'); gender (M/W) is per row.
    Column positions are read from the DataFields array in the list response.
    """
    base = f"{origin}/{event_id}/participants"

    try:
        resp = requests.get(f"{base}/config", params={"lang": "en"},
                            headers=HEADERS, timeout=20)
        resp.raise_for_status()
        p_config = resp.json()
    except Exception as e:
        console.print(f"[red]Error fetching participants config: {e}[/red]")
        return []

    lists = p_config.get("TabConfig", {}).get("Lists", [])
    if not lists:
        console.print("[red]No lists found in participants config[/red]")
        return []

    # raceresult.com sometimes exposes multiple disjoint participant lists for
    # the same event (e.g. a "hobby ages" roster and a separate "UCI
    # categories" roster) rather than one full roster plus a small preview
    # subset. Picking by raw row count alone can select a list that doesn't
    # even contain the requested category, so prefer whichever list actually
    # yields matching riders; fall back to total row count if none do (or no
    # filter was given).
    best_riders, best_score = [], -1
    for lst in lists:
        try:
            resp = requests.get(f"{base}/list",
                                params={"lang": "en", "listname": lst["Name"],
                                        "contest": "0", "r": "all", "key": key},
                                headers=HEADERS, timeout=30)
            resp.raise_for_status()
            candidate = resp.json()
        except Exception as e:
            console.print(f"[red]Error fetching participants list: {e}[/red]")
            continue
        riders = _extract_participant_rows(candidate, category_filter)
        score = len(riders) if category_filter else _total_rows(candidate)
        if score > best_score:
            best_riders, best_score = riders, score

    if best_score <= 0:
        console.print("[yellow]No populated list found in participants data[/yellow]")
        return []

    return best_riders


_CONTEST_NOISE_RE = re.compile(r"\s*[,-]\s*\(?[\d].*$")   # trailing age range / years, e.g. ", 17-18 let(2008-2009)"
_CONTEST_U23_RE   = re.compile(r"/\S+\s*U23\s*$", re.IGNORECASE)  # redundant "/Muži U23" combo suffix


def _extract_participant_rows(data: dict, category_filter: str = None) -> list:
    fields = data.get("DataFields", [])

    # Name: either one combined "AnzeigeName" column, or separate
    # FIRSTNAME/LASTNAME columns (seen on Czech UCI-category lists).
    name_col   = _find_col(fields, "AnzeigeName")
    first_col  = _find_col(fields, "FIRSTNAME")
    last_col   = _find_col(fields, "LASTNAME")
    if name_col is None and first_col is None:
        name_col = 3

    # Nationality: NATION.UCINAME/NATION.IOCNAME carry the IOC alpha-3 code
    # directly; NATION.FLAG carries an img URL that needs _flag_to_country().
    nat_col = _find_col(fields, "NATION.UCINAME", "NATION.IOCNAME")
    nat_direct = nat_col is not None
    if nat_col is None:
        nat_col = _find_col(fields, "NATION.FLAG")
        if nat_col is None:
            nat_col = 4

    year_col   = _find_col(fields, "YEAR")
    gender_col = _find_col(fields, "GeschlechtMW")
    team_col   = _find_col(fields, "CLUB")
    team_col   = team_col if team_col is not None else 6

    riders = []
    for grp_key, rows in data.get("data", {}).items():
        contest_raw  = _CONTEST_U23_RE.sub("", _CONTEST_NOISE_RE.sub("", re.sub(r"^#\d+_", "", grp_key)))
        contest_name = normalize_category_name(contest_raw)
        if not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, list):
                continue

            if first_col is not None and last_col is not None and len(row) > max(first_col, last_col):
                first = str(row[first_col]).strip().title()
                last  = str(row[last_col]).strip().title()
                if not first and not last:
                    continue
            elif name_col is not None and len(row) > name_col:
                name_raw = str(row[name_col]).strip()
                if not name_raw:
                    continue
                if "," in name_raw:
                    last, first = (p.strip().title() for p in name_raw.split(",", 1))
                else:
                    parts = name_raw.split(None, 1)
                    last  = parts[0].title()
                    first = parts[1].title() if len(parts) > 1 else ""
            else:
                continue

            if gender_col is not None and len(row) > gender_col:
                g      = row[gender_col]
                gender = "Men" if g == "M" else ("Women" if g == "W" else "")
            else:
                gender = ""

            # Some lists split gender into separate contests instead of a
            # per-row field (contest_name already starts with "Men"/"Women"
            # from the Czech alias table) — don't double-prepend in that case.
            if gender and not re.match(r"^(Men|Women)\b", contest_name):
                category = f"{gender} {contest_name}".strip()
            else:
                category = contest_name
            if not category_matches(category, category_filter):
                continue

            raw_nat = str(row[nat_col]) if len(row) > nat_col else ""
            country = raw_nat.strip() if nat_direct else _flag_to_country(raw_nat)
            riders.append(Rider(
                first_name=first, last_name=last,
                country=country,
                birth_year=str(row[year_col]) if year_col is not None and len(row) > year_col else "",
                team=str(row[team_col])       if len(row) > team_col else "",
                category=category,
                start_nr=str(row[0]).strip(),
            ))

    return riders


def _flag_to_country(flag_str: str) -> str:
    m = re.search(r"/flags/([A-Z]{2})\.svg", flag_str, re.IGNORECASE)
    return ISO2_TO_IOC.get(m.group(1).upper(), m.group(1).upper()) if m else ""
