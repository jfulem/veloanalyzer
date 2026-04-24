import re
import time

import requests
from bs4 import BeautifulSoup, NavigableString

from .config import CATEGORY_ALIASES, COUNTRY_NORMALIZE, HEADERS, console


def fetch(url: str, retries: int = 3, delay: float = 1.0) -> BeautifulSoup:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                console.print(f"[red]Error fetching {url}: {e}[/red]")
                raise


def normalize_country(raw: str) -> str:
    key = raw.strip().lower()
    if key in COUNTRY_NORMALIZE:
        return COUNTRY_NORMALIZE[key]
    for k, v in COUNTRY_NORMALIZE.items():
        if k in key:
            return v
    if re.match(r"^[A-Z]{3}$", raw.strip()):
        return raw.strip()
    return raw[:3].upper() if raw else "UNK"


def normalize_rider_name(raw: str) -> str:
    """Converts 'LASTNAME Firstname' → 'Firstname Lastname', handles ALL-CAPS last names."""
    raw = raw.strip()
    bracket_match = re.search(r"\[(.+?)\]", raw)
    if bracket_match:
        raw = bracket_match.group(1)
    parts = raw.split()
    if not parts:
        return raw
    if parts[0].isupper() and len(parts) > 1:
        last  = parts[0].title()
        first = " ".join(parts[1:])
        return f"{first} {last}"
    return raw


def normalize_category_name(name: str) -> str:
    """Replaces non-English category words with standard English equivalents."""
    return " ".join(CATEGORY_ALIASES.get(w.lower(), w) for w in name.split())


def category_matches(category_text: str, filter_str: str) -> bool:
    """
    Word-boundary aware category filter.

    Requires every word in filter_str to start at a word boundary in
    category_text, preventing 'Men Juniors' from matching 'Women Juniors'
    while still allowing 'Junior' to match 'Juniors'.
    """
    if not filter_str:
        return True
    haystack = re.sub(r"[^\w\s]", " ", category_text.lower())
    for word in filter_str.lower().split():
        if not re.search(rf"\b{re.escape(word)}", haystack):
            return False
    return True


def cell_direct_text(tag) -> str:
    """
    Returns only the direct text of a BeautifulSoup tag, ignoring child elements.
    Used for xcodata rank/points cells that embed change indicators in a child span.
    """
    return "".join(
        str(t) for t in tag.children if isinstance(t, NavigableString)
    ).strip()
