import re

from ..config import ISO2_TO_IOC, console
from ..models import Rider
from ..utils import category_matches, fetch

# Croatian/stoperica category base names → English
_BASE_NORMALIZE = {
    "ELITE": "Elite",
    "JUNIORI": "Juniors",
    "JUNIOR": "Juniors",
    "MASTERS": "Masters",
    "MASTER": "Masters",
    "AMATEUR": "Amateur",
    "U23": "U23",
    "U17": "U17",
    "U15": "U15",
}


def _flag_emoji_to_ioc(emoji: str) -> str:
    """Convert a flag emoji like 🇭🇷 to IOC alpha-3 like 'CRO'."""
    indicators = [c for c in emoji if 0x1F1E6 <= ord(c) <= 0x1F1FF]
    if len(indicators) < 2:
        return "UNK"
    iso2 = chr(ord(indicators[0]) - 0x1F1E6 + ord("A")) + chr(ord(indicators[1]) - 0x1F1E6 + ord("A"))
    return ISO2_TO_IOC.get(iso2, iso2[:3].upper())


def _parse_category(raw: str) -> str:
    """
    Convert stoperica raw category text to standard English.
    'ELITE M'    → 'Men Elite'
    'JUNIORI W'  → 'Women Juniors'
    """
    # Strip everything from the count "(N)" onwards (includes MDL icon text)
    cat = re.sub(r"\s*\(\d+\).*", "", raw, flags=re.DOTALL).strip()
    parts = cat.split()
    if not parts:
        return cat

    if parts[-1] == "M":
        gender, base_parts = "Men", parts[:-1]
    elif parts[-1] == "W":
        gender, base_parts = "Women", parts[:-1]
    else:
        gender, base_parts = "", parts

    base = " ".join(_BASE_NORMALIZE.get(p.upper(), p.title()) for p in base_parts)
    return f"{gender} {base}".strip() if gender else base


def parse_stoperica(url: str, category_filter: str = None) -> list:
    """
    Parses a stoperica.live race page (fully server-rendered MDL grid layout).

    Structure: each category is a div.cat-N with an onclick pointing to a sibling
    div#collapse-N that holds the rider rows.

    Row layout (cells): empty | empty | UCI ID | name+flag | club | status | time
    """
    soup = fetch(url)
    riders = []

    cat_divs = soup.find_all(
        "div", class_=lambda c: c and any(cls.startswith("cat-") for cls in c.split())
    )

    if not cat_divs:
        console.print("[yellow]stoperica: no category sections found[/yellow]")
        return []

    for cat_div in cat_divs:
        trigger = cat_div.find("div", class_="collapse-trigger")
        if not trigger:
            continue

        category = _parse_category(trigger.get_text(" ", strip=True))
        if not category_matches(category, category_filter):
            continue

        # The collapse div is a sibling; its id is embedded in the onclick attribute.
        onclick = cat_div.get("onclick", "")
        m = re.search(r"'#(collapse-[\w-]+)'", onclick)
        if not m:
            continue
        collapse = soup.find("div", id=m.group(1))
        if not collapse:
            continue

        for row in collapse.find_all("div", class_="mdl-grid"):
            cells = row.find_all("div", class_="mdl-cell", recursive=False)
            # Expect at least 5 cells: _, _, UCI ID, name+flag, club
            if len(cells) < 5:
                continue

            # Cell 2: UCI ID (inside <b>)
            uci_raw = cells[2].get_text(strip=True)
            if not uci_raw.isdigit():
                continue
            uci_id = uci_raw

            # Cell 3: flag emoji + "LASTNAME Firstname" (inside <a>)
            name_cell = cells[3]
            emoji_div = name_cell.find("div", class_="emoji")
            flag_emoji = emoji_div.get_text(strip=True) if emoji_div else ""
            full_text = name_cell.get_text(strip=True)
            raw_name = (
                full_text[len(flag_emoji):].strip()
                if flag_emoji and full_text.startswith(flag_emoji)
                else full_text
            )
            if not raw_name:
                continue

            # "LASTNAME Firstname" → last name is the first ALL-CAPS token
            parts = raw_name.split()
            if parts and parts[0].replace("-", "").isupper():
                last_name = parts[0].title()
                first_name = " ".join(parts[1:])
            else:
                first_name = " ".join(parts[:-1])
                last_name = parts[-1].title() if parts else ""

            country = _flag_emoji_to_ioc(flag_emoji) if flag_emoji else "UNK"

            # Cell 4: club
            team = cells[4].get_text(strip=True)

            riders.append(Rider(
                first_name=first_name,
                last_name=last_name,
                country=country,
                uci_id=uci_id,
                team=team,
                category=category,
            ))

    return riders
