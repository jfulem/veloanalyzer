import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from ..config import console
from ..models import Rider
from ..utils import category_matches, fetch

_CATEGORY_MAP = {
    "junioři":    "Men Juniors",
    "juniorky":   "Women Juniors",
    "kadeti":     "Men Cadets",
    "kadetky":    "Women Cadets",
    "muži u23":   "Men U23",
    "ženy u23":   "Women U23",
    "muži elite": "Men Elite",
    "ženy elite": "Women Elite",
    "žáci i":     "Boys U13",
    "žáci ii":    "Boys U15",
    "žákyně i":   "Girls U13",
    "žákyně ii":  "Girls U15",
    "holky 5-6":  "Girls U6",
    "holky 7-8":  "Girls U8",
    "holky 9-10": "Girls U10",
    "kluci 5-6":  "Boys U6",
    "kluci 7-8":  "Boys U8",
    "kluci 9-10": "Boys U10",
    "odrážedla":  "Balance Bikes",
    "open 20-30": "Open",
}


def _unlock_url(url: str) -> str:
    """Add dohzormhenyh=1 to the URL if not already present."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    if "dohzormhenyh" not in qs:
        qs["dohzormhenyh"] = ["1"]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query, fragment=""))


def _find_startlist_table(soup):
    """Return the table that contains the rider start list (has 'Jméno' or 'Jméno' header)."""
    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if not header_row:
            continue
        headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]
        if "jméno" in headers or "jmeno" in " ".join(headers):
            return table, headers
    return None, []


def parse_hynekmusil(url: str, category_filter: str = None) -> list:
    """
    Parses a hynekmusil.cz event start list.

    The URL must contain the event ID parameter (rebmunyavd=N).
    The dohzormhenyh=1 parameter is added automatically to unlock the start list.

    Table columns: HDR, St.Číslo, Národnost, Jméno, Typ závodu, Kategorie, Obec/Klub, Platba
    Name format: LASTNAME Firstname (UCI-style all-caps last name)
    """
    unlocked_url = _unlock_url(url)
    soup = fetch(unlocked_url)

    table, headers = _find_startlist_table(soup)
    if table is None:
        console.print("[yellow]hynekmusil: no start list table found[/yellow]")
        return []

    try:
        name_idx = next(i for i, h in enumerate(headers) if "jm" in h)
        cat_idx  = next(i for i, h in enumerate(headers) if "kateg" in h)
    except StopIteration:
        console.print("[yellow]hynekmusil: could not locate name/category columns[/yellow]")
        return []

    nr_idx   = next((i for i, h in enumerate(headers) if "st." in h or "číslo" in h), None)
    team_idx = next((i for i, h in enumerate(headers) if "klub" in h or "obec" in h), None)

    riders = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) <= cat_idx:
            continue

        raw_cat     = cells[cat_idx].get_text(strip=True)
        english_cat = _CATEGORY_MAP.get(raw_cat.lower(), raw_cat)
        if not category_matches(english_cat, category_filter):
            continue

        raw_name = cells[name_idx].get_text(strip=True)
        if not raw_name:
            continue

        parts = raw_name.split()
        if parts and re.sub(r"[-]", "", parts[0]).isupper() and len(parts) > 1:
            last_name  = parts[0].title()
            first_name = " ".join(parts[1:])
        else:
            first_name = " ".join(parts[:-1])
            last_name  = parts[-1].title() if parts else ""

        start_nr = cells[nr_idx].get_text(strip=True) if nr_idx is not None and len(cells) > nr_idx else ""
        team     = cells[team_idx].get_text(strip=True) if team_idx is not None and len(cells) > team_idx else ""

        riders.append(Rider(
            first_name=first_name,
            last_name=last_name,
            start_nr=start_nr,
            team=team,
            category=english_cat,
        ))

    return riders
