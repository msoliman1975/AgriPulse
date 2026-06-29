"""Country catalog: public.countries.

Platform-curated reference list of countries used to target Decision Trees
(and, via the logical cross-schema ref on tenant_<id>.farms.country_code,
to locate a farm). Curated by platform admins; tenants only read.

Codes are ISO 3166-1 alpha-2 (immutable, the cross-consumer targeting key).
Seeded with the MENA region AgriPulse operates in; extend via the admin
catalog endpoints.

Revision ID: 0043
Revises: 0042
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043"
down_revision: str | Sequence[str] | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (code, name_en, name_ar)
_COUNTRIES: tuple[tuple[str, str, str], ...] = (
    ("EG", "Egypt", "مصر"),
    ("JO", "Jordan", "الأردن"),
    ("SA", "Saudi Arabia", "المملكة العربية السعودية"),
    ("AE", "United Arab Emirates", "الإمارات العربية المتحدة"),
    ("MA", "Morocco", "المغرب"),
    ("TN", "Tunisia", "تونس"),
    ("DZ", "Algeria", "الجزائر"),
    ("LY", "Libya", "ليبيا"),
    ("SD", "Sudan", "السودان"),
    ("IQ", "Iraq", "العراق"),
    ("PS", "Palestine", "فلسطين"),
    ("LB", "Lebanon", "لبنان"),
    ("SY", "Syria", "سوريا"),
    ("OM", "Oman", "عُمان"),
    ("KW", "Kuwait", "الكويت"),
    ("QA", "Qatar", "قطر"),
    ("BH", "Bahrain", "البحرين"),
    ("YE", "Yemen", "اليمن"),
)


def upgrade() -> None:
    op.create_table(
        "countries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", name="uq_countries_code"),
        sa.CheckConstraint("code = upper(code)", name="ck_countries_code_upper"),
    )
    op.create_index(
        "ix_countries_active",
        "countries",
        ["name_en"],
        postgresql_where=sa.text("is_active = TRUE"),
    )
    op.execute(
        "CREATE TRIGGER trg_countries_updated_at "
        "BEFORE UPDATE ON public.countries "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- Seed (idempotent) --------------------------------------------------
    countries = sa.table(
        "countries",
        sa.column("code", sa.Text),
        sa.column("name_en", sa.Text),
        sa.column("name_ar", sa.Text),
    )
    op.bulk_insert(
        countries,
        [{"code": c, "name_en": en, "name_ar": ar} for (c, en, ar) in _COUNTRIES],
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_countries_updated_at ON public.countries")
    op.drop_index("ix_countries_active", table_name="countries")
    op.drop_table("countries")
