"""Add uci_ranking table.

Revision ID: 0007_uci_ranking
Revises: 0006_uci_xco_race_venue
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_uci_ranking"
down_revision = "0006_uci_xco_race_venue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "uci_ranking",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uci_cat", sa.String(8), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("team", sa.Text(), nullable=False, server_default=""),
        sa.Column("rider_id", sa.Integer(),
                  sa.ForeignKey("riders.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
    )
    op.create_index("idx_uci_ranking_cat", "uci_ranking", ["uci_cat"])


def downgrade() -> None:
    op.drop_index("idx_uci_ranking_cat", table_name="uci_ranking")
    op.drop_table("uci_ranking")
