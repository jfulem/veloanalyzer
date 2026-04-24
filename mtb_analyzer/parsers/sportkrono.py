from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from ..config import HEADERS, console
from ..models import Rider
from ..utils import category_matches, normalize_category_name


def parse_sportkrono(url: str, category_filter: str = None) -> list:
    """
    Parses a sportkrono.hu entry list via its internal AJAX API.
    Columns: Sorszám | Vezetéknév | Keresztnév | Egyesület | Város | Kategória
    No country or UCI ID available from this source.
    """
    parsed     = urlparse(url)
    event_id   = parsed.path.rstrip("/").split("/")[-1]
    path_parts = parsed.path.rstrip("/").split("/")
    app_prefix = "/".join(path_parts[:-2])
    api_url    = f"{parsed.scheme}://{parsed.netloc}{app_prefix}/ajax/feliratkozas/lista"

    try:
        resp = requests.post(api_url, data={"rendezveny": event_id},
                             headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        console.print(f"[red]Error fetching sportkrono data: {e}[/red]")
        return []

    if data.get("STATUS") != "OK":
        console.print("[red]sportkrono API returned non-OK status[/red]")
        return []

    soup  = BeautifulSoup(data["HTML"], "html.parser")
    table = soup.find("table")
    if not table:
        return []

    riders = []
    for row in table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if len(cols) < 6:
            continue
        start_nr = cols[0].get_text(strip=True).rstrip(".")
        last     = cols[1].get_text(strip=True)
        first    = cols[2].get_text(strip=True)
        team     = cols[3].get_text(strip=True)
        category = normalize_category_name(cols[5].get_text(strip=True))

        if not first or not last:
            continue
        if not category_matches(category, category_filter):
            continue

        riders.append(Rider(
            first_name=first, last_name=last,
            team=team, category=category, start_nr=start_nr,
        ))

    return riders
