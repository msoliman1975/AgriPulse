"""Weather-driven disease/pest risk scores (Weather-Indices PR-R1, Phase 2).

One per-tenant **regular** table, ``weather_risk_daily``, holding the daily
0-100 pressure score per (block, pathogen). This is weather's *spatial*
expression: the raw indices are farm-uniform, but risk folds in each block's
crop / growth-stage / canopy, so it varies block to block even though the
weather driver is the farm centroid.

  * PK ``(block_id, date, risk_code)`` — one score per pathogen per block-day.
  * ``score`` 0-100 (smallint); ``level`` low|moderate|high (banding, CHECKed).
  * ``inputs`` jsonb — the accumulation breakdown that produced the score
    (favourable days, mean favourability, stage factor, degree-days), so the
    map popup + pressure report can show the "why".
  * CASCADE FK to ``blocks`` (block-keyed; risk is per land unit).

The score producer (the daily task), the REST surface, the ``weather_risk``
condition source, the map overlay and the pressure report are PR-R2..R5; this
migration only lands the table the registry library writes into.

Revision ID: 0050
Revises: 0049
Create Date: 2026-06-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0050"
down_revision: str | Sequence[str] | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weather_risk_daily",
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("risk_code", sa.Text(), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        # The favourable-condition accumulation that produced the score.
        # Decimals serialised as strings per the Decimal->string JSON
        # convention shared with weather_index_daily.value_aux.
        sa.Column(
            "inputs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("block_id", "date", "risk_code", name="pk_weather_risk_daily"),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100",
            name="ck_weather_risk_daily_score_range",
        ),
        sa.CheckConstraint(
            "level IN ('low', 'moderate', 'high')",
            name="ck_weather_risk_daily_level",
        ),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["blocks.id"],
            name="fk_weather_risk_daily_block_id_blocks",
            ondelete="CASCADE",
        ),
    )
    # Map-overlay / pressure-report reads filter by (block_id, risk_code,
    # date-range) and "latest level per block per pathogen".
    op.create_index(
        "ix_weather_risk_daily_block_code_date",
        "weather_risk_daily",
        ["block_id", "risk_code", "date"],
    )


def downgrade() -> None:
    op.drop_index("ix_weather_risk_daily_block_code_date", table_name="weather_risk_daily")
    op.drop_table("weather_risk_daily")
