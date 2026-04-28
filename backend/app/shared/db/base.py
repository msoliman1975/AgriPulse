"""Declarative ORM base and shared column conventions.

Naming convention follows Alembic's recommended pattern so generated
migrations name constraints deterministically. TimestampedMixin captures
the audit columns described in data_model.md § 1.4.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, registry

if TYPE_CHECKING:
    from sqlalchemy.dialects.postgresql import UUID as PGUUID  # noqa: F401

# Predictable constraint names — Alembic and import-linter both rely on them.
naming_convention = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

mapper_registry = registry(metadata=MetaData(naming_convention=naming_convention))


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    registry = mapper_registry
    metadata = mapper_registry.metadata


class TimestampedMixin:
    """Audit columns per data_model.md § 1.4.

    `created_by` / `updated_by` are nullable for system-created rows.
    `deleted_at` provides soft-delete semantics; partial indexes elsewhere
    filter `WHERE deleted_at IS NULL`.

    A trigger maintains `updated_at` on UPDATE — see migrations.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_by: Mapped[UUID | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_by: Mapped[UUID | None] = mapped_column(nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


# Server-side UUID v7 generator — installed by the public Alembic migration.
# Use as `server_default=text("uuid_generate_v7()")` on PK columns.
UUID_V7_DEFAULT = text("uuid_generate_v7()")
