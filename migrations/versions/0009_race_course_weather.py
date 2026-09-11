"""Add races course (lap_km/lap_elevation_m/laps/terrain) and race-day weather.

The course fields are hand-entered in races.yml, one venue at a time; the
weather fields are backfilled from the Open-Meteo archive by
mtb_analyzer/weather.py. All are nullable because both arrive gradually — a
race can be tracked long before anyone measures its lap, and a race in the
future has no weather to look up yet.

Revision ID: 0009_race_course_weather
Revises: 0008_discipline
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_race_course_weather"
down_revision = "0008_discipline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("races", sa.Column("lap_km", sa.Float(), nullable=True))
    op.add_column("races", sa.Column("lap_elevation_m", sa.Integer(), nullable=True))
    op.add_column("races", sa.Column("laps", sa.Integer(), nullable=True))
    op.add_column("races", sa.Column("terrain", sa.Text(), nullable=False, server_default=""))
    op.add_column("races", sa.Column("weather_temp_max_c", sa.Float(), nullable=True))
    op.add_column("races", sa.Column("weather_temp_min_c", sa.Float(), nullable=True))
    op.add_column("races", sa.Column("weather_precip_mm", sa.Float(), nullable=True))
    op.add_column("races", sa.Column("weather_wind_kmh", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("races", "weather_wind_kmh")
    op.drop_column("races", "weather_precip_mm")
    op.drop_column("races", "weather_temp_min_c")
    op.drop_column("races", "weather_temp_max_c")
    op.drop_column("races", "terrain")
    op.drop_column("races", "laps")
    op.drop_column("races", "lap_elevation_m")
    op.drop_column("races", "lap_km")
