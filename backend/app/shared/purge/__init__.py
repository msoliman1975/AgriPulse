"""Hard-delete (purge) infrastructure.

Archive/inactivate is the tenant-facing, reversible verb. *Purge* is the
platform-admin-only, irreversible one: it removes an entity and everything it
owns — DB rows, object-storage assets, STAC records — leaving nothing behind.

The guarantee that "nothing is left behind" comes from :mod:`registry`, a
declarative manifest of every table an entity owns. Both the preview and the
delete are generated from that one manifest, so they cannot drift apart, and a
guard test (``tests/unit/shared/test_purge_registry.py``) fails CI when a
migration adds an ownership column that nobody registered.
"""

from app.shared.purge.registry import (
    BLOCK_CAGGS,
    BLOCK_OWNED,
    FARM_OWNED,
    OWNERSHIP_COLUMNS,
    TENANT_PUBLIC_OWNED,
    OwnedTable,
    UnownedColumnError,
    registered_pairs,
)

__all__ = [
    "BLOCK_CAGGS",
    "BLOCK_OWNED",
    "FARM_OWNED",
    "OWNERSHIP_COLUMNS",
    "TENANT_PUBLIC_OWNED",
    "OwnedTable",
    "UnownedColumnError",
    "registered_pairs",
]
