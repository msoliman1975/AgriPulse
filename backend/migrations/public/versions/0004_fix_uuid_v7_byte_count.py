"""Fix uuid_generate_v7 byte count.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-29

The function shipped in migration 0001 called ``gen_random_bytes(10)``,
producing only 20 hex characters after ``encode()`` — a UUID needs 32.
Any INSERT relying on the function as a column default failed with
``invalid input syntax for type uuid: "<20 hex chars>"``. Surfaced while
seeding the dev user manually for the local-app demo.

The body is otherwise identical to the original; the only change is the
byte count. CREATE OR REPLACE keeps any existing dependent objects.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_V7_FN_FIXED = """
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
    bytes := gen_random_bytes(16);
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
"""


def upgrade() -> None:
    op.execute(_UUID_V7_FN_FIXED)


def downgrade() -> None:
    # Intentionally a no-op: re-introducing the broken 10-byte version
    # helps no one. Dropping the function would cascade into dependent
    # column defaults (none today, but defensive).
    pass
