"""Bootstrap the 33 platform decision trees into the database.

Until now a platform tree was defined by a YAML file, and
``loader.sync_from_disk`` republished it at every startup whose compiled hash
differed. That made the file the owner: nobody could edit a platform tree in
the app, because the next restart would overwrite the edit.

This migration moves the definitions once. From here the database is the only
place a tree is defined, and the app is the only way to change one.

**It inserts where absent and never overwrites.** A tree is skipped when a row
with the same ``code`` and ``tenant_id IS NULL`` already exists, whatever
version that row is on. Every environment that has run the loader already has
all 33, so there the migration is a no-op; a fresh database gets them.

The definitions are read from ``data/0085_platform_decision_trees.json``, which
is the compiled output of the seed YAML at the time this was written. It is
about 900 KB, which is why it is a sibling file rather than a literal in this
module. Alembic does not scan subdirectories for versions, and the backend
image copies ``migrations/`` whole, so the file ships and is not mistaken for a
revision.

This is the last time a tree definition lives in the repository. The YAML files
and the loader are deleted in a later change; between now and then they are a
copy that looks authoritative and is not.

Version 1 of each tree is inserted **published**, because these trees are
already running in every environment and a draft would silently stop them.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0085"
down_revision: str | Sequence[str] | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA = Path(__file__).parent / "data" / "0085_platform_decision_trees.json"


def upgrade() -> None:
    trees = json.loads(_DATA.read_text(encoding="utf-8"))
    conn = op.get_bind()

    inserted = 0
    for tree in trees:
        code = tree["code"]
        existing = conn.execute(
            sa.text(
                "SELECT id FROM public.decision_trees " "WHERE code = :code AND tenant_id IS NULL"
            ),
            {"code": code},
        ).first()
        if existing is not None:
            # Already here — from the loader, or from a re-run of this
            # migration. Leave it exactly as it is, including any version
            # authored in the app since.
            continue

        # Resolve the crop by its stable code, the same way the loader did.
        # A tree whose crop is missing still installs with crop_id NULL; its
        # crop_paths targeting is what the evaluator actually uses.
        crop_id = None
        if tree.get("crop_code"):
            row = conn.execute(
                sa.text("SELECT id FROM public.crops WHERE code = :c AND deleted_at IS NULL"),
                {"c": tree["crop_code"]},
            ).first()
            if row is not None:
                crop_id = row.id

        tree_id = conn.execute(
            sa.text(
                """
                INSERT INTO public.decision_trees
                    (code, tenant_id, name_en, name_ar,
                     description_en, description_ar,
                     crop_id, crop_path, crop_paths, country_codes,
                     soil_textures, scope, applicable_regions, is_active)
                VALUES
                    (:code, NULL, :name_en, :name_ar,
                     :description_en, :description_ar,
                     :crop_id, :crop_path, :crop_paths, :country_codes,
                     :soil_textures, :scope, :applicable_regions, TRUE)
                RETURNING id
                """
            ),
            {
                "code": code,
                "name_en": tree["name_en"],
                "name_ar": tree.get("name_ar"),
                "description_en": tree.get("description_en"),
                "description_ar": tree.get("description_ar"),
                "crop_id": crop_id,
                "crop_path": tree.get("crop_path"),
                "crop_paths": tree.get("crop_paths") or [],
                "country_codes": tree.get("country_codes") or [],
                "soil_textures": tree.get("soil_textures") or [],
                "scope": tree.get("scope") or "block",
                "applicable_regions": tree.get("applicable_regions") or [],
            },
        ).scalar_one()

        version_id = conn.execute(
            sa.text(
                """
                INSERT INTO public.decision_tree_versions
                    (tree_id, version, tree_yaml, tree_compiled, compiled_hash,
                     published_at, published_by, notes)
                VALUES
                    (:tree_id, 1, :tree_yaml, CAST(:tree_compiled AS jsonb),
                     :compiled_hash, now(), NULL,
                     'Platform catalogue, moved from the repository into the database.')
                RETURNING id
                """
            ),
            {
                "tree_id": tree_id,
                "tree_yaml": tree["tree_yaml"],
                "tree_compiled": json.dumps(tree["tree_compiled"], sort_keys=True),
                "compiled_hash": tree["compiled_hash"],
            },
        ).scalar_one()

        conn.execute(
            sa.text("UPDATE public.decision_trees SET current_version_id = :v WHERE id = :t"),
            {"v": version_id, "t": tree_id},
        )
        inserted += 1

    print(f"0085: platform decision trees inserted={inserted} skipped={len(trees) - inserted}")


def downgrade() -> None:
    """Deliberately empty.

    Deleting the trees on a downgrade would take the whole platform
    catalogue away from an environment that has been running them, and would
    also delete any version authored in the app since. The rows are content;
    leaving them is the safe direction.
    """
