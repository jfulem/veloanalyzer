"""Add race_requests: visitor-submitted start lists.

Revision ID: 0003_race_requests
Revises: 0002_race_class
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_race_requests"
down_revision = "0002_race_class"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "race_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("race_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.Text(), nullable=False, server_default=""),
        sa.Column("email", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("submitter_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_race_requests_status", "race_requests", ["status", "created_at"])
    op.create_index("idx_race_requests_submitter", "race_requests", ["submitter_hash", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_race_requests_submitter", table_name="race_requests")
    op.drop_index("idx_race_requests_status", table_name="race_requests")
    op.drop_table("race_requests")
