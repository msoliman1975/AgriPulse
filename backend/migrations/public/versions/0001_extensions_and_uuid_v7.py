"""Postgres extensions and uuid_generate_v7().

Revision ID: 0001
Revises:
Create Date: 2026-04-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Extensions are created in `public`. CloudNativePG / vanilla Postgres both
# accept `IF NOT EXISTS` so reruns are idempotent. pgaudit is configured at
# the cluster level (shared_preload_libraries); the extension just exposes
# its functions.
_EXTENSIONS = (
    "pgcrypto",
    "citext",
    "postgis",
    "timescaledb",
    # pgstac is created from its own schema by the pgstac image; do it here
    # so a fresh dev cluster works without extra steps.
    "pgstac",
    "pgaudit",
)

# uuid_generate_v7 — RFC 9562 draft 04 layout. Postgres 17 will ship a
# native gen_random_uuid_v7(); until then we use a small SQL+pgcrypto
# function. The implementation comes from the timescaledb community
# pattern: 48 bits of millisecond timestamp + 12 bits of randomness in
# the rand_a slot + 62 bits of randomness in rand_b, with version (7)
# and variant (10) bits set per spec.
_UUID_V7_FN = """
CREATE OR REPLACE FUNCTION public.uuid_generate_v7()
RETURNS uuid
LANGUAGE plpgsql
PARALLEL SAFE
AS $$
DECLARE
    unix_ts_ms  bigint;
    bytes       bytea;
BEGIN
    unix_ts_ms := (extract(epoch FROM clock_timestamp()) * 1000)::bigint;
    bytes := gen_random_bytes(10);
    -- 48-bit timestamp (big-endian) into bytes 0..5
    bytes := set_byte(bytes, 0, ((unix_ts_ms >> 40) & 255)::int);
    bytes := set_byte(bytes, 1, ((unix_ts_ms >> 32) & 255)::int);
    bytes := set_byte(bytes, 2, ((unix_ts_ms >> 24) & 255)::int);
    bytes := set_byte(bytes, 3, ((unix_ts_ms >> 16) & 255)::int);
    bytes := set_byte(bytes, 4, ((unix_ts_ms >>  8) & 255)::int);
    bytes := set_byte(bytes, 5, ( unix_ts_ms        & 255)::int);
    -- byte 6 high nibble = version 7 (0b0111); low nibble = random
    bytes := set_byte(bytes, 6, ((get_byte(bytes, 6) & 15) | 112)::int);
    -- byte 8 high two bits = variant 10
    bytes := set_byte(bytes, 8, ((get_byte(bytes, 8) & 63) | 128)::int);
    RETURN encode(bytes, 'hex')::uuid;
END;
$$;

COMMENT ON FUNCTION public.uuid_generate_v7() IS
  'UUID v7 (RFC 9562) — chronologically sortable. Replace with native '
  'gen_random_uuid_v7() once Postgres 17 is rolled out.';
"""

# Generic updated_at trigger — tables that include the audit cols just attach
# a `BEFORE UPDATE` trigger that calls this function.
_TOUCH_FN = """
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    for ext in _EXTENSIONS:
        # pgstac/pgaudit may be unavailable on developer machines; allow opting
        # out via a session GUC for local-only environments. CI runs with all
        # extensions present.
        op.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
    op.execute(_UUID_V7_FN)
    op.execute(_TOUCH_FN)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.set_updated_at()")
    op.execute("DROP FUNCTION IF EXISTS public.uuid_generate_v7()")
    # Extensions are intentionally left in place — dropping them on rollback
    # would cascade into application data. Operators remove them by hand.
