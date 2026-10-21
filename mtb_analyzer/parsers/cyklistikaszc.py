import re

from ..models import Rider
from ..utils import category_matches, fetch

# 'Juniori MEN JUNIORS', 'Ženy WOMEN ELITE': the Slovak label, then the English
# one in capitals. Youth classes carry no English half ('Kadeti U17', 'Nábor')
# and keep their Slovak label, which no tracked category filter matches.
_ENGLISH_RE = re.compile(r"\b((?:WO)?MEN(?: [A-Z0-9]+)+)$")

# 'Niklas  MITTERBACHER [URC Bikerei/Vlow Racing Team]' — the surname is the
# trailing capitalised run, and the team bracket may be missing.
_ENTRY_RE = re.compile(r"^(?P<name>[^\[]+?)\s*(?:\[(?P<team>[^\]]*)\])?$")


def _category(heading: str) -> str:
    m = _ENGLISH_RE.search(heading)
    return m.group(1).title() if m else heading


def _split_name(name: str) -> tuple:
    """('Olivér Péter', 'Laczkó') from 'Olivér Péter LACZKÓ'."""
    parts = name.split()
    i = len(parts)
    while i > 1 and parts[i - 1].isupper():
        i -= 1
    if i == len(parts):  # no capitalised surname — take the last word
        i = len(parts) - 1
    return " ".join(parts[:i]), " ".join(parts[i:]).title()


def parse_cyklistikaszc(url: str, category_filter: str = None) -> list:
    """
    Parses a Slovak Cycling Federation (cyklistikaszc.sk) entry list —
    /kalendar-vysledky/zoznam-prihlasenych-pretekarov/<id>.

    Not a table: each category is an <h3> followed by one
    <div class="bg-gray"> per rider reading 'First LAST [Team]'. The list
    publishes no start number, nationality, birth year or UCI ID.
    """
    soup = fetch(url)

    riders = []
    for heading in soup.find_all("h3"):
        category = _category(heading.get_text(" ", strip=True))
        if not category_matches(category, category_filter):
            continue

        entry = heading.find_next_sibling()
        while entry is not None and entry.name == "div" and "bg-gray" in (entry.get("class") or []):
            m = _ENTRY_RE.match(entry.get_text(" ", strip=True))
            entry = entry.find_next_sibling()
            if not m:
                continue
            first_name, last_name = _split_name(m.group("name"))
            if not last_name:
                continue
            riders.append(Rider(
                first_name=first_name,
                last_name=last_name,
                team=" ".join((m.group("team") or "").split()),
                category=category,
            ))

    return riders
