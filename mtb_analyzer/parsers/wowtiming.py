from ..config import console
from ..models import Rider
from ..utils import category_matches, fetch

# Czech word → English for category normalization.
# Slash-separated categories (e.g. "Junioři/juniorky") are split on "/"
# before lookup, so each side is normalized independently then deduplicated.
_CZECH_WORD_MAP = {
    "junioři": "Juniors",
    "juniorky": "Juniors",
    "žactvo": "Youth",
    "žáci": "Boys",
    "žákyně": "Girls",
    "veteráni": "Veterans",
    "ženy": "Women",
    "muži": "Men",
    "kadeti": "Cadets",
    "kadetky": "Cadets",
    "elite": "Elite",
    "elita": "Elite",
    "dospělí": "Adults",
    "dospělý": "Adults",
    "děti": "Children",
    "masters": "Masters",
    "expert": "Expert",
}


def _normalize_category(raw: str) -> str:
    """
    Normalizes a Czech/mixed category string to English.
    Slash-separated genders ("Junioři/juniorky") are merged and deduplicated
    so they match either-gender filters while avoiding repeated words.
    """
    words = raw.replace("/", " ").split()
    seen: set[str] = set()
    out = []
    for w in words:
        mapped = _CZECH_WORD_MAP.get(w.lower(), w)
        key = mapped.lower()
        if key not in seen:
            out.append(mapped)
            seen.add(key)
    return " ".join(out)


def parse_wowtiming(url: str, category_filter: str = None) -> list:
    """
    Parses a wowtiming.cz start list page (WordPress plugin, fully server-rendered).

    The rider table (#myTable) has columns:
      # | Jméno (first) | Příjmení (last) | Ročník (year) | Kategorie | Team | Payment

    No nationality column — country is left blank.
    Czech category words are normalized to English; slash-separated mixed-gender
    categories (e.g. "Junioři/juniorky") collapse to a single gender-neutral term.
    """
    soup = fetch(url)

    table = soup.find("table", id="myTable")
    if not table:
        console.print("[yellow]wowtiming: #myTable not found[/yellow]")
        return []

    riders = []
    for row in table.find_all("tr"):
        if row.get("class") == ["header"]:
            continue
        cells = row.find_all("td")
        if len(cells) < 6:
            continue

        first_name = cells[1].get_text(strip=True)
        last_name = cells[2].get_text(strip=True)
        if not first_name and not last_name:
            continue

        czech_cat = cells[4].get_text(strip=True)
        english_cat = _normalize_category(czech_cat)
        if not category_matches(english_cat, category_filter):
            continue

        riders.append(Rider(
            first_name=first_name,
            last_name=last_name,
            birth_year=cells[3].get_text(strip=True),
            category=english_cat,
            team=cells[5].get_text(strip=True),
        ))

    return riders
