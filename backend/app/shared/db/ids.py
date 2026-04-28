"""UUID v7 generation in pure Python.

Mirrors the ``public.uuid_generate_v7()`` SQL function from migration
0001 so that server-generated and app-generated identifiers are
interchangeable on every table that uses UUID v7 as its primary key.

Use the SQL default (``server_default=text("uuid_generate_v7()")``)
whenever possible. Use this helper only when the application needs the
ID *before* the INSERT — for example, when a derived value (a tenant's
schema name) must be written into another column of the same row.
"""

from __future__ import annotations

import os
import time
from uuid import UUID


def uuid7() -> UUID:
    """Return a fresh RFC 9562 UUID v7.

    48 bits of millisecond timestamp, 12 bits of randomness in `rand_a`,
    62 bits of randomness in `rand_b`, with version (7) and variant (10)
    bits set per spec. Sortable by creation time across any process
    sharing this clock — Postgres 17 will replace this with a native
    generator.
    """
    unix_ts_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF  # 48-bit
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFFFFFFFFFFFFFF

    int_value = (
        (unix_ts_ms << 80)
        | (0x7 << 76)  # version 7
        | (rand_a << 64)
        | (0b10 << 62)  # variant 10
        | rand_b
    )
    return UUID(int=int_value)


def schema_name_for(tenant_id: UUID) -> str:
    """Return the canonical Postgres schema name for a tenant.

    Hex form (no hyphens) keeps the identifier valid without quoting,
    and matches the regex used by ``app.shared.db.session.sanitize_tenant_schema``.
    """
    return f"tenant_{tenant_id.hex}"
