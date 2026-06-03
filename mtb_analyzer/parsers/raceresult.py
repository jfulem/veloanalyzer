import re
from urllib.parse import urlparse

import requests

from ..config import HEADERS, ISO2_TO_IOC, console
from ..models import Rider
from ..utils import category_matches, normalize_category_name


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
    except Exception as e:
        console.print(f"[red]Error fetching raceresult config: {e}[/red]")
        return []

    key = config.get("key", "")

    if config.get("showParticipants") and not config.get("showResults"):
        return _parse_participants(origin, event_id, key, category_filter)

    lists = config.get("lists", [])
    if not lists:
        console.print("[red]No lists found in raceresult config[/red]")
        return []

    try:
        resp = requests.get(f"{origin}/{event_id}/RRPublish/data/list",
                            params={"listname": lists[0]["Name"], "contest": "0",
                                    "r": "all", "l": "en", "key": key},
                            headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        console.print(f"[red]Error fetching raceresult data: {e}[/red]")
        return []

    riders = []
    for grp_key, grp_val in data.get("data", {}).items():
        category_base = normalize_category_name(re.sub(r"^#\d+_", "", grp_key))
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
                if not isinstance(row, list) or len(row) < 4:
                    continue
                name_raw = str(row[3]).strip()
                if not name_raw:
                    continue
                if "," in name_raw:
                    last, first = (p.strip().title() for p in name_raw.split(",", 1))
                else:
                    parts = name_raw.split(None, 1)
                    last  = parts[0].title()
                    first = parts[1].title() if len(parts) > 1 else ""

                country = _flag_to_country(str(row[4])) if len(row) > 4 else ""
                riders.append(Rider(
                    first_name=first, last_name=last,
                    country=country,
                    birth_year=str(row[5]) if len(row) > 5 else "",
                    team=str(row[6])       if len(row) > 6 else "",
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

    try:
        resp = requests.get(f"{base}/list",
                            params={"lang": "en", "listname": lists[0]["Name"],
                                    "contest": "0", "r": "all", "key": key},
                            headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        console.print(f"[red]Error fetching participants list: {e}[/red]")
        return []

    fields     = data.get("DataFields", [])
    name_col   = fields.index("AnzeigeName")  if "AnzeigeName"  in fields else 3
    flag_col   = fields.index("NATION.FLAG")  if "NATION.FLAG"  in fields else 4
    year_col   = fields.index("YEAR")         if "YEAR"         in fields else 5
    gender_col = fields.index("GeschlechtMW") if "GeschlechtMW" in fields else None
    team_col   = fields.index("CLUB")         if "CLUB"         in fields else 6

    riders = []
    for grp_key, rows in data.get("data", {}).items():
        contest_name = normalize_category_name(re.sub(r"^#\d+_", "", grp_key))
        if not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, list) or len(row) <= name_col:
                continue
            name_raw = str(row[name_col]).strip()
            if not name_raw:
                continue

            if gender_col is not None and len(row) > gender_col:
                g      = row[gender_col]
                gender = "Men" if g == "M" else ("Women" if g == "W" else "")
            else:
                gender = ""

            category = f"{gender} {contest_name}".strip() if gender else contest_name
            if not category_matches(category, category_filter):
                continue

            if "," in name_raw:
                last, first = (p.strip().title() for p in name_raw.split(",", 1))
            else:
                parts = name_raw.split(None, 1)
                last  = parts[0].title()
                first = parts[1].title() if len(parts) > 1 else ""

            country = _flag_to_country(str(row[flag_col])) if len(row) > flag_col else ""
            riders.append(Rider(
                first_name=first, last_name=last,
                country=country,
                birth_year=str(row[year_col]) if len(row) > year_col else "",
                team=str(row[team_col])       if len(row) > team_col else "",
                category=category,
                start_nr=str(row[0]).strip(),
            ))

    return riders


def _flag_to_country(flag_str: str) -> str:
    m = re.search(r"/flags/([A-Z]{2})\.svg", flag_str, re.IGNORECASE)
    return ISO2_TO_IOC.get(m.group(1).upper(), m.group(1).upper()) if m else ""
