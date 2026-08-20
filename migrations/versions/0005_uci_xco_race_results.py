"""Add uci_xco_race_results table.

Revision ID: 0005_uci_xco_race_results
Revises: 0004_race_location
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_uci_xco_race_results"
down_revision = "0004_race_location"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "uci_xco_race_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("xco_race_id", sa.Text(), nullable=False),
        sa.Column("category", sa.String(8), nullable=False),
        sa.Column("comp_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("date_raw", sa.Text(), nullable=False, server_default=""),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("race_class", sa.String(8), nullable=False, server_default=""),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("nationality", sa.String(3), nullable=False, server_default=""),
        sa.Column("race_time", sa.Text(), nullable=False, server_default=""),
        sa.Column("uci_pts", sa.Integer(), nullable=True),
        sa.UniqueConstraint(
            "xco_race_id", "category", "first_name", "last_name",
            name="uq_uci_xco_race_results_rider",
        ),
    )
    op.create_index(
        "idx_uci_xco_race_results_lookup",
        "uci_xco_race_results",
        ["xco_race_id", "category"],
    )


def downgrade() -> None:
    op.drop_index("idx_uci_xco_race_results_lookup", table_name="uci_xco_race_results")
    op.drop_table("uci_xco_race_results")
