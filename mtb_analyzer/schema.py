"""Postgres schema.

Replaces the flat, per-start-list SQLite layout written by export_db.py. The
important change is that a rider is now a single global row: previously a rider
entered in three races got three `riders` rows and three copies of their
12-month history. Here `riders` holds identity, `race_entries` holds the facts
that are specific to one start list, and `rider_results` holds each rider's
history exactly once.
"""

from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey, Index,
                        Integer, MetaData, String, Table, Text, UniqueConstraint)

metadata = MetaData()

# One row per person, deduplicated across every start list.
riders = Table(
    "riders", metadata,
    Column("id", Integer, primary_key=True),
    # UCI ID is the strong identity key, but plenty of start lists omit it, so
    # it is nullable and dedup falls back to normalized_name + birth_year.
    Column("uci_id", String(20), unique=True),
    Column("first_name", Text, nullable=False),
    Column("last_name", Text, nullable=False),
    # Diacritic-stripped, lowercased "first last" — the fallback identity key
    # and the target of the trigram index used by rider search.
    Column("normalized_name", Text, nullable=False),
    Column("birth_year", String(4), nullable=False, server_default=""),
    Column("country", String(3), nullable=False, server_default=""),
    Column("xcodata_slug", Text, nullable=False, server_default=""),
    UniqueConstraint("normalized_name", "birth_year", name="uq_riders_name_birth_year"),
)

races = Table(
    "races", metadata,
    Column("id", Integer, primary_key=True),
    Column("slug", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("date", Date),
    Column("uci_category", String(8), nullable=False, server_default=""),
    Column("category", Text, nullable=False, server_default=""),
    # 'XCO' or 'CX' — see mtb_analyzer/discipline.py. Defaulted rather than
    # nullable so every row written before cyclo-cross existed reads as the
    # MTB cross-country it was.
    Column("discipline", String(8), nullable=False, server_default="XCO"),
    Column("source_url", Text, nullable=False, server_default=""),
    # False for ad-hoc races created by on-demand analysis (phase 5); those are
    # reaped once expires_at passes so they don't accumulate forever.
    Column("is_tracked", Boolean, nullable=False, server_default="true"),
    Column("expires_at", DateTime(timezone=True)),
    # Free-text venue ("Bedřichov, Czech Republic"), geocoded once by
    # mtb_analyzer/geocode.py. lat/lon are nullable — races.yml entries the
    # geocoder hasn't resolved yet (or that never got a location: at all)
    # simply don't get a map pin rather than showing a wrong one.
    Column("location", Text, nullable=False, server_default=""),
    Column("lat", Float),
    Column("lon", Float),
)

# A rider's participation in one race, plus everything that is true only of
# that start list (bib, team as entered, rank at the time it was scraped).
race_entries = Table(
    "race_entries", metadata,
    Column("id", Integer, primary_key=True),
    Column("race_id", Integer, ForeignKey("races.id", ondelete="CASCADE"), nullable=False),
    Column("rider_id", Integer, ForeignKey("riders.id", ondelete="CASCADE"), nullable=False),
    Column("start_nr", Text, nullable=False, server_default=""),
    Column("team", Text, nullable=False, server_default=""),
    Column("category", Text, nullable=False, server_default=""),
    Column("uci_rank", Integer),
    Column("uci_points", Integer),
    Column("cp_xco_points", Integer, nullable=False, server_default="0"),
    Column("computed_points", Integer, nullable=False, server_default="0"),
    Column("result_rank", Integer),
    Column("result_time", Text, nullable=False, server_default=""),
    Column("match_confidence", Integer, nullable=False, server_default="100"),
    Column("corrected_name", Text, nullable=False, server_default=""),
    Column("race_name", Text, nullable=False, server_default=""),
    UniqueConstraint("race_id", "rider_id", name="uq_race_entries_race_rider"),
)

# Each rider's UCI XCO history, stored once regardless of how many start lists
# they appear in.
rider_results = Table(
    "rider_results", metadata,
    Column("id", Integer, primary_key=True),
    Column("rider_id", Integer, ForeignKey("riders.id", ondelete="CASCADE"), nullable=False),
    Column("xco_race_id", Text, nullable=False),
    Column("race_name", Text, nullable=False, server_default=""),
    # The UCI publishes dates as display strings ("07 Jun 2026", or a range
    # "01 - 02 Apr 2023"). date_raw preserves that string so the frontend's
    # existing formatting keeps working; date is the parsed value so the server
    # can order and filter chronologically.
    Column("date_raw", Text, nullable=False, server_default=""),
    Column("date", Date),
    Column("location", Text, nullable=False, server_default=""),
    Column("rank", Integer),
    Column("time", Text, nullable=False, server_default=""),
    Column("cat", Text, nullable=False, server_default=""),
    Column("uci_pts", Integer),
    # UCI competition class ('1', '2', '3', 'HC', 'CS', 'CN', 'S1'...). Drives
    # the per-class points quotas in art. 4.16.008, so the UI can show which
    # results actually contribute to a rider's total.
    Column("race_class", String(8), nullable=False, server_default=""),
    Column("discipline", String(8), nullable=False, server_default="XCO"),
    # xco_race_id is "{date}|{comp_name}", which a rider could in principle
    # repeat across disciplines (same venue, same weekend), so the discipline
    # is part of the identity rather than merely a filter.
    UniqueConstraint("rider_id", "xco_race_id", "discipline",
                     name="uq_rider_results_rider_race"),
)

# Queued on-demand analyses (phase 5). Doubles as the job queue: the worker
# claims rows with SELECT ... FOR UPDATE SKIP LOCKED, so no Redis is needed.
analysis_jobs = Table(
    "analysis_jobs", metadata,
    Column("id", String(36), primary_key=True),
    Column("status", String(16), nullable=False, server_default="queued"),
    Column("url", Text, nullable=False),
    Column("category", Text, nullable=False, server_default=""),
    Column("uci_category", String(8), nullable=False, server_default=""),
    Column("progress", Text, nullable=False, server_default=""),
    Column("error", Text, nullable=False, server_default=""),
    Column("result_race_id", Integer, ForeignKey("races.id", ondelete="SET NULL")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
)

# Visitor-submitted start lists, for races not yet in races.yml. Public and
# unauthenticated, so everything here is untrusted input: it is stored and
# displayed nowhere on the site, and only ever read by the maintainer.
race_requests = Table(
    "race_requests", metadata,
    Column("id", Integer, primary_key=True),
    Column("url", Text, nullable=False),
    Column("race_name", Text, nullable=False, server_default=""),
    Column("category", Text, nullable=False, server_default=""),
    # Optional, so the maintainer can reply. Never displayed publicly.
    Column("email", Text, nullable=False, server_default=""),
    Column("note", Text, nullable=False, server_default=""),
    # Salted hash rather than the address itself: enough to rate-limit a
    # submitter without keeping their IP.
    Column("submitter_hash", String(64), nullable=False, server_default=""),
    # new → added → rejected, for the maintainer to track what they've handled.
    Column("status", String(16), nullable=False, server_default="new"),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

# Full finisher list for every UCI XCO event in the last 12 months.
# One row per finisher per race per category. Populated by ingest and queried
# by /api/xco-race to let the rider card link to a full race result view.
uci_xco_race_results = Table(
    "uci_xco_race_results", metadata,
    Column("id", Integer, primary_key=True),
    # Matches rider_results.xco_race_id — the composite "{date}|{comp_name}" key
    # used throughout the ranking pipeline. Used as the lookup key so the
    # frontend can fetch full results from a RaceResult row without extra columns.
    Column("xco_race_id", Text, nullable=False),
    Column("category", String(8), nullable=False),
    Column("comp_name", Text, nullable=False, server_default=""),
    Column("date_raw", Text, nullable=False, server_default=""),
    Column("date", Date),
    Column("race_class", String(8), nullable=False, server_default=""),
    Column("rank", Integer),
    Column("first_name", Text, nullable=False, server_default=""),
    Column("last_name", Text, nullable=False, server_default=""),
    Column("nationality", String(3), nullable=False, server_default=""),
    Column("race_time", Text, nullable=False, server_default=""),
    Column("uci_pts", Integer),
    # Competition-level, so identical on every finisher row of the same
    # xco_race_id — denormalized here rather than a separate competitions
    # table because this table already carries other per-competition fields
    # (comp_name, date, race_class) the same way. country is the IOC code
    # straight from the UCI calendar API, used to browse/group the archive
    # by country without a geocoding step.
    Column("venue", Text, nullable=False, server_default=""),
    Column("country", String(3), nullable=False, server_default=""),
    Column("discipline", String(8), nullable=False, server_default="XCO"),
    UniqueConstraint("xco_race_id", "category", "discipline", "first_name", "last_name",
                     name="uq_uci_xco_race_results_rider"),
)

# The official UCI ranking (ME/WE/MJ/WJ), refreshed wholesale on every
# ingest — this is a snapshot of this week's ranking, not history, so a rider
# has at most one row here at a time (rider_id is unique) and a category's
# rows are fully replaced rather than upserted. Every ranked rider gets a
# `riders` row even if they've never appeared in a tracked start list, via
# the same identity rules (UCI ID, then name + birth year) store.py's
# start-list ingest already uses — so this table only needs to point at that
# global identity, not repeat name/country/etc.
uci_ranking = Table(
    "uci_ranking", metadata,
    Column("id", Integer, primary_key=True),
    Column("uci_cat", String(8), nullable=False),
    Column("rank", Integer, nullable=False),
    Column("points", Integer, nullable=False, server_default="0"),
    # From the ranking feed itself (dataride's TeamName) — the only team info
    # available for a ranked rider who has never been on a tracked start
    # list, where team instead comes from race_entries.
    Column("team", Text, nullable=False, server_default=""),
    Column("discipline", String(8), nullable=False, server_default="XCO"),
    # Unique per discipline, not globally: a cyclo-cross rider who also races
    # MTB holds a rank in both, and a bare unique(rider_id) would let one
    # ranking silently evict the other.
    Column("rider_id", Integer, ForeignKey("riders.id", ondelete="CASCADE"),
           nullable=False),
    UniqueConstraint("rider_id", "discipline", name="uq_uci_ranking_rider_discipline"),
)

meta = Table(
    "meta", metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False, server_default=""),
)

Index("idx_race_entries_race", race_entries.c.race_id)
Index("idx_race_entries_rider", race_entries.c.rider_id)
Index("idx_rider_results_rider", rider_results.c.rider_id)
Index("idx_races_date", races.c.date)
Index("idx_analysis_jobs_status", analysis_jobs.c.status)
Index("idx_uci_ranking_cat", uci_ranking.c.uci_cat, uci_ranking.c.discipline)
Index("idx_races_discipline", races.c.discipline)

# Trigram index for search-as-you-type over rider names. Requires the pg_trgm
# extension, created by migrations/bootstrap before this index is built.
Index(
    "idx_riders_normalized_name_trgm",
    riders.c.normalized_name,
    postgresql_using="gin",
    postgresql_ops={"normalized_name": "gin_trgm_ops"},
)

Index("idx_race_requests_status", race_requests.c.status, race_requests.c.created_at)
Index("idx_race_requests_submitter", race_requests.c.submitter_hash, race_requests.c.created_at)
Index("idx_uci_xco_race_results_lookup", uci_xco_race_results.c.xco_race_id,
      uci_xco_race_results.c.category, uci_xco_race_results.c.discipline)
# Backs the archive-browsing query, which groups the whole table by country.
Index("idx_uci_xco_race_results_country", uci_xco_race_results.c.country)
