"""Persistence layer — writes enriched riders into Postgres.

Replaces export_db.py. The substantive difference is rider identity: a start
list gives us a name and sometimes a UCI ID, and the same person must resolve
to the same `riders` row across every race they enter, otherwise global search
and rider profiles show the same athlete several times.
"""

import re
from datetime import date, datetime, timezone

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from .config import console
from .db import get_engine
from .discipline import DEFAULT_DISCIPLINE
from .discipline import normalize as normalize_discipline
from .ranking import _strip_diacritics, ranking_window_start
from .schema import meta, race_entries, races, rider_results, riders, uci_ranking, uci_xco_race_results

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

    if row is None:
        # One source carries a middle name the other omits — 'Milán Zsolt
        # Podgornik' on one start list, 'Milán Podgornik' on the next. Without
        # this the same rider forks into two identities, and each start list
        # shows whichever half it happened to create: one ranked, one not.
        #
        # Matched on first given name + surname + birth year, and only when
        # exactly one candidate qualifies, so two genuinely different riders
        # who share those never get merged.
        norm_last = _strip_diacritics(rider.last_name or "").strip().lower()
        first_token = norm.split()[0] if norm.split() else ""
        if norm_last and first_token:
            candidates = [
                r for r in conn.execute(
                    select(riders.c.id, riders.c.normalized_name).where(
                        riders.c.birth_year == birth_year,
                        riders.c.normalized_name.like(f"% {norm_last}"),
                    )
                ).fetchall()
                if r[1].split() and r[1].split()[0] == first_token
            ]
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
            # Skip if another row already has (normalized_name, birth_year) —
            # that would violate uq_riders_name_birth_year. Happens when a
            # UCI-ID lookup adopts one row while a separate same-named row
            # already carries the wildcard birth_year '*'.
            conflict = conn.execute(
                select(riders.c.id).where(
                    riders.c.normalized_name == norm,
                    riders.c.birth_year == birth_year,
                    riders.c.id != rider_id,
                )
            ).first()
            if not conflict:
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
        "discipline": normalize_discipline(race_cfg.get("discipline")),
        "source_url": race_cfg.get("url", ""),
        "is_tracked": True,
        "location": race_cfg.get("location", "") or "",
        "lat": race_cfg.get("lat"),
        "lon": race_cfg.get("lon"),
    }
    stmt = insert(races).values(**values)
    return conn.execute(
        stmt.on_conflict_do_update(
            index_elements=[races.c.slug],
            set_={k: stmt.excluded[k] for k in values if k != "slug"},
        ).returning(races.c.id)
    ).scalar_one()


def _save_results(conn: Connection, rider_id: int, results: list,
                  discipline: str = DEFAULT_DISCIPLINE) -> None:
    """Upsert a rider's race history.

    Older rows are never deleted: each scrape only sees a rolling 12-month
    window, so keeping them lets the database accumulate deeper history than
    any single run could produce. They stop counting toward the UCI total on
    their first anniversary — that is applied at display time — but the races
    still happened and still belong on the rider's page.

    Inside the window it is the opposite: the freshly built history is
    authoritative, and a stored row for a race the rider is no longer in gets
    dropped. Without that, a result attributed to the wrong rider or the wrong
    event stayed forever, because an upsert can only correct rows it collides
    with — a phantom result nothing collides with was untouchable. That is how
    a junior's enduro ride at a World Cup sat among his cross-country points.

    The pruning is deliberately skipped when the rebuilt history is empty: that
    means the lookup found nothing for this rider, usually a name that stopped
    matching, and deleting a season of real results over a spelling change
    would be far worse than keeping a stale row.
    """
    rows = []
    seen = set()
    for res in results or []:
        xco_race_id = str(res.get("race_id", "") or "")
        res_disc = normalize_discipline(res.get("disc") or discipline)
        if not xco_race_id or (xco_race_id, res_disc) in seen:
            continue
        seen.add((xco_race_id, res_disc))
        raw_date = res.get("date", "") or ""
        rows.append({
            "rider_id": rider_id,
            "xco_race_id": xco_race_id,
            # Trust the result's own discipline where the history carries one
            # (build_uci_xco_history stamps every row), and fall back to the
            # race's for anything assembled by hand.
            "discipline": res_disc,
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

    # Prune stale in-window rows before writing the fresh ones. Scoped per
    # discipline so a rider's cyclo-cross winter is never pruned by a rebuild
    # of their mountain-bike summer. Rows whose date would not parse have a
    # NULL date and never satisfy the comparison, so they are left alone.
    window_start = ranking_window_start().date()
    keep_by_discipline: dict = {}
    for row in rows:
        keep_by_discipline.setdefault(row["discipline"], set()).add(row["xco_race_id"])
    for disc, keep in keep_by_discipline.items():
        conn.execute(delete(rider_results).where(
            rider_results.c.rider_id == rider_id,
            rider_results.c.discipline == disc,
            rider_results.c.date >= window_start,
            rider_results.c.xco_race_id.notin_(keep),
        ))

    stmt = insert(rider_results).values(rows)
    conn.execute(stmt.on_conflict_do_update(
        index_elements=[rider_results.c.rider_id, rider_results.c.xco_race_id,
                        rider_results.c.discipline],
        set_={k: stmt.excluded[k] for k in
              ("race_name", "date_raw", "date", "location", "rank", "time", "cat",
               "uci_pts", "race_class")},
    ))


def save_race(conn: Connection, race_cfg: dict, rider_list: list) -> int:
    """Write one race and its start list. Returns the race id."""
    race_id = _upsert_race(conn, race_cfg)
    discipline = normalize_discipline(race_cfg.get("discipline"))

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
        _save_results(conn, rider_id, rider.race_results, discipline)

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


def save_uci_race_results(race_results_cache: dict) -> None:
    """Persist the full finisher lists built by build_uci_xco_history and
    build_uci_xco_country_archive.

    race_results_cache is {discipline: {uci_cat: {xco_race_id: [finisher_row,
    ...]}}} as returned by get_uci_xco_race_results_cache().

    Every race this run rebuilt is replaced outright rather than merged into.
    The table is a mirror of what the UCI publishes for an event, and a merge
    cannot express a correction: an upsert keyed on the finisher would leave a
    rider's rank, time and points at whatever was stored first, and a finisher
    who should no longer be in the race at all would simply stay. That is not
    hypothetical — competitions that bundle several disciplines were being read
    for the wrong event (see ranking._label_discipline), so these rows held a
    22-minute short-track result where the cross-country one belonged.

    Only races present in `race_results_cache` are touched, so a competition
    this run failed to fetch keeps whatever is already stored rather than being
    deleted on a transient network error.
    """
    # Keyed by the same tuple as the table's unique constraint, because the
    # same finisher really can arrive twice: the UCI's own results feed
    # occasionally repeats a DNF rider, and build_uci_xco_history plus
    # build_uci_xco_country_archive both feed this cache. Two such rows in one
    # INSERT would now violate that constraint outright — the delete below
    # clears the way for a plain insert, so there is no ON CONFLICT to absorb
    # them. Last one wins; for a genuine duplicate the rows are equivalent.
    rows_by_key: dict = {}
    for discipline, by_category in race_results_cache.items():
        discipline = normalize_discipline(discipline)
        for category, races_by_id in by_category.items():
            for xco_race_id, finishers in races_by_id.items():
                for f in finishers:
                    first_name = f.get("first_name", "")
                    last_name  = f.get("last_name", "")
                    key = (xco_race_id, category, discipline, first_name, last_name)
                    rows_by_key[key] = {
                        "xco_race_id": xco_race_id,
                        "category":    category,
                        "discipline":  discipline,
                        "comp_name":   f.get("comp_name", ""),
                        "date_raw":    f.get("date_raw", ""),
                        "date":        parse_result_date(f.get("date_raw", "")),
                        "race_class":  f.get("race_class", ""),
                        "rank":        f.get("rank"),
                        "first_name":  first_name,
                        "last_name":   last_name,
                        "nationality": f.get("nationality", ""),
                        "race_time":   f.get("race_time", ""),
                        "uci_pts":     f.get("uci_pts"),
                        "venue":       f.get("venue", ""),
                        "country":     f.get("country", ""),
                    }

    rows_to_insert = list(rows_by_key.values())
    if not rows_to_insert:
        return

    rebuilt = {(r["xco_race_id"], r["category"], r["discipline"]) for r in rows_to_insert}

    # Postgres caps bind parameters at 65 535. With 15 columns per row that
    # allows ~4 300 rows per statement; use 1 000 to stay well clear. The
    # delete carries 3 parameters per race, so it can afford far larger
    # batches — 5 000 races is still only 15 000 parameters.
    _CHUNK, _DELETE_CHUNK = 1000, 5000
    key = tuple_(uci_xco_race_results.c.xco_race_id,
                 uci_xco_race_results.c.category,
                 uci_xco_race_results.c.discipline)
    rebuilt_list = sorted(rebuilt)
    with get_engine().begin() as conn:
        for i in range(0, len(rebuilt_list), _DELETE_CHUNK):
            conn.execute(delete(uci_xco_race_results).where(
                key.in_(rebuilt_list[i : i + _DELETE_CHUNK])))
        for i in range(0, len(rows_to_insert), _CHUNK):
            conn.execute(insert(uci_xco_race_results).values(rows_to_insert[i : i + _CHUNK]))
    console.print(
        f"[green]  ✓ Saved {len(rows_to_insert)} UCI race result rows "
        f"across {len(rebuilt)} races[/green]"
    )


def save_uci_ranking(uci_cat: str, entries: list,
                     discipline: str = DEFAULT_DISCIPLINE) -> None:
    """
    Replace the stored official UCI ranking for one category (in one
    discipline) with `entries`
    (ranking.get_uci_cache(cat)["by_name"].values()), fusing each ranked
    rider into the global `riders` table with the same identity rules
    _resolve_rider uses for start-list ingest: UCI ID wins, then name +
    birth year — a tracked rider with a blank birth year adopts the
    ranking's real one rather than forking a duplicate row.

    Every ranked rider gets a `riders` row even if they've never appeared on
    a tracked start list, so the Riders page can show the whole ranking
    fused with tracked riders with a single join — no runtime name matching.

    This is a snapshot (this week's ranking), not history: the whole
    category is deleted and reinserted each run rather than upserted by
    rank, since UCI rankings can tie at 0 points, so rank isn't a safe key
    either. A rider can only be ranked in one category at a time *per
    discipline* ((rider_id, discipline) is unique on uci_ranking) — ON
    CONFLICT DO UPDATE handles the rare case of someone moving category
    between runs by just moving their row. Cross-discipline is a different
    matter: a cyclo-cross regular who also races MTB legitimately holds two
    rows, which is why the constraint is not on rider_id alone.
    """
    discipline = normalize_discipline(discipline)
    with get_engine().begin() as conn:
        existing = conn.execute(
            select(riders.c.id, riders.c.uci_id, riders.c.normalized_name, riders.c.birth_year)
        ).fetchall()
        by_uci_id: dict = {}
        by_norm_birth: dict = {}
        by_norm_blank: dict = {}
        for rid, uci_id, norm, birth in existing:
            if uci_id:
                by_uci_id[uci_id] = rid
            by_norm_birth[(norm, birth)] = rid
            if birth == "":
                by_norm_blank.setdefault(norm, []).append(rid)

        matched: list = []      # (rider_id, entry)
        to_create: list = []    # (normalized_name, entry)
        claimed_uci_ids: set = set()
        claimed_norm_birth: set = set()
        for e in entries:
            norm   = normalize_name(e.get("first_name", ""), e.get("last_name", ""))
            uci_id = e.get("uci_id", "")
            birth  = e.get("birth_year", "")

            rid = by_uci_id.get(uci_id) if uci_id else None
            if rid is None:
                rid = by_norm_birth.get((norm, birth))
            if rid is None and birth:
                candidates = by_norm_blank.get(norm, [])
                if len(candidates) == 1:
                    rid = candidates[0]

            if rid is not None:
                matched.append((rid, e))
                continue

            # Two different-enough-to-not-match-anything entries can still
            # collide with each other (same uci_id data glitch, or two
            # people who happen to share a name and birth year) — riders has
            # a unique constraint on both, so the second one would abort the
            # whole bulk insert. Drop it rather than crash the run; it's a
            # rare edge case, and the loss is one ranking row, not the ingest.
            if uci_id and uci_id in claimed_uci_ids:
                continue
            if (norm, birth) in claimed_norm_birth:
                continue
            if uci_id:
                claimed_uci_ids.add(uci_id)
            claimed_norm_birth.add((norm, birth))
            to_create.append((norm, e))

        new_ids: list = []
        if to_create:
            values = [{
                "uci_id": e.get("uci_id") or None,
                "first_name": e.get("first_name", ""),
                "last_name": e.get("last_name", ""),
                "normalized_name": norm,
                "birth_year": e.get("birth_year", ""),
                "country": e.get("country", ""),
                "xcodata_slug": "",
            } for norm, e in to_create]
            # Row order matches input order for a plain multi-row INSERT ...
            # RETURNING (no ON CONFLICT), so zipping back against to_create
            # below is safe.
            result = conn.execute(insert(riders).values(values).returning(riders.c.id))
            new_ids = [row[0] for row in result.fetchall()]

        def _ranking_row(rid: int, e: dict) -> dict:
            return {
                "rider_id":   rid,
                "uci_cat":    uci_cat,
                "discipline": discipline,
                "rank":       int(e["rank"]),
                "points":     int(e.get("points") or 0),
                "team":       e.get("team", ""),
            }

        ranking_rows  = [_ranking_row(rid, e) for rid, e in matched]
        ranking_rows += [_ranking_row(rid, e) for rid, (_, e) in zip(new_ids, to_create)]

        conn.execute(delete(uci_ranking).where(
            uci_ranking.c.uci_cat == uci_cat,
            uci_ranking.c.discipline == discipline,
        ))

        if ranking_rows:
            _CHUNK = 1000
            for i in range(0, len(ranking_rows), _CHUNK):
                chunk = ranking_rows[i : i + _CHUNK]
                stmt = insert(uci_ranking).values(chunk)
                conn.execute(stmt.on_conflict_do_update(
                    index_elements=[uci_ranking.c.rider_id, uci_ranking.c.discipline],
                    set_={"uci_cat": stmt.excluded.uci_cat, "rank": stmt.excluded.rank,
                          "points": stmt.excluded.points, "team": stmt.excluded.team},
                ))

    console.print(
        f"[green]  ✓ Saved UCI ranking ({discipline} {uci_cat}): {len(matched)} matched "
        f"to tracked riders, {len(new_ids)} new riders created[/green]"
    )
