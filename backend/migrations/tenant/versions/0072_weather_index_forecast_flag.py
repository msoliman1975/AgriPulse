"""Weather indices gain a forecast half — provenance flag on the projection.

``weather_index_daily`` only ever held days the farm had already lived
through: the derivation task read ``weather_observations`` and capped its
targets at "today" in farm-local time. Meanwhile every fetch was writing
5 days of hourly forecast into ``weather_forecasts`` that nothing
projected. So the overview's weather charts stopped dead at today while
the data to extend them sat one table over.

Projecting forward makes rows on the same (farm, date, index) key mean
two different things, and the difference is not cosmetic — a forecast
value must not feed the climatology baselines, must not be the "now"
reading on the strip, and must be drawn as a distinct segment. Hence an
explicit column rather than an inferred ``date > today`` test, which
would silently reclassify every stored row each midnight.

Existing rows are all observed by construction, so ``DEFAULT FALSE``
backfills them correctly and the column can be NOT NULL immediately.

Revision ID: 0072
Revises: 0071
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0072"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "weather_index_daily",
        sa.Column(
            "is_forecast",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    # The forecast rows themselves go too: without the flag there is no way
    # to tell them from observed history, and leaving them behind would let
    # the baseline sweep average predictions into the climatology.
    op.execute(sa.text("DELETE FROM weather_index_daily WHERE is_forecast"))
    op.drop_column("weather_index_daily", "is_forecast")
