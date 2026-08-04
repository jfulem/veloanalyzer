"""Database engine wiring."""

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from .schema import metadata

_engine: Engine | None = None


def database_url() -> str:
    """Read DATABASE_URL and normalise it for SQLAlchemy 2 + psycopg 3.

    Neon (and most managed providers) hand out `postgresql://...` URLs, which
    SQLAlchemy maps to psycopg2 by default. We install psycopg 3, so the driver
    has to be named explicitly.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Locally, export the Neon connection "
            "string; on Fly, set it with `fly secrets set DATABASE_URL=...`."
        )
    parsed = make_url(url)
    if parsed.drivername in ("postgres", "postgresql"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    return parsed.render_as_string(hide_password=False)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        # pool_pre_ping because Neon suspends compute after 5 minutes idle;
        # without it the first request after a suspend hits a dead connection.
        _engine = create_engine(database_url(), pool_pre_ping=True, future=True)
    return _engine


def bootstrap(engine: Engine | None = None) -> None:
    """Create the extension and every table. Idempotent."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        # Must exist before the gin_trgm_ops index in schema.py can be built.
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        metadata.create_all(conn)
