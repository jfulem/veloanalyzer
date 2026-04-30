import requests
from bs4 import BeautifulSoup

from ..config import HEADERS, console
from ..models import Rider
from ..utils import category_matches

# Czech/Slovak category names → standard English
_CATEGORY_MAP = {
    # Czech (with diacritics)
    "Junioři": "Men Juniors",
    "Juniorky": "Women Juniors",
    "Kadeti": "Men Cadets",
    "Kadetky": "Women Cadets",
    "Muži Elite a U 23": "Men Elite",
    "Muži Elite": "Men Elite",
    "Ženy Elite a U23": "Women Elite",
    "Ženy Elite": "Women Elite",
    "Expert": "Expert",
    "Masters": "Masters",
    "Masters A": "Masters A",
    "Masters B": "Masters B",
    "Masters C": "Masters C",
    "Žáci I": "Boys U13",
    "Žáci II": "Boys U15",
    "Žákyně I": "Girls U13",
    "Žákyně II": "Girls U15",
    "Kluci 5-6 let": "Boys U6",
    "Kluci 7-8 let": "Boys U8",
    "Kluci 9-10 let": "Boys U10",
    "Holky 5-6 let": "Girls U6",
    "Holky 7-8 let": "Girls U8",
    "Holky 9-10 let": "Girls U10",
    # Slovak (without háček on Junior/Kadett)
    "Juniori": "Men Juniors",
    "Kadeti": "Men Cadets",
    "Ženy Masters": "Women Masters",
    "Mini chlapci": "Boys Mini",
    "Mini dievčatá": "Girls Mini",
    "Mladší žiaci": "Young Boys",
    "Mladšie žiačky": "Young Girls",
    "Starší žiaci": "Older Boys",
    "Staršie žiačky": "Older Girls",
}

# ISO 3166-1 alpha-3 codes that differ from IOC alpha-3
_ISO3_TO_IOC = {
    "ROU": "ROM",
    "DEU": "GER",
    "NLD": "NED",
    "CHE": "SUI",
    "DNK": "DEN",
    "GRC": "GRE",
}


def parse_sportsoft(url: str, category_filter: str = None) -> list:
    """
    Parses a registrace.sportsoft.cz start list page (ASP.NET WebForms).

    The rider table is only rendered after an HTTP POST with the ASP.NET
    state fields and clicking the OK button. All courses are fetched at once
    (Filtr = -1) and filtered client-side.

    Row layout: Name | Year | Club | Nat. | Course | Category | Payment | —
    Country codes on the site are mostly IOC alpha-3; known ISO3 differences
    (e.g. ROU → ROM) are remapped.
    """
    s = requests.Session()
    try:
        resp = s.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        console.print(f"[red]Error fetching sportsoft page: {e}[/red]")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Collect ASP.NET postback state from hidden inputs
    def _hv(name: str) -> str:
        el = soup.find("input", {"name": name})
        return el["value"] if el else ""

    # Find the course-select and submit button names dynamically
    sel_el = soup.find("select", id=lambda i: i and "Filtr" in i and "Tab" not in i)
    btn_el = soup.find("input", type="submit", id=lambda i: i and "BtnFiltr" in i)
    txt_el = soup.find("input", type="text")

    if not sel_el or not btn_el:
        console.print("[yellow]sportsoft: could not find filter form elements[/yellow]")
        return []

    post_data = {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": _hv("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": _hv("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": _hv("__EVENTVALIDATION"),
        sel_el["name"]: "-1",         # all courses
        btn_el["name"]: btn_el.get("value", "OK"),
    }
    if txt_el:
        post_data[txt_el["name"]] = ""

    try:
        resp2 = s.post(url, data=post_data, headers=HEADERS, timeout=30)
        resp2.raise_for_status()
    except Exception as e:
        console.print(f"[red]Error posting to sportsoft: {e}[/red]")
        return []

    soup2 = BeautifulSoup(resp2.text, "html.parser")
    table = soup2.find("table", id=lambda i: i and "Tab1" in i)
    if not table:
        console.print("[yellow]sportsoft: no rider table in response[/yellow]")
        return []

    # Read header to locate columns (layout varies: optional St.no. column)
    header_row = table.find("tr", class_="zahlavi")
    if header_row:
        col = {th.get_text(strip=True).lower(): i
               for i, th in enumerate(header_row.find_all("th"))}
    else:
        col = {}
    name_idx    = col.get("name",   0)
    year_idx    = col.get("year",   1)
    club_idx    = col.get("club",   2)
    nat_idx     = col.get("nat.",   3)
    course_idx  = col.get("course", 4)

    riders = []
    for row in table.find_all("tr", class_=["licha", "suda"]):
        cells = row.find_all("td")
        if len(cells) <= course_idx:
            continue

        czech_cat = cells[course_idx].get_text(strip=True)
        english_cat = _CATEGORY_MAP.get(czech_cat, czech_cat)
        if not category_matches(english_cat, category_filter):
            continue

        raw_name = cells[name_idx].get_text(strip=True)
        parts = raw_name.split()
        if parts and parts[0].replace("-", "").isupper():
            last_name = parts[0].title()
            first_name = " ".join(parts[1:])
        else:
            first_name = " ".join(parts[:-1])
            last_name = parts[-1].title() if parts else ""

        raw_cc = cells[nat_idx].get_text(strip=True)
        country = _ISO3_TO_IOC.get(raw_cc, raw_cc)

        riders.append(Rider(
            first_name=first_name,
            last_name=last_name,
            country=country,
            birth_year=cells[year_idx].get_text(strip=True),
            team=cells[club_idx].get_text(strip=True),
            category=english_cat,
        ))

    return riders
