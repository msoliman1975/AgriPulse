"""The `trial_signups` model and its migration must name the same columns.

This exists because they did not. `TrialSignup` inherits `TimestampedMixin`,
which adds `created_by`, `updated_by` and `deleted_at`; migration 0078 created
only `created_at` and `updated_at`. Nothing failed at migration time — the
table was created happily — and every query the ORM built then named three
columns that did not exist. Eighteen integration tests died on
`UndefinedColumnError`, and only a database could see it.

This check needs no database, so it runs in the unit suite where a mismatch
is caught in seconds rather than after a 30-minute CI job.

It reads the migration as text. That is crude, and it is the point: parsing
the file is the only way to compare the two without a live Postgres.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.billing.models import TrialSignup

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "public"
    / "versions"
    / "0078_trial_signups.py"
)

pytestmark = pytest.mark.skipif(
    not _MIGRATION.exists(),
    reason="migration file absent (renamed or renumbered)",
)


def _migration_columns() -> set[str]:
    source = _MIGRATION.read_text(encoding="utf-8")
    upgrade = source.split("def upgrade")[1].split("def downgrade")[0]
    return set(re.findall(r'sa\.Column\(\s*\n?\s*"([a-z_]+)"', upgrade))


def test_model_and_migration_declare_the_same_columns() -> None:
    model = {column.name for column in TrialSignup.__table__.columns}
    migration = _migration_columns()

    assert not (model - migration), (
        "Columns on the model that the migration never creates. Every query "
        f"the ORM builds will fail: {sorted(model - migration)}"
    )
    assert not (migration - model), (
        "Columns the migration creates that the model does not know about: "
        f"{sorted(migration - model)}"
    )


def test_the_timestamp_mixin_columns_are_all_there() -> None:
    """Named separately so a failure says which three were missed."""
    migration = _migration_columns()
    for column in ("created_at", "created_by", "updated_at", "updated_by", "deleted_at"):
        assert column in migration, f"TimestampedMixin column {column!r} is not in 0078"


def test_the_check_constraint_lists_every_model_status() -> None:
    """The status tuple in the model mirrors a CHECK in the migration.

    Two copies of one list, which is why this is asserted rather than
    trusted.
    """
    from app.modules.billing.models import SIGNUP_STATUSES

    source = _MIGRATION.read_text(encoding="utf-8")
    for status in SIGNUP_STATUSES:
        assert f'"{status}"' in source, f"status {status!r} is not in migration 0078"
