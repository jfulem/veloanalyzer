import csv
import re

import requests

from ..config import HEADERS, console
from ..models import Rider
from ..utils import category_matches, normalize_category_name


_GENDER_MAP = {"m": "Men", "ž": "Women", "male": "Men", "female": "Women"}


def parse_gsheets(url: str, category_filter: str = None) -> list:
    """
    Parses a Google Sheets published spreadsheet (pubhtml or pub CSV URL).
    Converts the URL to CSV export format for reliable parsing.

    Column names vary by sheet (different organizers use different languages/
    layouts), so columns are matched against a list of known aliases rather
    than one fixed name, e.g.:
      - last name:  Prezime | Last Name
      - first name: Ime | First Name
      - gender:     Spol (M/Ž) | Gender (Male/Female)
      - category:   Kategorija | Category
      - team:       Klub | Team Name
    Gender is mapped to Men/Women and combined with category, e.g. "Men Juniors".
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

    def col(row, *names):
        for name in names:
            try:
                return row[header.index(name)].strip()
            except (ValueError, IndexError):
                continue
        return ""

    riders = []
    for row in rows[1:]:
        if not row or not any(row):
            continue

        last  = col(row, "prezime", "last name").title()
        first = col(row, "ime", "first name").title()
        if not last and not first:
            continue

        spol       = col(row, "spol", "gender")
        kategorija = col(row, "kategorija", "category")
        gender     = _GENDER_MAP.get(spol.lower(), spol)
        category   = normalize_category_name(f"{gender} {kategorija}".strip() if gender else kategorija)

        uci_id      = re.sub(r"\s+", "", col(row, "uci id"))
        start_nr    = col(row, "#", "bib")
        team        = col(row, "klub", "team name", "team")
        nationality = col(row, "nationality", "country")

        if not category_matches(category, category_filter):
            continue

        riders.append(Rider(
            first_name=first, last_name=last,
            uci_id=uci_id, team=team, country=nationality,
            category=category, start_nr=start_nr,
        ))

    return riders
