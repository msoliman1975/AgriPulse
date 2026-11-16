"""Crop image (investor app v2, build plan 3.1).

One image per crop, with an optional per-variety override. The column holds
the S3 key of the uploaded original under ``platform/crop-images/``; the
light worker writes square WebP renditions (64, 128, 256 px) next to it.
Every upload gets a new key, so a URL built from the key can be cached for a
year: a re-upload changes the URL instead of the bytes behind it.

Additive and nullable: no backfill, no existing row changes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0114"
down_revision: str | Sequence[str] | None = "0113"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("crops", "crop_varieties")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"""
            ALTER TABLE public.{table}
                ADD COLUMN image_s3_key text,
                ADD CONSTRAINT ck_{table}_image_s3_key
                    CHECK (image_s3_key IS NULL
                           OR image_s3_key LIKE 'platform/crop-images/%');
            """
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"""
            ALTER TABLE public.{table}
                DROP CONSTRAINT IF EXISTS ck_{table}_image_s3_key,
                DROP COLUMN IF EXISTS image_s3_key;
            """
        )
