"""Persistence layer — writes enriched riders into Postgres.

Replaces export_db.py. The substantive difference is rider identity: a start
list gives us a name and sometimes a UCI ID, and the same person must resolve
to the same `riders` row across every race they enter, otherwise global search
and rider profiles show the same athlete several times.
"""

import re
from datetime import date, datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from .config import console
from .db import get_engine
from .ranking import _strip_diacritics
from .schema import meta, race_entries, races, rider_results, riders

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}

_RESULT_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})")


def parse_result_date(s: str) -> date | None:
    """Parse a UCI display date — "07 Jun 2026", or "01 - 02 Apr 2023" for a
    multi-day event — into a real date. Mirrors parseResultDate() in
    frontend/src/utils.ts: the last match wins, so ranges yield the end date.
    Returns None when nothing parses, which is stored as NULL.
    """
    hits = _RESULT_DATE_RE.findall(s or "")
    if not hits:
        return None
    day, mon, year = hits[-1]
    month = _MONTHS.get(mon.title())
    if not month:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def parse_iso_date(s: str) -> date | None:
    try:
        return date.fromisoformat((s or "").strip())
    except ValueError:
        return None


def normalize_name(first: str, last: str) -> str:
    """Diacritic-stripped, lowercased "first last" — the fallback identity key.
    Uses the same _strip_diacritics as the start-list merge in pipeline.py so
    the two agree on who counts as the same rider."""
    return f"{_strip_diacritics(first or '').strip()} {_strip_diacritics(last or '').strip()}".strip().lower()


def _resolve_rider(conn: Connection, rider) -> int:
    """Find or create the global `riders` row for this start-list entry.

    UCI ID wins when present. Otherwise we fall back to name + birth year, with
    two allowances for the fact that start lists are inconsistent about what
    they publish:

      * a rider previously seen without a UCI ID gets it backfilled rather than
        duplicated once a list supplies one;
      * a birth year of "" matches a single same-named rider, and a known birth
        year adopts an earlier "" row rather than forking it.
    """
    norm = normalize_name(rider.first_name, rider.last_name)
    uci_id = (rider.uci_id or "").strip()
    birth_year = (rider.birth_year or "").strip()

    row = None
    if uci_id:
        row = conn.execute(
            select(riders.c.id).where(riders.c.uci_id == uci_id)
        ).first()

    if row is None:
        row = conn.execute(
            select(riders.c.id).where(
                riders.c.normalized_name == norm,
                riders.c.birth_year == birth_year,
            )
        ).first()

    if row is None and birth_year:
        # Known birth year, but this rider may already exist from a list that
        # didn't publish one. Adopt that row and backfill.
        row = conn.execute(
            select(riders.c.id).where(
                riders.c.normalized_name == norm,
                riders.c.birth_year == "",
            )
        ).first()

    if row is None and not birth_year:
        # Unknown birth year: accept a same-named rider only when unambiguous.
        candidates = conn.execute(
            select(riders.c.id).where(riders.c.normalized_name == norm).limit(2)
        ).fetchall()
        if len(candidates) == 1:
            row = candidates[0]

    if row is not None:
        rider_id = row[0]
        # Only ever fill blanks; never overwrite a known value with an empty
        # one, since any given start list may omit fields another supplied.
        updates = {}
        if uci_id:
            updates["uci_id"] = uci_id
        if birth_year:
            updates["birth_year"] = birth_year
        if rider.country:
            updates["country"] = rider.country
        if rider.xcodata_slug:
            updates["xcodata_slug"] = rider.xcodata_slug
        if updates:
            conn.execute(riders.update().where(riders.c.id == rider_id).values(**updates))
        return rider_id

    return conn.execute(
        insert(riders)
        .values(
            uci_id=uci_id or None,
            first_name=rider.first_name or "",
            last_name=rider.last_name or "",
            normalized_name=norm,
            birth_year=birth_year,
            country=rider.country or "",
            xcodata_slug=rider.xcodata_slug or "",
        )
        .returning(riders.c.id)
    ).scalar_one()


def _upsert_race(conn: Connection, race_cfg: dict) -> int:
    slug = race_cfg.get("output", "").removesuffix(".html")
    values = {
        "slug": slug,
        "name": race_cfg.get("name", ""),
        "date": parse_iso_date(race_cfg.get("date", "")),
        "uci_category": race_cfg.get("uci_category", ""),
        "category": race_cfg.get("category", ""),
        "source_url": race_cfg.get("url", ""),
        "is_tracked": True,
    }
    stmt = insert(races).values(**values)
    return conn.execute(
        stmt.on_conflict_do_update(
            index_elements=[races.c.slug],
            set_={k: stmt.excluded[k] for k in values if k != "slug"},
        ).returning(races.c.id)
    ).scalar_one()


def _save_results(conn: Connection, rider_id: int, results: list) -> None:
    """Upsert a rider's race history.

    Rows are never deleted: each scrape only sees a rolling 12-month window, so
    keeping older rows lets the database accumulate deeper history than any
    single run could produce.
    """
    rows = []
    seen = set()
    for res in results or []:
        xco_race_id = str(res.get("race_id", "") or "")
        if not xco_race_id or xco_race_id in seen:
            continue
        seen.add(xco_race_id)
        raw_date = res.get("date", "") or ""
        rows.append({
            "rider_id": rider_id,
            "xco_race_id": xco_race_id,
            "race_name": res.get("race_name", "") or "",
            "date_raw": raw_date,
            "date": parse_result_date(raw_date),
            "location": res.get("location", "") or "",
            "rank": res.get("rank"),
            "time": res.get("time", "") or "",
            "cat": res.get("cat", "") or "",
            "uci_pts": res.get("uci_pts"),
            "race_class": res.get("race_class", "") or "",
        })
    if not rows:
        return

    stmt = insert(rider_results).values(rows)
    conn.execute(stmt.on_conflict_do_update(
        index_elements=[rider_results.c.rider_id, rider_results.c.xco_race_id],
        set_={k: stmt.excluded[k] for k in
              ("race_name", "date_raw", "date", "location", "rank", "time", "cat",
               "uci_pts", "race_class")},
    ))


def save_race(conn: Connection, race_cfg: dict, rider_list: list) -> int:
    """Write one race and its start list. Returns the race id."""
    race_id = _upsert_race(conn, race_cfg)

    # Timing sites take start lists down once a race is over, so a past race
    # scrapes as zero riders. Replacing entries with nothing would delete
    # history this database exists to accumulate — the static site lost those
    # riders on every rebuild, and not repeating that is the point of moving to
    # Postgres. Keep whatever is already stored instead.
    if not rider_list:
        existing = conn.execute(
            select(func.count())
            .select_from(race_entries)
            .where(race_entries.c.race_id == race_id)
        ).scalar_one()
        if existing:
            # Retaining the data is right, but staying quiet about it is not:
            # a filter that stops matching looks exactly like a source going
            # offline, and the stale rows would hide it indefinitely.
            console.print(
                f"[yellow]  ! {race_cfg.get('name', '')}: scraped 0 riders but "
                f"{existing} entries are already stored — keeping them. "
                f"Check the source URL and category filter.[/yellow]"
            )
        return race_id

    # Otherwise entries are replaced wholesale rather than merged: riders
    # withdraw between scrapes, and a stale entry would keep showing them on
    # the start list.
    conn.execute(delete(race_entries).where(race_entries.c.race_id == race_id))

    for rider in rider_list:
        rider_id = _resolve_rider(conn, rider)
        conn.execute(insert(race_entries).values(
            race_id=race_id,
            rider_id=rider_id,
            start_nr=rider.start_nr or "",
            team=rider.team or "",
            category=rider.category or "",
            uci_rank=rider.uci_rank,
            uci_points=rider.uci_points,
            cp_xco_points=rider.cp_xco_points or 0,
            computed_points=rider.computed_points or 0,
            result_rank=rider.result_rank,
            result_time=rider.result_time or "",
            match_confidence=rider.match_confidence,
            corrected_name=rider.corrected_name or "",
            race_name=rider.race_name or "",
        ).on_conflict_do_nothing(
            index_elements=[race_entries.c.race_id, race_entries.c.rider_id],
        ))
        _save_results(conn, rider_id, rider.race_results)

    return race_id


def save_all(race_configs: list, rider_groups: list) -> None:
    """Write every race in one transaction, so a mid-run scrape failure can't
    leave the site showing half-updated start lists."""
    with get_engine().begin() as conn:
        for race_cfg, rider_list in zip(race_configs, rider_groups):
            save_race(conn, race_cfg, rider_list)

        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        stmt = insert(meta).values(key="generated_at", value=generated_at)
        conn.execute(stmt.on_conflict_do_update(
            index_elements=[meta.c.key], set_={"value": stmt.excluded.value},
        ))
