import csv
import re

import requests

from ..config import HEADERS, console
from ..models import Rider
from ..utils import category_matches, normalize_category_name


def parse_gsheets(url: str, category_filter: str = None) -> list:
    """
    Parses a Google Sheets published spreadsheet (pubhtml or pub CSV URL).
    Converts the URL to CSV export format for reliable parsing.
    Expected columns: # | UCI ID | Prezime (last) | Ime (first) | Spol (M/Ž) | Kategorija | Klub
    Spol is mapped to Men/Women and combined with Kategorija: e.g. "Men Juniors".
    """
    csv_url = re.sub(r"/pubhtml\b", "/pub", url)
    if "output=csv" not in csv_url:
        sep = "&" if "?" in csv_url else "?"
        csv_url += f"{sep}output=csv"

    try:
        resp = requests.get(csv_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        console.print(f"[red]Error fetching Google Sheets data: {e}[/red]")
        return []

    reader = csv.reader(resp.content.decode("utf-8-sig").splitlines())
    rows   = list(reader)
    if not rows:
        return []

    header = [h.strip().lower() for h in rows[0]]

    def col(row, name):
        try:
            return row[header.index(name)].strip()
        except (ValueError, IndexError):
            return ""

    riders = []
    for row in rows[1:]:
        if not row or not any(row):
            continue

        last  = col(row, "prezime").title()
        first = col(row, "ime").title()
        if not last and not first:
            continue

        spol       = col(row, "spol")
        kategorija = col(row, "kategorija")
        gender     = "Men" if spol == "M" else ("Women" if spol == "Ž" else spol)
        category   = normalize_category_name(f"{gender} {kategorija}".strip() if gender else kategorija)

        uci_id   = re.sub(r"\s+", "", col(row, "uci id"))
        start_nr = col(row, "#")
        team     = col(row, "klub")

        if not category_matches(category, category_filter):
            continue

        riders.append(Rider(
            first_name=first, last_name=last,
            uci_id=uci_id, team=team,
            category=category, start_nr=start_nr,
        ))

    return riders
