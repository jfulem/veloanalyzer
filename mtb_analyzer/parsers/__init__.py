from urllib.parse import urlparse

from ..config import console
from ..utils import fetch
from .generic import parse_generic
from .gsheets import parse_gsheets
from .raceresult import parse_raceresult
from .runtix import parse_runtix
from .sportkrono import parse_sportkrono
from .sportzeitnehmung import parse_sportzeitnehmung


def detect_site(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "sportzeitnehmung" in host:
        return "sportzeitnehmung"
    if "runtix" in host:
        return "runtix"
    if "sportkrono" in host:
        return "sportkrono"
    if "docs.google.com" in host and "spreadsheets" in url:
        return "gsheets"
    if "raceresult" in host:
        return "raceresult"
    return "unknown"


def parse_start_list(url: str, category_filter: str = None) -> tuple:
    """Auto-detects the website format and returns (riders, race_name)."""
    site = detect_site(url)
    console.print(f"[dim]Detected format: {site} — {url}[/dim]")

    soup_title = fetch(url)
    race_name  = soup_title.title.get_text(strip=True) if soup_title.title else url

    if site == "sportzeitnehmung":
        riders = parse_sportzeitnehmung(url, category_filter)
    elif site == "runtix":
        riders = parse_runtix(url, category_filter)
    elif site == "sportkrono":
        riders = parse_sportkrono(url, category_filter)
    elif site == "gsheets":
        riders = parse_gsheets(url, category_filter)
    elif site == "raceresult":
        riders = parse_raceresult(url, category_filter)
    else:
        console.print("[yellow]Unknown website format — trying generic parser...[/yellow]")
        riders = parse_generic(soup_title, category_filter)

    return riders, race_name


__all__ = [
    "detect_site",
    "parse_start_list",
    "parse_sportzeitnehmung",
    "parse_runtix",
    "parse_sportkrono",
    "parse_gsheets",
    "parse_raceresult",
    "parse_generic",
]
