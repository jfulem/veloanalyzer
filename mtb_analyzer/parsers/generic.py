from bs4 import BeautifulSoup

from ..models import Rider


def parse_generic(soup: BeautifulSoup, category_filter: str = None) -> list:
    """Generic fallback parser — scans all tables for rider rows."""
    riders = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr")[1:]:
            cols  = row.find_all("td")
            if len(cols) < 2:
                continue
            texts = [c.get_text(strip=True) for c in cols]
            if texts[0] and texts[1] and not texts[0].isdigit():
                riders.append(Rider(first_name=texts[0], last_name=texts[1],
                                    country=texts[2] if len(texts) > 2 else ""))
    return riders
