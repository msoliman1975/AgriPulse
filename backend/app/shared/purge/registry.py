"""Declarative ownership manifest — what a block / farm / tenant owns.

This module is the single source of truth for purge. The engine generates both
the impact preview and the DELETE statements from these tuples, so the numbers
an admin confirms against are produced by the same code that does the work.

Ordering
--------
``order`` is a topological rank, ascending: lower is deleted first. It exists
because four FKs in the tenant schema are ``ON DELETE RESTRICT`` rather than
CASCADE, so a naive delete of the parent fails:

    blocks.parent_unit_id  -> blocks   RESTRICT   (pivot sectors)
    blocks.farm_id         -> farms    RESTRICT
    plan_activities.block_id -> blocks RESTRICT
    public.tenant_subscriptions.tenant_id -> tenants RESTRICT

Two more need ordering for a different reason — they are ``SET NULL``, so
deleting the parent first silently blanks a column on a row we are about to
delete anyway (harmless, but it doubles the write):

    alerts.prescription_activity_id -> plan_activities  SET NULL
    plan_activities.recommendation_id -> recommendations SET NULL

Everything else is CASCADE or unenforced. CASCADE tables are still listed
explicitly: we want them *counted* in the preview, and an explicit DELETE makes
the receipt's per-table row counts real rather than inferred.

Unenforced ownership
--------------------
The rows that actually orphan today are the ones with an ownership column and
no FK at all — hypertables (``audit_events``, ``block_index_aggregates``,
``signal_observations``, ``weather_observations``, ``weather_forecasts``,
``block_grid_aggregates``), the ingestion logs, ``recommendations_history``, and
the cross-schema ``public.farm_scopes`` / ``public.backfill_runs`` /
``public.decision_trees``. Those are precisely why this manifest exists; they
are marked ``fk=False`` below so the guard test can assert we did not simply
inherit the FK graph.
"""

from __future__ import annotations

from dataclasses import dataclass

# The three columns that express "this row belongs to X". The guard test sweeps
# information_schema for these and requires every hit to be registered here or
# explicitly exempted.
OWNERSHIP_COLUMNS: tuple[str, ...] = ("tenant_id", "farm_id", "block_id")


class UnownedColumnError(RuntimeError):
    """A table carries an ownership column that the manifest does not cover."""


@dataclass(frozen=True)
class OwnedTable:
    """One table's relationship to an owning entity.

    ``owner_column`` is the common case — a direct ``block_id`` / ``farm_id`` /
    ``tenant_id`` column. ``where_sql`` covers tables that are owned only
    transitively (``grid_cells`` hangs off ``grid_configs``, ``activity_resources``
    off ``plan_activities``); it must reference the bind parameter ``:ids``.
    """

    table: str
    owner_column: str | None = None
    where_sql: str | None = None
    schema: str = "tenant"
    order: int = 50
    # True when a real FK already cascades this row away. Purely informational:
    # the engine deletes it explicitly either way so the count is honest. False
    # marks the rows that would otherwise orphan.
    fk: bool = True
    hypertable: bool = False
    # Column holding an object-storage key that must be deleted alongside the
    # row. Collected before the DELETE, removed after the transaction commits.
    storage_key_column: str | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if (self.owner_column is None) == (self.where_sql is None):
            raise ValueError(f"{self.table}: set exactly one of owner_column / where_sql")

    def predicate(self) -> str:
        """SQL WHERE fragment selecting this table's rows for ``:ids``."""
        if self.where_sql is not None:
            return self.where_sql
        return f"{self.owner_column} = ANY(:ids)"

    def qualified(self) -> str:
        # Tenant-schema statements run with search_path already set, so the bare
        # name is correct there; public tables are always schema-qualified.
        return self.table if self.schema == "tenant" else f"public.{self.table}"


# --- Block -----------------------------------------------------------------
#
# Order bands: 10 = leaf data, 20 = rows other owned rows point at,
# 30 = plan_activities (RESTRICT on blocks), 40 = child sector blocks.
# The block row itself is deleted by the engine, not listed here.

BLOCK_OWNED: tuple[OwnedTable, ...] = (
    # -- leaf data ----------------------------------------------------------
    OwnedTable("alerts", owner_column="block_id", order=10),
    OwnedTable(
        "block_attachments",
        owner_column="block_id",
        order=10,
        storage_key_column="s3_key",
    ),
    OwnedTable("block_index_baselines", owner_column="block_id", order=10),
    OwnedTable(
        "block_index_aggregates",
        owner_column="block_id",
        order=10,
        fk=False,
        hypertable=True,
        note="source of the block_index_daily/weekly continuous aggregates",
    ),
    OwnedTable(
        "block_grid_aggregates",
        owner_column="block_id",
        order=10,
        fk=False,
        hypertable=True,
    ),
    OwnedTable("growth_stage_logs", owner_column="block_id", order=10),
    OwnedTable(
        "imagery_ingestion_jobs",
        owner_column="block_id",
        order=10,
        fk=False,
        note="FK reaches only imagery_aoi_subscriptions; block_id is unenforced",
    ),
    OwnedTable("irrigation_schedules", owner_column="block_id", order=10),
    OwnedTable("recommendations_history", owner_column="block_id", order=10, fk=False),
    OwnedTable(
        "signal_observations",
        owner_column="block_id",
        order=10,
        fk=False,
        hypertable=True,
        storage_key_column="attachment_s3_key",
    ),
    OwnedTable(
        "weather_ingestion_attempts",
        owner_column="block_id",
        order=10,
        fk=False,
        note="FK reaches only weather_subscriptions; block_id is unenforced",
    ),
    OwnedTable("weather_risk_daily", owner_column="block_id", order=10),
    OwnedTable(
        "grid_cells",
        where_sql="grid_config_id IN (SELECT id FROM grid_configs WHERE block_id = ANY(:ids))",
        order=10,
        note="owned transitively through grid_configs",
    ),
    OwnedTable(
        "activity_resources",
        where_sql="activity_id IN (SELECT id FROM plan_activities WHERE block_id = ANY(:ids))",
        order=10,
        note="owned transitively through plan_activities",
    ),
    # -- rows the leaves point at -------------------------------------------
    OwnedTable("block_crops", owner_column="block_id", order=20),
    OwnedTable("grid_configs", owner_column="block_id", order=20),
    OwnedTable("imagery_aoi_subscriptions", owner_column="block_id", order=20),
    OwnedTable("weather_subscriptions", owner_column="block_id", order=20),
    OwnedTable("signal_assignments", owner_column="block_id", order=20),
    OwnedTable(
        "recommendations",
        owner_column="block_id",
        order=20,
        note="plan_activities.recommendation_id is SET NULL — delete before activities",
    ),
    # -- RESTRICT on blocks: must precede the block row ---------------------
    OwnedTable(
        "plan_activities",
        owner_column="block_id",
        order=30,
        note="ON DELETE RESTRICT — the block row cannot go until these do",
    ),
)

# Continuous aggregates over block_index_aggregates. Both run with
# `materialized_only = false` (real-time aggregation), so deleting the source
# rows is not enough: already-materialised buckets keep serving the purged
# block's numbers to every chart until the aggregate is refreshed.
#
# `refresh_continuous_aggregate` cannot run inside a transaction block, so the
# engine defers these to a post-commit phase on an autocommit connection.
BLOCK_CAGGS: tuple[tuple[str, str], ...] = (
    ("block_index_daily", "block_index_aggregates"),
    ("block_index_weekly", "block_index_aggregates"),
)


# --- Farm ------------------------------------------------------------------
#
# Child blocks are purged first by the engine (recursing through BLOCK_OWNED),
# because blocks.farm_id is RESTRICT. What remains here is farm-level data plus
# the farm-scoped columns on tables that are *also* block-scoped — a
# recommendation or signal observation can be attached to a farm with no block.

FARM_OWNED: tuple[OwnedTable, ...] = (
    OwnedTable(
        "audit_events",
        owner_column="farm_id",
        order=10,
        fk=False,
        hypertable=True,
        note="tenant-scoped audit trail; the platform archive in "
        "public.audit_events_archive is what survives",
    ),
    OwnedTable(
        "farm_attachments",
        owner_column="farm_id",
        order=10,
        storage_key_column="s3_key",
    ),
    OwnedTable("farm_imagery_overrides", owner_column="farm_id", order=10),
    OwnedTable("farm_imagery_template", owner_column="farm_id", order=10),
    OwnedTable("farm_weather_overrides", owner_column="farm_id", order=10),
    OwnedTable("farm_weather_template", owner_column="farm_id", order=10),
    OwnedTable("weather_derived_daily", owner_column="farm_id", order=10),
    OwnedTable("weather_index_baselines", owner_column="farm_id", order=10),
    OwnedTable("weather_index_daily", owner_column="farm_id", order=10),
    OwnedTable(
        "weather_observations",
        owner_column="farm_id",
        order=10,
        fk=False,
        hypertable=True,
    ),
    OwnedTable(
        "weather_forecasts",
        owner_column="farm_id",
        order=10,
        fk=False,
        hypertable=True,
    ),
    OwnedTable("weather_ingestion_attempts", owner_column="farm_id", order=10, fk=False),
    OwnedTable("recommendations_history", owner_column="farm_id", order=10, fk=False),
    OwnedTable(
        "signal_observations",
        owner_column="farm_id",
        order=10,
        fk=False,
        hypertable=True,
        storage_key_column="attachment_s3_key",
    ),
    OwnedTable(
        "activity_resources",
        where_sql="activity_id IN (SELECT id FROM plan_activities WHERE farm_id = ANY(:ids))",
        order=10,
    ),
    OwnedTable("signal_assignments", owner_column="farm_id", order=20),
    OwnedTable("recommendations", owner_column="farm_id", order=20, fk=False),
    OwnedTable("plan_activities", owner_column="farm_id", order=30),
    OwnedTable("vegetation_plans", owner_column="farm_id", order=40),
    OwnedTable("resources", owner_column="farm_id", order=40),
    # -- public-schema rows keyed by farm_id --------------------------------
    # These are the cross-schema leaks: no FK can reach across schemas, so
    # nothing cleans them up today. farm_scopes has a dedicated hourly detector
    # (farms/consistency_check.py) that reports orphans and never deletes them.
    OwnedTable("farm_scopes", owner_column="farm_id", schema="public", order=10, fk=False),
    OwnedTable("backfill_runs", owner_column="farm_id", schema="public", order=10, fk=False),
)


# --- Tenant ----------------------------------------------------------------
#
# The tenant schema is removed wholesale by DROP SCHEMA ... CASCADE, so nothing
# tenant-schema lives here. This manifest covers only the public-schema residue,
# which is where every observed tenant-purge orphan has come from.

TENANT_PUBLIC_OWNED: tuple[OwnedTable, ...] = (
    OwnedTable(
        "decision_trees",
        owner_column="tenant_id",
        schema="public",
        order=10,
        fk=False,
        note="tenant-authored trees; decision_tree_versions cascades off this",
    ),
    OwnedTable("backfill_runs", owner_column="tenant_id", schema="public", order=10, fk=False),
    OwnedTable("tenant_settings_overrides", owner_column="tenant_id", schema="public", order=10),
    OwnedTable(
        "tenant_memberships",
        owner_column="tenant_id",
        schema="public",
        order=20,
        note="public.farm_scopes cascades off this",
    ),
    OwnedTable("tenant_settings", owner_column="tenant_id", schema="public", order=20),
    OwnedTable(
        "tenant_subscriptions",
        owner_column="tenant_id",
        schema="public",
        order=30,
        note="ON DELETE RESTRICT — must precede the tenants row",
    ),
)


# --- Guard-test support ----------------------------------------------------

# (table, column) pairs that legitimately carry an ownership column but are not
# purge targets. Every entry needs a reason; the guard test prints them.
EXEMPT_PAIRS: dict[tuple[str, str], str] = {
    # The whole point of the platform archive is to outlive the tenant it
    # describes — purge writes to it rather than deleting from it.
    ("audit_events_archive", "tenant_id"): "deliberately survives tenant purge",
    ("audit_events_archive", "farm_id"): "deliberately survives tenant purge",
    # Purge's own records. The receipt is the tombstone — after a purge it is
    # the only remaining evidence the entity existed — and the job is the log of
    # how it was removed. Deleting either as part of the purge would erase the
    # proof that the purge happened.
    ("purge_jobs", "tenant_id"): "purge's own operational log",
    ("purge_receipts", "tenant_id"): "the tombstone; outliving its subject is the point",
    # The entity rows themselves. The engine deletes these directly after
    # walking the manifest, so registering them would double-delete.
    ("blocks", "farm_id"): "the block row itself; deleted by the engine",
    ("tenants", "tenant_id"): "the tenant row itself; deleted by the engine",
    # Views and continuous aggregates are not independently deletable; they
    # follow their source tables (CAGGs via BLOCK_CAGGS refresh).
    ("block_index_daily", "block_id"): "continuous aggregate over block_index_aggregates",
    ("block_index_weekly", "block_id"): "continuous aggregate over block_index_aggregates",
    ("v_block_integration_health", "block_id"): "view",
    ("v_block_integration_health", "farm_id"): "view",
    ("v_farm_integration_health", "farm_id"): "view",
    ("v_integration_recent_attempts", "block_id"): "view",
    ("v_integration_recent_attempts", "farm_id"): "view",
}


def registered_pairs() -> set[tuple[str, str]]:
    """Every ``(table, owner_column)`` the manifest covers.

    Transitively-owned tables (``where_sql``) contribute their table name with a
    ``None`` column and are matched by table name alone in the guard test.
    """
    pairs: set[tuple[str, str]] = set()
    for group in (BLOCK_OWNED, FARM_OWNED, TENANT_PUBLIC_OWNED):
        for owned in group:
            if owned.owner_column is not None:
                pairs.add((owned.table, owned.owner_column))
    return pairs


def all_owned() -> tuple[OwnedTable, ...]:
    return BLOCK_OWNED + FARM_OWNED + TENANT_PUBLIC_OWNED


def ordered(group: tuple[OwnedTable, ...]) -> list[OwnedTable]:
    """Manifest entries in delete order (ascending ``order``, then table name)."""
    return sorted(group, key=lambda t: (t.order, t.table))
