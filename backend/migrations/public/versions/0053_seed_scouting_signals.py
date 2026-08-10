"""Seed the platform-curated scouting form catalog (T6).

Nine signal definitions and five templates, inserted as **platform** rows
(``tenant_id IS NULL``) so every tenant reads the same scouting vocabulary and
an improvement to a form reaches everybody. This is the S0 gate for the mobile
scouting app: without these, there is no form to render and no app.

Why data lives in a migration rather than a YAML seeder
-------------------------------------------------------
Decision trees are YAML + ``loader.sync_from_disk()`` because they carry
scientific provenance — ``evidence`` blocks with DOIs and transferability
ratings — that deserves code review and a diff. Signal definitions are
vocabulary, not claims, and they are authored in the UI at ``/platform/signals``.
Seeding them from a file-based syncer that re-runs on every API start would
overwrite a platform admin's edit on the next deploy. A one-shot data migration
has no such conflict: it establishes the baseline and then gets out of the way.

Idempotent by ``NOT EXISTS`` on (code, platform scope) rather than
``ON CONFLICT``, so re-running is a no-op and a tenant that already authored a
colliding code is unaffected — its row shadows the platform one (see
``snapshot.py``).

Aggregation choices are constrained by the engine, not by taste:
``mean``/``max``/``min``/``sum`` are numeric-only; ``count`` works on any
value_kind (it counts rows); everything non-numeric coerces to ``latest`` in
``signals/snapshot.py``. ``disease_severity`` is therefore ``latest`` and not
``max`` — an earlier draft of the spec asked for ``max`` over a 7-day window,
which reads well but is silently coerced for a categorical, so recording it
here would misdescribe what the engine does.

Revision ID: 0053
Revises: 0052
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | Sequence[str] | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (code, name, value_kind, categorical_values, unit, value_min, value_max,
#  attachment_allowed, aggregation, aggregation_window_days, description)
_DEFINITIONS: tuple[tuple, ...] = (
    (
        "canopy_vigour",
        "Canopy vigour",
        "categorical",
        ["good", "fair", "poor", "severe"],
        None,
        None,
        None,
        True,
        "latest",
        None,
        "Overall visual condition of the canopy at the point of inspection.",
    ),
    (
        "stress_cause_observed",
        "Observed cause of stress",
        "categorical",
        [
            "water",
            "pest",
            "disease",
            "nutrition",
            "salinity",
            "mechanical",
            "none",
            "unknown",
        ],
        None,
        None,
        None,
        True,
        "latest",
        None,
        "What the scout attributes the stress to. 'none' is a real answer and "
        "is how a false-positive alert gets recorded as such.",
    ),
    (
        "pest_incidence_pct",
        "Pest incidence",
        "numeric",
        None,
        "%",
        0,
        100,
        True,
        "mean",
        7,
        "Share of inspected plants showing pest damage.",
    ),
    (
        "disease_symptom",
        "Disease symptom",
        "categorical",
        [
            "leaf_spot",
            "powdery",
            "anthracnose",
            "wilt",
            "chlorosis",
            "necrosis",
            "none",
        ],
        None,
        None,
        None,
        True,
        "latest",
        None,
        "Symptom observed, not a diagnosis — attribution happens downstream.",
    ),
    (
        "disease_severity",
        "Disease severity",
        "categorical",
        ["none", "trace", "moderate", "severe"],
        None,
        None,
        None,
        True,
        # Categorical: any non-`latest`, non-`count` rule is coerced to
        # `latest` by the engine, so state `latest` rather than imply a
        # windowed max the evaluator will never apply.
        "latest",
        None,
        "How far the symptom has progressed where it was found.",
    ),
    (
        "soil_moisture_feel",
        "Soil moisture (by feel)",
        "categorical",
        ["dry", "moist", "wet", "saturated"],
        None,
        None,
        None,
        # No camera: a handful of soil photographs identically wet or dry.
        False,
        "latest",
        None,
        "Hand-feel assessment at root depth. Deliberately coarse — it is a "
        "cross-check on irrigation, not a measurement.",
    ),
    (
        "irrigation_fault",
        "Irrigation fault",
        "categorical",
        ["none", "emitter_blocked", "line_leak", "no_pressure", "uneven"],
        None,
        None,
        None,
        True,
        "latest",
        None,
        "Visible fault in the delivery system serving this block.",
    ),
    (
        "weed_pressure",
        "Weed pressure",
        "categorical",
        ["none", "light", "moderate", "heavy"],
        None,
        None,
        None,
        True,
        "latest",
        None,
        "Competition observed during a routine round.",
    ),
    (
        "scout_photo",
        "Scout photo",
        "event",
        None,
        None,
        None,
        None,
        True,
        # `count` is valid on any value_kind (CS-14) — it counts rows, so this
        # answers "how much photographic evidence exists for this block lately".
        "count",
        7,
        "A photograph taken during a visit. Each photo is its own observation "
        "row, carrying the GPS fix and clock reading from the moment of the "
        "shutter rather than from submit time.",
    ),
)

# (template_code, name, description, ((definition_code, is_required), ...))
_TEMPLATES: tuple[tuple, ...] = (
    (
        "scout_general_v1",
        "General scouting visit",
        "Default form for a visit raised by a recommendation or an alert.",
        (
            ("canopy_vigour", True),
            ("stress_cause_observed", True),
            ("soil_moisture_feel", False),
            ("scout_photo", True),
        ),
    ),
    (
        "scout_pest_disease_v1",
        "Pest and disease inspection",
        "For visits dispatched against a pest or disease signal.",
        (
            ("disease_symptom", True),
            ("disease_severity", True),
            ("pest_incidence_pct", False),
            ("scout_photo", True),
        ),
    ),
    (
        "scout_irrigation_v1",
        "Irrigation check",
        "For visits raised by irrigation or water-stress signals.",
        (
            ("soil_moisture_feel", True),
            ("irrigation_fault", True),
            ("scout_photo", True),
        ),
    ),
    (
        "scout_routine_v1",
        "Routine round",
        "Walked as part of a scheduled round rather than in response to a signal.",
        (
            ("canopy_vigour", True),
            ("weed_pressure", False),
            ("scout_photo", False),
        ),
    ),
    (
        "scout_quick_v1",
        "Quick log",
        "Scout-initiated walk-up: a photo and a note, nothing else.",
        (("scout_photo", True),),
    ),
)

_PLATFORM_CODES = tuple(d[0] for d in _DEFINITIONS)
_TEMPLATE_CODES = tuple(t[0] for t in _TEMPLATES)


def upgrade() -> None:
    bind = op.get_bind()

    for (
        code,
        name,
        value_kind,
        categorical_values,
        unit,
        value_min,
        value_max,
        attachment_allowed,
        aggregation,
        window_days,
        description,
    ) in _DEFINITIONS:
        bind.execute(
            sa.text(
                """
                INSERT INTO public.signal_definitions (
                    tenant_id, code, name, description, value_kind, unit,
                    categorical_values, value_min, value_max,
                    attachment_allowed, is_active, aggregation,
                    aggregation_window_days
                )
                SELECT NULL, :code, :name, :description, :value_kind, :unit,
                       CAST(:categorical_values AS text[]),
                       :value_min, :value_max, :attachment_allowed, TRUE,
                       :aggregation, :window_days
                 WHERE NOT EXISTS (
                    SELECT 1 FROM public.signal_definitions
                     WHERE code = :code AND tenant_id IS NULL
                 )
                """
            ),
            {
                "code": code,
                "name": name,
                "description": description,
                "value_kind": value_kind,
                "unit": unit,
                "categorical_values": categorical_values,
                "value_min": value_min,
                "value_max": value_max,
                "attachment_allowed": attachment_allowed,
                "aggregation": aggregation,
                "window_days": window_days,
            },
        )

    for template_code, name, description, members in _TEMPLATES:
        bind.execute(
            sa.text(
                """
                INSERT INTO public.signal_templates
                       (tenant_id, code, name, description, is_active)
                SELECT NULL, :code, :name, :description, TRUE
                 WHERE NOT EXISTS (
                    SELECT 1 FROM public.signal_templates
                     WHERE code = :code AND tenant_id IS NULL
                 )
                """
            ),
            {"code": template_code, "name": name, "description": description},
        )
        # Members resolve by code against the platform tier, so the junction
        # never accidentally points at a tenant's shadowing definition.
        for position, (definition_code, is_required) in enumerate(members):
            bind.execute(
                sa.text(
                    """
                    INSERT INTO public.signal_template_definitions
                           (template_id, signal_definition_id, position, is_required)
                    SELECT t.id, d.id, :position, :is_required
                      FROM public.signal_templates t
                      JOIN public.signal_definitions d
                        ON d.code = :definition_code AND d.tenant_id IS NULL
                     WHERE t.code = :template_code AND t.tenant_id IS NULL
                       AND NOT EXISTS (
                          SELECT 1 FROM public.signal_template_definitions x
                           WHERE x.template_id = t.id AND x.signal_definition_id = d.id
                       )
                    """
                ),
                {
                    "template_code": template_code,
                    "definition_code": definition_code,
                    "position": position,
                    "is_required": is_required,
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    # Junction rows cascade off the templates. Tenant-authored rows sharing a
    # code are untouched — every statement is pinned to the platform tier.
    bind.execute(
        sa.text(
            "DELETE FROM public.signal_templates " "WHERE tenant_id IS NULL AND code = ANY(:codes)"
        ),
        {"codes": list(_TEMPLATE_CODES)},
    )
    bind.execute(
        sa.text(
            "DELETE FROM public.signal_definitions "
            "WHERE tenant_id IS NULL AND code = ANY(:codes)"
        ),
        {"codes": list(_PLATFORM_CODES)},
    )
