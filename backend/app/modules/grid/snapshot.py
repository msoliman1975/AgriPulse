"""Load the per-block grid spatial-anomaly snapshot for the engine (G-4).

The recommendations driver calls :func:`load_snapshot` once per block per
evaluation pass and stuffs the result into ``ConditionContext.grid`` so
decision-tree predicates can reference ``{source: grid, index_code,
field}``. Mirrors ``signals.snapshot`` / ``weather.snapshot``: it returns
empty data for blocks without a grid (or without a current anomaly), so
predicates fail closed rather than spuriously firing.

The detection threshold ``k`` resolves three tiers — per-block override
(``grid_configs.anomaly_z_threshold``) -> tenant override -> platform
default — identical to the standalone anomaly sweep, so a tree sees the
same verdict the alert sweep would raise.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.grid.anomaly import DEFAULT_K
from app.modules.grid.service import get_grid_service
from app.shared.conditions import GridAnomalyEntry
from app.shared.settings.errors import SettingNotFoundError
from app.shared.settings.resolver import SettingsResolver

_ANOMALY_K_KEY = "grid.anomaly_z_threshold"


async def _resolve_default_k(
    public_session: AsyncSession,
    tenant_session: AsyncSession,
    tenant_id: UUID,
) -> float:
    """Tenant override -> platform default for the detection threshold.

    Falls back to :data:`DEFAULT_K` when the key/tenant can't be resolved
    so a missing seed never breaks an evaluation pass.
    """
    try:
        resolved = await SettingsResolver(
            public_session=public_session, tenant_session=tenant_session
        ).get_tenant(tenant_id, _ANOMALY_K_KEY)
    except SettingNotFoundError:
        return DEFAULT_K
    try:
        return float(resolved.value)
    except (TypeError, ValueError):
        return DEFAULT_K


async def load_snapshot(
    tenant_session: AsyncSession,
    public_session: AsyncSession,
    *,
    block_id: UUID,
    tenant_id: UUID,
) -> dict[str, GridAnomalyEntry]:
    """``{index_code: GridAnomalyEntry}`` for the block's current anomalies."""
    default_k = await _resolve_default_k(public_session, tenant_session, tenant_id)
    svc = get_grid_service(tenant_session=tenant_session)
    summaries = await svc.snapshot_block_anomalies(block_id=block_id, default_k=default_k)
    out: dict[str, GridAnomalyEntry] = {}
    for index_code, s in summaries.items():
        out[index_code] = GridAnomalyEntry(
            worst_z=Decimal(str(s["worst_z"])),
            flagged_count=s["flagged_count"],
            worst_row=s["worst_row"],
            worst_col=s["worst_col"],
            severity=s["severity"],
        )
    return out
