"""Add rider_results.race_class.

The UCI points quotas in art. 4.16.008 apply per competition class, so the
class has to travel with each result for the UI to show which ones count.

Revision ID: 0002_race_class
Revises: 0001_initial
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_race_class"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rider_results",
        sa.Column("race_class", sa.String(length=8), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("rider_results", "race_class")
