import re
from urllib.parse import urlparse

import requests

from ..config import HEADERS, ISO2_TO_IOC, console
from ..models import Rider
from ..utils import category_matches, normalize_category_name


def parse_raceresult(url: str, category_filter: str = None) -> list:
    """
    Parses a my.raceresult.com participants page via the internal JSON API.
    Fetches /RRPublish/data/config for the API key, then /RRPublish/data/list.
    Data is grouped by category → gender subgroup.
    Row layout: [BIB, ID, rank, "Lastname, Firstname", flag_img, year, club, ...]
    Country is extracted from the flag SVG URL (ISO 2-letter → IOC 3-letter).
    Gender comes from subgroup name: männlich/M = Men, weiblich/W = Women.
    """
    parsed   = urlparse(url)
    event_id = parsed.path.strip("/").split("/")[0]
    base     = f"{parsed.scheme}://{parsed.netloc}/{event_id}/RRPublish/data"

    try:
        resp = requests.get(f"{base}/config", headers=HEADERS, timeout=20)
        resp.raise_for_status()
        config = resp.json()
    except Exception as e:
        console.print(f"[red]Error fetching raceresult config: {e}[/red]")
        return []

    key   = config.get("key", "")
    lists = config.get("lists", [])
    if not lists:
        console.print("[red]No lists found in raceresult config[/red]")
        return []

    try:
        resp = requests.get(f"{base}/list",
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


def _flag_to_country(flag_str: str) -> str:
    m = re.search(r"/flags/([A-Z]{2})\.svg", flag_str, re.IGNORECASE)
    return ISO2_TO_IOC.get(m.group(1).upper(), m.group(1).upper()) if m else ""
