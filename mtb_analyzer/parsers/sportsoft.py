import requests
from bs4 import BeautifulSoup
from urllib.parse import urldefrag

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


def _parse_rows(table, col: dict, category_filter) -> list:
    """Extract Rider objects from one page of the sportsoft table."""
    name_idx   = col.get("name",   0)
    year_idx   = col.get("year",   1)
    club_idx   = col.get("club",   None)
    nat_idx    = col.get("nat.",   3)
    course_idx = col.get("course", 4)

    riders = []
    for row in table.find_all("tr", class_=["licha", "suda"]):
        cells = row.find_all("td")
        if len(cells) <= course_idx:
            continue

        czech_cat   = cells[course_idx].get_text(strip=True)
        english_cat = _CATEGORY_MAP.get(czech_cat, czech_cat)
        if not category_matches(english_cat, category_filter):
            continue

        raw_name = cells[name_idx].get_text(strip=True)
        parts    = raw_name.split()
        if parts and parts[0].replace("-", "").isupper():
            last_name  = parts[0].title()
            first_name = " ".join(parts[1:])
        else:
            first_name = " ".join(parts[:-1])
            last_name  = parts[-1].title() if parts else ""

        raw_cc  = cells[nat_idx].get_text(strip=True)
        country = _ISO3_TO_IOC.get(raw_cc, raw_cc)

        team = cells[club_idx].get_text(strip=True) if club_idx is not None and len(cells) > club_idx else ""

        riders.append(Rider(
            first_name=first_name,
            last_name=last_name,
            country=country,
            birth_year=cells[year_idx].get_text(strip=True),
            team=team,
            category=english_cat,
        ))
    return riders


def _max_page(table) -> int:
    """Return the highest page number found in the pagination row, or 1."""
    paging = table.find("tr", class_="strankovani")
    if not paging:
        return 1
    pages = []
    for a in paging.find_all("a", href=True):
        import re
        m = re.search(r"Page\$(\d+)", a["href"])
        if m:
            pages.append(int(m.group(1)))
    return max(pages) if pages else 1


def parse_sportsoft(url: str, category_filter: str = None) -> list:
    """
    Parses a registrace.sportsoft.cz start list page (ASP.NET WebForms).

    Single-race pages (startlist.aspx?e=N): returns riders with no race_name set.
    Multi-race meeting pages (mstartlist.aspx?m=N): iterates every race in the
    Zavod dropdown and sets rider.race_name to the race label for each group.
    """
    s = requests.Session()
    try:
        resp = s.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        console.print(f"[red]Error fetching sportsoft page: {e}[/red]")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    def _hv(soup_: BeautifulSoup, name: str) -> str:
        el = soup_.find("input", {"name": name})
        return el["value"] if el else ""

    # Course-filter select: older pages use "Filtr", multi-race meeting pages use "Trat"
    sel_el = (
        soup.find("select", id=lambda i: i and "Filtr" in i and "Tab" not in i)
        or soup.find("select", id=lambda i: i and "Trat" in i)
    )
    btn_el = soup.find("input", type="submit", id=lambda i: i and "BtnFiltr" in i)
    txt_el = soup.find("input", type="text")

    if not sel_el or not btn_el:
        console.print("[yellow]sportsoft: could not find filter form elements[/yellow]")
        return []

    base_data = {sel_el["name"]: "-1"}  # all courses
    if txt_el:
        base_data[txt_el["name"]] = ""

    zavod_el = soup.find("select", id=lambda i: i and "Zavod" in i)
    race_options = []
    if zavod_el:
        race_options = [
            (opt["value"], opt.get_text(strip=True))
            for opt in zavod_el.find_all("option")
            if opt.get("value")
        ]

    def _post(current_soup: BeautifulSoup, event_target: str, event_arg: str,
              extra: dict = None) -> BeautifulSoup:
        data = {
            "__EVENTTARGET":        event_target,
            "__EVENTARGUMENT":      event_arg,
            "__VIEWSTATE":          _hv(current_soup, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": _hv(current_soup, "__VIEWSTATEGENERATOR"),
            "__EVENTVALIDATION":    _hv(current_soup, "__EVENTVALIDATION"),
            **base_data,
            **(extra or {}),
        }
        r = s.post(url, data=data, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")

    def _fetch_race(race_soup: BeautifulSoup, race_label: str) -> list:
        """Click BtnFiltr and paginate; tag every rider with race_label."""
        try:
            page_soup = _post(race_soup, "", "",
                              extra={btn_el["name"]: btn_el.get("value", "OK")})
        except Exception as e:
            console.print(f"[red]sportsoft: error fetching '{race_label}': {e}[/red]")
            return []

        table = page_soup.find("table", id=lambda i: i and "Tab1" in i)
        if not table:
            console.print(f"[yellow]sportsoft: no table for '{race_label}'[/yellow]")
            return []

        header_row = table.find("tr", class_="zahlavi")
        col = ({th.get_text(strip=True).lower(): i
                for i, th in enumerate(header_row.find_all("th"))}
               if header_row else {})
        grid_name = table["id"].replace("_", "$")

        riders = _parse_rows(table, col, category_filter)
        for r in riders:
            r.race_name = race_label

        total_pages = _max_page(table)
        for page_num in range(2, total_pages + 1):
            try:
                page_soup = _post(page_soup, grid_name, f"Page${page_num}")
            except Exception as e:
                console.print(f"[yellow]sportsoft: page {page_num} error: {e}[/yellow]")
                break
            table = page_soup.find("table", id=lambda i: i and "Tab1" in i)
            if not table:
                break
            more = _parse_rows(table, col, category_filter)
            for r in more:
                r.race_name = race_label
            riders.extend(more)

        return riders

    if len(race_options) > 1:
        # Multi-race meeting: iterate every race in the Zavod dropdown.
        # Each race is fetched by posting a Zavod-change postback from the
        # initial (clean) soup, then clicking BtnFiltr.
        all_riders = []
        for race_val, race_label in race_options:
            base_data[zavod_el["name"]] = race_val
            try:
                race_soup = _post(soup, zavod_el["name"], "")
            except Exception as e:
                console.print(f"[red]sportsoft: error selecting '{race_label}': {e}[/red]")
                continue
            all_riders.extend(_fetch_race(race_soup, race_label))
        return all_riders

    # Single-race: optionally honour a URL fragment to pick a specific race.
    if race_options:
        default_val = next(
            (opt["value"] for opt in zavod_el.find_all("option") if opt.get("selected")),
            race_options[0][0],
        )
        _, fragment = urldefrag(url)
        desired_val = fragment if fragment else default_val
        base_data[zavod_el["name"]] = desired_val
        if desired_val != default_val:
            try:
                soup = _post(soup, zavod_el["name"], "")
            except Exception as e:
                console.print(f"[red]sportsoft: error selecting race: {e}[/red]")
                return []

    return _fetch_race(soup, "")
