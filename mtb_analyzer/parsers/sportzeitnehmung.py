import re
import time

from ..models import Rider
from ..utils import category_matches, fetch, normalize_country


def parse_sportzeitnehmung(url: str, category_filter: str = None) -> list:
    """Parses a sportzeitnehmung.at registrant list, following pagination (?start=N)."""
    riders   = []
    base_url = url.split("?")[0]
    page_num = 0

    while True:
        page_url = f"{base_url}?start={page_num * 20}" if page_num > 0 else base_url
        soup  = fetch(page_url)
        table = soup.find("table")
        if not table:
            break

        rows       = table.find_all("tr")
        new_riders = 0
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 6:
                continue
            first   = cols[0].get_text(strip=True)
            last    = cols[1].get_text(strip=True)
            race    = cols[2].get_text(strip=True)
            country = cols[4].get_text(strip=True)
            uci_id  = re.sub(r"\s+", "", cols[5].get_text(strip=True))
            team    = cols[6].get_text(strip=True) if len(cols) > 6 else ""

            if not first or not last:
                continue
            if not category_matches(race, category_filter):
                continue

            riders.append(Rider(
                first_name=first, last_name=last,
                country=normalize_country(country),
                uci_id=uci_id, team=team, category=race,
            ))
            new_riders += 1

        if new_riders == 0:
            break

        links      = [a.get("href", "") for a in soup.find_all("a", href=True)]
        next_start = (page_num + 1) * 20
        has_next   = any(f"start={next_start}" in lnk for lnk in links)
        if not has_next:
            break
        page_num += 1
        time.sleep(0.3)

    return riders
