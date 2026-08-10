"""Add races.location/lat/lon.

Revision ID: 0004_race_location
Revises: 0003_race_requests
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_race_location"
down_revision = "0003_race_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("races", sa.Column("location", sa.Text(), nullable=False, server_default=""))
    op.add_column("races", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("races", sa.Column("lon", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("races", "lon")
    op.drop_column("races", "lat")
    op.drop_column("races", "location")
