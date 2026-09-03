"""Add a discipline dimension so cyclo-cross can live beside MTB XCO.

Every existing row is MTB cross-country, so `discipline` lands with a server
default of 'XCO' and needs no backfill pass.

Two unique constraints have to widen along with it:

  * uci_ranking.rider_id was unique on its own. A rider who races both
    disciplines holds a rank in each, and the old constraint would let the
    second ingest evict the first.
  * uci_xco_race_results and rider_results key on the composite
    "{date}|{comp_name}" race id, which two disciplines could in principle
    repeat on the same weekend at the same venue.

Revision ID: 0008_discipline
Revises: 0007_uci_ranking
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_discipline"
down_revision = "0007_uci_ranking"
branch_labels = None
depends_on = None

_TABLES = ("races", "rider_results", "uci_xco_race_results", "uci_ranking")


def _unique_constraints_on(table: str, columns: list) -> list:
    """Names of UNIQUE constraints on `table` covering exactly `columns`."""
    inspector = sa.inspect(op.get_bind())
    return [
        c["name"]
        for c in inspector.get_unique_constraints(table)
        if list(c["column_names"]) == list(columns) and c["name"]
    ]


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("discipline", sa.String(8), nullable=False, server_default="XCO"),
        )

    # rider_results: widen the per-rider race key.
    op.drop_constraint("uq_rider_results_rider_race", "rider_results", type_="unique")
    op.create_unique_constraint(
        "uq_rider_results_rider_race", "rider_results",
        ["rider_id", "xco_race_id", "discipline"],
    )

    # uci_xco_race_results: widen the per-finisher key and its lookup index.
    op.drop_constraint(
        "uq_uci_xco_race_results_rider", "uci_xco_race_results", type_="unique")
    op.create_unique_constraint(
        "uq_uci_xco_race_results_rider", "uci_xco_race_results",
        ["xco_race_id", "category", "discipline", "first_name", "last_name"],
    )
    op.drop_index("idx_uci_xco_race_results_lookup", table_name="uci_xco_race_results")
    op.create_index(
        "idx_uci_xco_race_results_lookup", "uci_xco_race_results",
        ["xco_race_id", "category", "discipline"],
    )

    # uci_ranking: one row per rider *per discipline*. The old constraint was
    # declared inline as unique=True on the column, so Postgres named it
    # itself — conventionally uci_ranking_rider_id_key, but the name is the
    # server's to choose and a hard-coded guess would fail the whole migration.
    # Ask the catalog for whatever single-column unique constraint is actually
    # on rider_id and drop that.
    for name in _unique_constraints_on("uci_ranking", ["rider_id"]):
        op.drop_constraint(name, "uci_ranking", type_="unique")
    op.create_unique_constraint(
        "uq_uci_ranking_rider_discipline", "uci_ranking", ["rider_id", "discipline"],
    )
    op.drop_index("idx_uci_ranking_cat", table_name="uci_ranking")
    op.create_index("idx_uci_ranking_cat", "uci_ranking", ["uci_cat", "discipline"])

    op.create_index("idx_races_discipline", "races", ["discipline"])


def downgrade() -> None:
    # Cyclo-cross races go with the column. Without this they survive as rows
    # whose discipline is simply gone — indistinguishable from MTB, so the
    # site would serve cyclo-cross start lists as cross-country ones, and a
    # later re-upgrade would stamp them 'XCO' with no way back. Deleting is
    # safe because races are derived data: `races.yml` is the source of truth
    # and re-running the ingest rebuilds every one of them.
    op.execute("DELETE FROM races WHERE discipline <> 'XCO'")

    op.drop_index("idx_races_discipline", table_name="races")

    op.drop_index("idx_uci_ranking_cat", table_name="uci_ranking")
    op.create_index("idx_uci_ranking_cat", "uci_ranking", ["uci_cat"])
    op.drop_constraint("uq_uci_ranking_rider_discipline", "uci_ranking", type_="unique")
    # Only MTB rows can survive a single-discipline unique constraint.
    op.execute("DELETE FROM uci_ranking WHERE discipline <> 'XCO'")
    op.create_unique_constraint("uci_ranking_rider_id_key", "uci_ranking", ["rider_id"])


    op.drop_index("idx_uci_xco_race_results_lookup", table_name="uci_xco_race_results")
    op.create_index(
        "idx_uci_xco_race_results_lookup", "uci_xco_race_results",
        ["xco_race_id", "category"],
    )
    op.drop_constraint(
        "uq_uci_xco_race_results_rider", "uci_xco_race_results", type_="unique")
    op.execute("DELETE FROM uci_xco_race_results WHERE discipline <> 'XCO'")
    op.create_unique_constraint(
        "uq_uci_xco_race_results_rider", "uci_xco_race_results",
        ["xco_race_id", "category", "first_name", "last_name"],
    )

    op.drop_constraint("uq_rider_results_rider_race", "rider_results", type_="unique")
    op.execute("DELETE FROM rider_results WHERE discipline <> 'XCO'")
    op.create_unique_constraint(
        "uq_rider_results_rider_race", "rider_results", ["rider_id", "xco_race_id"],
    )

    for table in reversed(_TABLES):
        op.drop_column(table, "discipline")
