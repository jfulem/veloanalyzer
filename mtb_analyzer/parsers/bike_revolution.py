import re

import requests

from ..config import HEADERS, console
from ..models import Rider
from ..utils import category_matches
from .raceresult import parse_raceresult


def _find_raceresult_event_id(url: str) -> str | None:
    """
    Fetch the bike-revolution.ch startlisten page and look for an embedded
    RaceResult event ID.  Returns the event ID string if found, else None.

    The event ID is configured via Storyblok CMS and rendered into the Nuxt.js
    component as `this.blok.eventId || <fallback>`.  It may appear in:
      - The initial HTML:   iframe src, data-event-id attribute, JS variable
      - Preloaded JS chunks: eventId||NNNNNN pattern in the Nuxt component
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        console.print(f"[red]bike-revolution: error fetching page: {e}[/red]")
        return None

    html = resp.text

    # 1. Iframe src  my.raceresult.com/NNNNN/...
    m = re.search(r'my\.raceresult\.com/(\d{5,6})/', html)
    if m:
        return m.group(1)

    # 2. data-event-id or data-rr-event-id attribute
    m = re.search(r'data-(?:rr-)?event-id=["\'](\d{5,6})["\']', html, re.I)
    if m:
        return m.group(1)

    # 3. JS variable RREventId = NNNNNN
    m = re.search(r'\bRREventId\s*[=:]\s*(\d{5,6})\b', html)
    if m:
        return m.group(1)

    # 4. Search preloaded Nuxt.js chunks for the Storyblok component default:
    #    this.blok.eventId||NNNNNN
    base = re.sub(r'/[^/]*$', '', url.rstrip('/'))  # base URL of the site
    base = f"https://{requests.utils.urlparse(url).netloc}"
    chunk_urls = re.findall(r'href=["\']([^"\']+\.js)["\']', html)
    for chunk_path in chunk_urls:
        chunk_url = chunk_path if chunk_path.startswith('http') else base + chunk_path
        try:
            cr = requests.get(chunk_url, headers=HEADERS, timeout=10)
            cm = re.search(r'eventId\s*\|\|\s*(\d{5,6})', cr.text)
            if cm:
                return cm.group(1)
        except Exception:
            continue

    return None


def parse_bike_revolution(url: str, category_filter: str = None) -> list:
    """
    Parses the bike-revolution.ch start list page.

    The start list is embedded via a RaceResult.com widget whose event ID is
    injected by Storyblok CMS when the list is officially published.  This
    parser auto-detects the event ID and delegates to the raceresult parser.

    Until the start list is published (typically 5-7 days before the race),
    this returns an empty list.
    """
    event_id = _find_raceresult_event_id(url)
    if not event_id:
        console.print(
            "[yellow]bike-revolution: RaceResult event ID not found — "
            "start list may not be published yet[/yellow]"
        )
        return []

    console.print(f"[dim]bike-revolution: delegating to raceresult event {event_id}[/dim]")
    rr_url = f"https://my.raceresult.com/{event_id}/participants"
    return parse_raceresult(rr_url, category_filter)
