"""Crop / variety threshold enrichment — PR-2 of FarmDM rollout.

The agronomy engine (alerts, recommendations, irrigation scheduling) is
crop-aware. It needs three pieces of catalog data the proposal puts on
``CROP_VARIETY``:

  1. Default rule thresholds (NDVI deviation, irrigation deficit,
     frost cutoff, etc.) — platform-curated defaults that engines
     consult before per-tenant ``rule_overrides`` apply (PR-5).
  2. Variety-specific phenology overrides — most varieties inherit the
     crop's stages, a few (e.g. early-maturing maize) need their own.

This migration:

  * Adds ``crops.default_thresholds`` (JSONB nullable) so every variety
    of a crop inherits sane platform defaults if not overridden.
  * Adds ``crop_varieties.default_thresholds`` (JSONB nullable) for
    per-variety tuning. Resolution is a shallow merge over the crop
    defaults — see ``app.modules.farms.crop_thresholds.resolve``.
  * Adds ``crop_varieties.phenology_stages_override`` (JSONB nullable)
    that replaces the crop's ``phenology_stages`` array wholesale when
    set (the array is too irregular to merge keywise).

All three are nullable so existing rows backfill to NULL. Engine
consumers treat NULL as "no overrides — use whatever the next layer
provides" (crop default → built-in fallback).

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crops",
        sa.Column(
            "default_thresholds",
            postgresql.JSONB(),
            nullable=True,
        ),
        schema="public",
    )
    op.add_column(
        "crop_varieties",
        sa.Column(
            "default_thresholds",
            postgresql.JSONB(),
            nullable=True,
        ),
        schema="public",
    )
    op.add_column(
        "crop_varieties",
        sa.Column(
            "phenology_stages_override",
            postgresql.JSONB(),
            nullable=True,
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("crop_varieties", "phenology_stages_override", schema="public")
    op.drop_column("crop_varieties", "default_thresholds", schema="public")
    op.drop_column("crops", "default_thresholds", schema="public")
