"""The platform switch between the old decision-tree engine and the beta one.

The sweep reads the switch row in `public.decision_engine` (public migration
0093) inside its tree query, so flipping the row is enough to change which
trees run on the next pass. What the row cannot do on its own is retire what
the outgoing trees already wrote. That is this module's job, and it runs in
the same transaction as the flip:

  * open and deferred recommendations of an outgoing tree go to ``expired``,
    each with a ``recommendations_history`` row whose reason is
    ``engine_retired``;
  * open, acknowledged and snoozed alerts of an outgoing tree go to
    ``resolved``. Alerts have no history table, so the count per tenant is
    kept on the switch row's ``last_close_out``;
  * current verdicts of an outgoing tree get ``valid_to`` set to the flip
    time, so Farm Health and block health stop showing them while the
    verdict history still does.

One transaction for every tenant. A flip that closed half the tenants and
then failed would leave those tenants with no output from either engine
until the next pass, and the rest with both.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.repository import _rowcount
from app.shared.db.session import sanitize_tenant_schema

Engine = Literal["old", "beta"]

# The tree stage each engine runs. The sweep's tree query holds the same map.
STAGE_FOR_ENGINE: dict[str, str] = {"old": "live", "beta": "beta"}

# The reason written on each history row and read back by anyone asking why
# a card closed with nobody acting on it.
RETIRED_REASON = "engine_retired"


async def read_engine(public_session: AsyncSession) -> dict[str, Any]:
    """The current switch row. A missing row reads as 'old', as the sweep does."""
    row = (
        (
            await public_session.execute(
                text(
                    "SELECT engine, switched_at, switched_by, last_close_out "
                    "FROM public.decision_engine WHERE id = 1"
                )
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return {"engine": "old", "switched_at": None, "switched_by": None, "last_close_out": None}
    return dict(row)


async def switch_engine(
    public_session: AsyncSession, *, to: Engine, actor_user_id: UUID | None
) -> dict[str, Any]:
    """Flip the switch and close the outgoing trees' open output, atomically.

    The caller owns the transaction and commits it. Flipping to the engine
    that already runs changes nothing and closes nothing: ``changed`` is
    False and the row is returned as it stands.
    """
    # Lock the row first. Two admins clicking at once would otherwise both
    # read 'old', both close the live output, and both write 'beta'.
    current = (
        await public_session.execute(
            text("SELECT engine FROM public.decision_engine WHERE id = 1 FOR UPDATE")
        )
    ).scalar_one_or_none()
    if current is None:
        await public_session.execute(
            text("INSERT INTO public.decision_engine (id, engine) VALUES (1, 'old')")
        )
        current = "old"
    if current == to:
        return {**await read_engine(public_session), "changed": False}

    outgoing_stage = STAGE_FOR_ENGINE[current]
    incoming_stage = STAGE_FOR_ENGINE[to]
    trees = (
        await public_session.execute(
            text("SELECT id, code, stage FROM public.decision_trees WHERE stage IN (:o, :i)"),
            {"o": outgoing_stage, "i": incoming_stage},
        )
    ).all()
    outgoing_ids = [r.id for r in trees if r.stage == outgoing_stage]
    outgoing_codes = sorted({r.code for r in trees if r.stage == outgoing_stage})
    # An alert names its tree by code only. A code held by a tree on both
    # sides of the flip cannot say which engine wrote the alert, so it is
    # left open rather than closed on a guess.
    incoming_codes = {r.code for r in trees if r.stage == incoming_stage}
    alert_codes = [c for c in outgoing_codes if c not in incoming_codes]

    schemas = (
        await public_session.execute(
            text(
                "SELECT schema_name FROM public.tenants "
                "WHERE deleted_at IS NULL ORDER BY schema_name"
            )
        )
    ).scalars()

    close_out: dict[str, dict[str, int]] = {}
    for raw in list(schemas):
        schema = sanitize_tenant_schema(str(raw))
        close_out[schema] = await _close_out_tenant(
            public_session,
            schema=schema,
            tree_ids=outgoing_ids,
            alert_codes=alert_codes,
            actor_user_id=actor_user_id,
            engine_from=current,
            engine_to=to,
        )
    # Back to public for the row write, since the loop moved the search_path.
    await public_session.execute(text("SET LOCAL search_path TO public"))

    await public_session.execute(
        text(
            """
            UPDATE public.decision_engine
               SET engine = :to,
                   switched_at = public.app_now(),
                   switched_by = :actor,
                   last_close_out = CAST(:close_out AS jsonb)
             WHERE id = 1
            """
        ).bindparams(bindparam("actor", type_=PG_UUID(as_uuid=True))),
        {
            "to": to,
            "actor": actor_user_id,
            "close_out": _json({"from": current, "to": to, "tenants": close_out}),
        },
    )
    return {**await read_engine(public_session), "changed": True}


async def _close_out_tenant(
    session: AsyncSession,
    *,
    schema: str,
    tree_ids: list[UUID],
    alert_codes: list[str],
    actor_user_id: UUID | None,
    engine_from: str,
    engine_to: str,
) -> dict[str, int]:
    """Close one tenant's open output from the outgoing trees. Returns counts."""
    await session.execute(text(f"SET LOCAL search_path TO {schema}, public"))
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :v, TRUE)"), {"v": schema}
    )
    # History first, from the rows about to change, so each closed card
    # carries one row naming why. Written before the UPDATE because the
    # UPDATE is what takes them out of the 'open'/'deferred' set.
    history = await session.execute(
        text(
            """
            INSERT INTO recommendations_history
                (recommendation_id, block_id, cell_id, farm_id, from_state,
                 to_state, actor_user_id, details)
            -- Each value in jsonb_build_object is cast: a bare bind there has
            -- no type Postgres can infer, and the statement fails to prepare.
            SELECT r.id, r.block_id, r.cell_id, r.farm_id, r.state, 'expired', :actor,
                   jsonb_build_object('reason', CAST(:reason AS text),
                                      'engine_from', CAST(:efrom AS text),
                                      'engine_to', CAST(:eto AS text))
              FROM recommendations r
             WHERE r.state IN ('open', 'deferred')
               AND r.tree_id = ANY(CAST(:ids AS uuid[]))
            """
        ).bindparams(bindparam("actor", type_=PG_UUID(as_uuid=True))),
        {
            "ids": tree_ids,
            "actor": actor_user_id,
            "reason": RETIRED_REASON,
            "efrom": engine_from,
            "eto": engine_to,
        },
    )
    recs = await session.execute(
        text(
            """
            UPDATE recommendations
               SET state = 'expired',
                   deferred_until = NULL,
                   updated_at = public.app_now(),
                   updated_by = :actor
             WHERE state IN ('open', 'deferred')
               AND tree_id = ANY(CAST(:ids AS uuid[]))
            """
        ).bindparams(bindparam("actor", type_=PG_UUID(as_uuid=True))),
        {"ids": tree_ids, "actor": actor_user_id},
    )
    # `tree:<code>:<leaf>` on a parent, `tree:<code>:<leaf>:cell:<uuid>` on a
    # child. The second segment is the tree code on both.
    alerts = await session.execute(
        text(
            """
            UPDATE alerts
               SET status = 'resolved',
                   resolved_at = public.app_now(),
                   resolved_by = :actor,
                   snoozed_until = NULL,
                   updated_at = public.app_now(),
                   updated_by = :actor
             WHERE status IN ('open', 'acknowledged', 'snoozed')
               AND rule_code LIKE 'tree:%'
               AND split_part(rule_code, ':', 2) = ANY(CAST(:codes AS text[]))
            """
        ).bindparams(bindparam("actor", type_=PG_UUID(as_uuid=True))),
        {"codes": alert_codes, "actor": actor_user_id},
    )
    verdicts = await session.execute(
        text(
            """
            UPDATE decision_tree_block_verdicts
               SET valid_to = public.app_now(),
                   updated_at = public.app_now()
             WHERE valid_to IS NULL
               AND tree_id = ANY(CAST(:ids AS uuid[]))
            """
        ),
        {"ids": tree_ids},
    )
    return {
        "recommendations_expired": _rowcount(recs),
        "history_rows": _rowcount(history),
        "alerts_resolved": _rowcount(alerts),
        "verdicts_closed": _rowcount(verdicts),
    }


def _json(value: Any) -> str:
    return json.dumps(value, default=str)
