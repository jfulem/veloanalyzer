"""Read endpoints.

The response shapes deliberately match the TypeScript interfaces the frontend
already had when it queried SQLite in the browser (frontend/src/api.ts), so the
ui/ components did not have to change. In particular `date` on a result is the
UCI display string, while ordering uses the parsed date column.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..db import get_engine

router = APIRouter(prefix="/api")


def get_conn():
    with get_engine().connect() as conn:
        yield conn


def _rows(conn: Connection, sql: str, **params) -> list[dict]:
    return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def _race_id(conn: Connection, slug: str) -> int:
    row = conn.execute(text("SELECT id FROM races WHERE slug = :slug"), {"slug": slug}).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No race with slug {slug!r}")
    return row[0]


@router.get("/meta")
def get_meta(conn: Connection = Depends(get_conn)) -> dict:
    return {r["key"]: r["value"] for r in _rows(conn, "SELECT key, value FROM meta")}


@router.get("/races")
def list_races(conn: Connection = Depends(get_conn)) -> list[dict]:
    """Every race. The frontend splits upcoming from past itself and needs the
    full list anyway to resolve #race=<slug> deep links to past races."""
    return _rows(conn, """
        SELECT id, slug, name, date, uci_category, category
        FROM races
        ORDER BY date ASC NULLS LAST, name
    """)


@router.get("/stats")
def get_stats(conn: Connection = Depends(get_conn)) -> dict:
    """Site-wide totals for the landing page.

    `riders` counts distinct people, not start-list entries — that is the whole
    point of the normalised schema, and it is the honest answer to "riders
    tracked" now that we can give it.
    """
    row = conn.execute(text("""
        SELECT (SELECT count(*) FROM races)       AS races,
               (SELECT count(*) FROM riders)      AS riders,
               (SELECT count(*) FROM race_entries) AS entries
    """)).mappings().one()
    return dict(row)


# Declared before /races/{slug} on purpose: FastAPI matches routes in order, so
# the path-parameter route would otherwise capture "stats" as a slug.
@router.get("/races/stats")
def get_race_stats(conn: Connection = Depends(get_conn)) -> list[dict]:
    """Per-race aggregates for the landing and race-overview pages.

    Reproduces what _compute_race_stats() derived in Python when the site was
    generated ahead of time.
    """
    return _rows(conn, """
        SELECT r.id, r.slug, r.name, r.date, r.uci_category, r.category,
               count(e.id)                    AS total,
               count(e.uci_rank)              AS ranked,
               min(e.uci_rank)                AS best,
               round(avg(e.uci_rank))::int    AS avg
        FROM races r
        LEFT JOIN race_entries e ON e.race_id = r.id
        GROUP BY r.id
        ORDER BY r.date ASC NULLS LAST, r.name
    """)


@router.get("/races/{slug}")
def get_race(slug: str, conn: Connection = Depends(get_conn)) -> dict:
    rows = _rows(conn, """
        SELECT id, slug, name, date, uci_category, category
        FROM races WHERE slug = :slug
    """, slug=slug)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No race with slug {slug!r}")
    return rows[0]


@router.get("/races/{slug}/entries")
def get_race_entries(slug: str, conn: Connection = Depends(get_conn)) -> list[dict]:
    """Flattens riders + race_entries back into the flat row the table expects.

    The ORDER BY reproduces the old client-side query exactly: official result
    first when the race has been run, then UCI rank, then the estimated-points
    fallbacks for unranked riders. It encodes real product logic, so it is kept
    verbatim rather than re-derived.
    """
    _race_id(conn, slug)
    return _rows(conn, """
        SELECT ri.id                     AS id,
               e.race_id                 AS race_id,
               ri.first_name, ri.last_name,
               e.corrected_name,
               ri.country, ri.birth_year,
               e.start_nr,
               COALESCE(ri.uci_id, '')   AS uci_id,
               e.uci_rank, e.uci_points, e.cp_xco_points, e.computed_points,
               e.result_rank, e.result_time,
               e.team, e.category, e.match_confidence,
               ri.xcodata_slug, e.race_name
        FROM race_entries e
        JOIN riders ri ON ri.id = e.rider_id
        JOIN races  r  ON r.id  = e.race_id
        WHERE r.slug = :slug
        ORDER BY (e.result_rank IS NULL), e.result_rank,
                 (e.uci_rank IS NULL), e.uci_rank,
                 COALESCE(e.computed_points, 0) DESC,
                 COALESCE(e.cp_xco_points, 0) DESC,
                 ri.last_name
    """, slug=slug)


@router.get("/races/{slug}/results")
def get_race_results(slug: str, conn: Connection = Depends(get_conn)) -> list[dict]:
    """Every history row for everyone in this race, in one request.

    The head-to-head panel and the form-trend arrows both need the whole field's
    history at once, so this stays a single batch call rather than one request
    per rider.
    """
    _race_id(conn, slug)
    return _rows(conn, """
        SELECT rr.id, rr.rider_id, rr.xco_race_id, rr.race_name,
               rr.date_raw AS date, rr.location, rr.rank, rr.time, rr.cat, rr.uci_pts
        FROM rider_results rr
        WHERE rr.rider_id IN (
            SELECT e.rider_id FROM race_entries e
            JOIN races r ON r.id = e.race_id
            WHERE r.slug = :slug
        )
        ORDER BY rr.date DESC NULLS LAST
    """, slug=slug)


@router.get("/riders/{rider_id}")
def get_rider(rider_id: int, conn: Connection = Depends(get_conn)) -> dict:
    rows = _rows(conn, """
        SELECT id, uci_id, first_name, last_name, normalized_name,
               birth_year, country, xcodata_slug
        FROM riders WHERE id = :id
    """, id=rider_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No rider with id {rider_id}")
    return rows[0]


@router.get("/riders/{rider_id}/results")
def get_rider_results(rider_id: int, conn: Connection = Depends(get_conn)) -> list[dict]:
    return _rows(conn, """
        SELECT id, rider_id, xco_race_id, race_name,
               date_raw AS date, location, rank, time, cat, uci_pts
        FROM rider_results
        WHERE rider_id = :id
        ORDER BY date DESC NULLS LAST
    """, id=rider_id)
