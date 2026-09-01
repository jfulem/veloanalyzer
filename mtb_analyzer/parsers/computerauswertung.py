from ..config import console
from ..models import Rider
from ..utils import category_matches, fetch

# The "Category" column's leading code (e.g. "ME Elite Herren") is
# authoritative — the German words after it are not parsed. Maps straight to
# the canonical "<Gender> <Level>" strings races.yml's category: filters use.
_CAT_CODE_LABEL = {
    "ME": "Men Elite",
    "MJ": "Men Juniors",
    "WE": "Women Elite",
    "WJ": "Women Juniors",
    "MU": "Men U23",
    "WU": "Women U23",
}


def parse_computerauswertung(url: str, category_filter: str = None) -> list:
    """
    Parses a computerauswertung.at starterliste.php page.

    One flat HTML table holds every category together: a colspan=5 "titel"
    row (just a group label, no data) separates each block, and every rider
    row carries Name / UCI-ID / Nat. / Category / Team.

    Name is "Lastname Firstname" (space-separated, no comma), so a
    multi-word first or last name can't be told apart reliably — the same
    ambiguity raceresult.py's participants-mode fallback accepts, resolved
    the same way: the first word is the last name, the rest is the first
    name.
    """
    soup = fetch(url)

    table = None
    for t in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in t.find_all("th")]
        if "Name" in headers and "UCI-ID" in headers:
            table = t
            break
    if table is None:
        console.print("[red]computerauswertung: results table not found[/red]")
        return []

    riders = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != 5:
            continue  # header row (uses <th>) or a "titel" group-separator row

        name_raw, uci_id, nat, cat_raw, team = (c.get_text(strip=True) for c in cells)
        if not name_raw:
            continue

        code     = cat_raw.split(None, 1)[0] if cat_raw else ""
        category = _CAT_CODE_LABEL.get(code, cat_raw)
        if not category_matches(category, category_filter):
            continue

        parts = name_raw.split(None, 1)
        last  = parts[0]
        first = parts[1] if len(parts) > 1 else ""

        riders.append(Rider(
            first_name=first, last_name=last,
            country=nat, uci_id=uci_id, team=team, category=category,
        ))

    return riders
