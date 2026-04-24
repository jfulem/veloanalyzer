import re

from ..models import Rider
from ..utils import category_matches, fetch, normalize_country


def parse_runtix(url: str, category_filter: str = None) -> list:
    """
    Parses a runtix.com start list.
    Name formats: 'LASTNAME, Firstname' or 'LASTNAME Firstname'.
    No UCI IDs available — ranking resolved via fuzzy name matching.
    """
    soup             = fetch(url)
    riders           = []
    current_category = ""

    for element in soup.find_all(["h2", "h3", "table"]):
        if element.name in ("h2", "h3"):
            current_category = element.get_text(strip=True)
            continue

        if element.name != "table":
            continue

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

            name_cell  = cols[1]
            lines      = [l.strip() for l in name_cell.get_text("\n").split("\n") if l.strip()]
            if not lines:
                continue

            raw_name   = lines[0]
            team       = lines[1] if len(lines) > 1 else ""
            birth_year = cols[2].get_text(strip=True) if len(cols) > 2 else ""
            nationality = cols[3].get_text(strip=True) if len(cols) > 3 else ""

            first, last = _parse_name(raw_name)
            riders.append(Rider(
                first_name=first, last_name=last,
                country=normalize_country(nationality),
                team=team, category=current_category,
                birth_year=birth_year, start_nr=start_nr,
            ))

    return riders


def _parse_name(raw: str) -> tuple:
    """'LASTNAME, Firstname' or 'LASTNAME Firstname' → (Firstname, Lastname)."""
    raw = raw.strip()
    if "," in raw:
        parts = raw.split(",", 1)
        return parts[1].strip().title(), parts[0].strip().title()
    parts = raw.split()
    if not parts:
        return "", ""
    if len(parts) >= 2:
        if parts[0].isupper() or parts[0] == parts[0].upper():
            return " ".join(p.title() for p in parts[1:]), parts[0].title()
        return parts[0], " ".join(parts[1:])
    return "", parts[0].title()
