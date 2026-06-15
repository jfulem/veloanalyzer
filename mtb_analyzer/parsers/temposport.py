import re

from ..config import console
from ..models import Rider
from ..utils import category_matches, fetch

_CATEGORY_MAP = {
    "xcoelit férfi":     "Men Elite",
    "xcoelit nő":        "Women Elite",
    "xcou19 férfi":      "Men Juniors",
    "xcou19 nő":         "Women Juniors",
    "xcou17 férfi":      "Men Cadets",
    "xcou17 lány":       "Women Cadets",
    "xcou15 fiú":        "Boys U15",
    "xcou15 lány":       "Girls U15",
    "xcou13 fiú":        "Boys U13",
    "xcou13 lány":       "Girls U13",
    "xcou11 fiú":        "Boys U11",
    "xcou11 lány":       "Girls U11",
    "xcou9 fiú":         "Boys U9",
    "xcou9 lány":        "Girls U9",
    "xcomaster 1 férfi": "Masters A",
    "xcomaster 1 nő":    "Women Masters A",
    "xcomaster 2 férfi": "Masters B",
    "xcomaster 2 nő":    "Women Masters B",
    "xcomaster 3 férfi": "Masters C",
    "xcomaster 3 nő":    "Women Masters C",
    "xcomaster 4 férfi": "Masters D",
    "xcomaster 4 nő":    "Women Masters D",
}


def _parse_name(raw: str) -> tuple:
    """
    Parse Hungarian name (last name first) into (first_name, last_name).

    Hungarian format: "LASTNAME Firstname" or "LASTNAME  Firstname" (double space).
    All-caps names are normalized to Title Case.
    """
    parts = raw.split()
    if not parts:
        return "", ""
    last  = parts[0].title() if parts[0].isupper() else parts[0]
    first = " ".join(
        p.title() if p.isupper() else p
        for p in parts[1:]
    )
    return first, last


def parse_temposport(url: str, category_filter: str = None) -> list:
    """
    Parses a temposport.hu várolista (waiting list / start list) page.

    Table columns: Név (Name), Szül. év (Birth year), Egyesület (Team), Kategória (Category)
    Name order: last name first (Hungarian convention).
    """
    soup = fetch(url)

    table = soup.find("table")
    if not table:
        console.print("[yellow]temposport: no table found on page[/yellow]")
        return []

    rows = table.find_all("tr")
    if not rows:
        return []

    header_cells = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th", "td"])]
    try:
        name_idx  = next(i for i, h in enumerate(header_cells) if "név" in h)
        year_idx  = next(i for i, h in enumerate(header_cells) if "szül" in h)
        team_idx  = next(i for i, h in enumerate(header_cells) if "egyes" in h)
        cat_idx   = next(i for i, h in enumerate(header_cells) if "kateg" in h)
    except StopIteration:
        console.print("[yellow]temposport: could not identify expected columns[/yellow]")
        return []

    riders = []
    for row in rows[1:]:
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

        first_name, last_name = _parse_name(raw_name)
        birth_year = cells[year_idx].get_text(strip=True) if len(cells) > year_idx else ""
        team       = cells[team_idx].get_text(strip=True) if len(cells) > team_idx else ""

        riders.append(Rider(
            first_name=first_name,
            last_name=last_name,
            birth_year=birth_year,
            team=team,
            category=english_cat,
        ))

    return riders
