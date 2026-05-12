from urllib.parse import urlparse

from ..config import NAME_CORRECTIONS, console
from ..utils import fetch
from .generic import parse_generic
from .gsheets import parse_gsheets
from .raceresult import parse_raceresult
from .runtix import parse_runtix
from .sportkrono import parse_sportkrono
from .sportzeitnehmung import parse_sportzeitnehmung
from .sportsoft import parse_sportsoft
from .stoperica import parse_stoperica
from .wowtiming import parse_wowtiming


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
    if "stoperica" in host:
        return "stoperica"
    if "sportsoft" in host:
        return "sportsoft"
    if "wowtiming" in host:
        return "wowtiming"
    return "unknown"


def _apply_name_corrections(riders: list) -> None:
    for rider in riders:
        correction = NAME_CORRECTIONS.get(rider.full_name)
        if correction:
            rider.first_name, rider.last_name = correction


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
    elif site == "stoperica":
        riders = parse_stoperica(url, category_filter)
    elif site == "sportsoft":
        riders = parse_sportsoft(url, category_filter)
    elif site == "wowtiming":
        riders = parse_wowtiming(url, category_filter)
    else:
        console.print("[yellow]Unknown website format — trying generic parser...[/yellow]")
        riders = parse_generic(soup_title, category_filter)

    _apply_name_corrections(riders)
    return riders, race_name


__all__ = [
    "detect_site",
    "parse_start_list",
    "parse_sportzeitnehmung",
    "parse_runtix",
    "parse_sportkrono",
    "parse_gsheets",
    "parse_raceresult",
    "parse_stoperica",
    "parse_sportsoft",
    "parse_wowtiming",
    "parse_generic",
]
