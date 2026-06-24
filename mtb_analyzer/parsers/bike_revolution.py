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

    The event ID is configured per-year via Storyblok CMS. The live value for
    this exact page is in its prerendered Nuxt static payload
    (/_nuxt/static/<buildId>/<path>/payload.js, preloaded via a <link> tag in
    the HTML) as `eventId:"NNNNNN"`.

    NB: the Nuxt component source also has a hardcoded fallback default
    (`this.blok.eventId || NNNNNN`) baked into its JS chunk — that fallback is
    whatever event ID existed when the component was last built (e.g. last
    year's), so it must NOT be used as a discovery source: it silently returns
    a plausible-looking but stale event ID instead of the current one.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        console.print(f"[red]bike-revolution: error fetching page: {e}[/red]")
        return None

    html = resp.text
    base = f"https://{requests.utils.urlparse(url).netloc}"

    # 1. Nuxt static payload for this page — the actual current Storyblok
    #    content, including this year's eventId.
    for path in re.findall(r'href="(/_nuxt/static/[^"]+/payload\.js)"', html):
        try:
            pr = requests.get(base + path, headers=HEADERS, timeout=10)
            m = re.search(r'eventId:"(\d{5,6})"', pr.text)
            if m:
                return m.group(1)
        except Exception:
            continue

    # 2. Iframe src  my.raceresult.com/NNNNN/...
    m = re.search(r'my\.raceresult\.com/(\d{5,6})/', html)
    if m:
        return m.group(1)

    # 3. data-event-id or data-rr-event-id attribute
    m = re.search(r'data-(?:rr-)?event-id=["\'](\d{5,6})["\']', html, re.I)
    if m:
        return m.group(1)

    # 4. JS variable RREventId = NNNNNN
    m = re.search(r'\bRREventId\s*[=:]\s*(\d{5,6})\b', html)
    if m:
        return m.group(1)

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
