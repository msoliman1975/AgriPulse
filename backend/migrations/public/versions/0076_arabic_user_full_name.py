"""Add an Arabic display name to `public.users`.

Migration 0075 gave every named platform entity an Arabic column, but the
one name a tenant user sees most often was left out: the name of another
person. `users.full_name` is a single free-text column, so the Arabic
pages show `Mohamed Soliman` in a list of Arabic block names, and a field
flag comment is signed in Latin script.

`full_name` cannot simply be translated, because it is written by the
login path: `upsert_from_jwt` copies the name out of the Keycloak token
on every sign-in. Anything written into `full_name` by the tenant is
overwritten the next time that person logs in.

So the Arabic name is a separate column that the login path never
touches. It is set by whoever invites or edits the person, and readers
fall back with `COALESCE(NULLIF(full_name_ar, ''), full_name)`.

No backfill copies English into it. That is deliberate and differs from
0075. A person's name in Latin script is already readable inside an
Arabic sentence, and copying it would make an unauthored name
indistinguishable from a real Arabic one, so nobody would know which
rows still need attention.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076"
down_revision: str | Sequence[str] | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("full_name_ar", sa.Text(), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("users", "full_name_ar", schema="public")
