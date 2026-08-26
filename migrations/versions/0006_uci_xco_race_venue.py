"""Add venue/country to uci_xco_race_results.

Revision ID: 0006_uci_xco_race_venue
Revises: 0005_uci_xco_race_results
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_uci_xco_race_venue"
down_revision = "0005_uci_xco_race_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "uci_xco_race_results",
        sa.Column("venue", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "uci_xco_race_results",
        sa.Column("country", sa.String(3), nullable=False, server_default=""),
    )
    op.create_index(
        "idx_uci_xco_race_results_country",
        "uci_xco_race_results",
        ["country"],
    )


def downgrade() -> None:
    op.drop_index("idx_uci_xco_race_results_country", table_name="uci_xco_race_results")
    op.drop_column("uci_xco_race_results", "country")
    op.drop_column("uci_xco_race_results", "venue")
