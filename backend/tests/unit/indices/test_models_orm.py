"""Unit tests for indices ORM model shapes."""

from __future__ import annotations

from app.modules.indices.models import BlockIndexAggregate, IndicesCatalog


def test_indices_catalog_lives_in_public() -> None:
    assert IndicesCatalog.__tablename__ == "indices_catalog"
    assert IndicesCatalog.__table__.schema == "public"
    cols = {c.name for c in IndicesCatalog.__table__.columns}
    assert {
        "id",
        "code",
        "name_en",
        "name_ar",
        "formula_text",
        "value_min",
        "value_max",
        "physical_meaning",
        "is_standard",
    }.issubset(cols)


def test_block_index_aggregate_lives_in_tenant_schema() -> None:
    assert BlockIndexAggregate.__tablename__ == "block_index_aggregates"
    assert BlockIndexAggregate.__table__.schema is None


def test_block_index_aggregate_has_all_stat_columns() -> None:
    cols = {c.name for c in BlockIndexAggregate.__table__.columns}
    expected = {
        "time",
        "block_id",
        "index_code",
        "product_id",
        "mean",
        "min",
        "max",
        "p10",
        "p50",
        "p90",
        "std_dev",
        "valid_pixel_count",
        "total_pixel_count",
        "valid_pixel_pct",
        "cloud_cover_pct",
        "stac_item_id",
        "inserted_at",
    }
    assert expected.issubset(cols)


def test_block_index_aggregate_valid_pixel_pct_is_generated() -> None:
    """`valid_pixel_pct` is a stored generated column — never settable."""
    col = BlockIndexAggregate.__table__.c.valid_pixel_pct
    assert col.computed is not None
    assert col.computed.persisted is True


def test_block_index_aggregate_unique_key_for_idempotency() -> None:
    """The composite UNIQUE on (time, block_id, index_code, product_id)
    is the per-scene idempotency key per Q5 in the PR-A plan.
    """
    uniques = [
        c
        for c in BlockIndexAggregate.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    target = next(
        (
            uq
            for uq in uniques
            if {col.name for col in uq.columns} == {"time", "block_id", "index_code", "product_id"}
        ),
        None,
    )
    assert target is not None, "Expected idempotency-key unique constraint"
