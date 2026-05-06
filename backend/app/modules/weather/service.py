"""WeatherService Protocol.

PR-A declares the public surface that the rest of the platform consumes;
the concrete implementation lands in PR-B (Open-Meteo adapter +
ingestion) and PR-C (derivations + read endpoints). Until then the
Protocol is enough for downstream modules to depend on this module's
contract without coupling to its internals (enforced by the
`weather internals are private` import-linter contract).

Subscriptions are per-block (mirrors imagery's UX) but the underlying
hypertables key on `farm_id` because Open-Meteo's grid is ~9km — see
data_model § 8 and `models.py`.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Protocol
from uuid import UUID


class WeatherService(Protocol):
    """Public contract for the `weather` module.

    Method bodies and DTOs land in PR-B / PR-C. The Protocol is here
    to make the surface inspectable and to lock the names so callers
    in other modules can be wired up before the impl exists.
    """

    # ---- subscriptions (per-block) -----------------------------------
    async def create_subscription(
        self,
        *,
        block_id: UUID,
        provider_code: str,
        cadence_hours: int | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> UUID: ...

    async def list_subscriptions(
        self,
        *,
        block_id: UUID,
        include_inactive: bool = False,
    ) -> tuple[object, ...]: ...

    async def revoke_subscription(
        self,
        *,
        block_id: UUID,
        subscription_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None: ...

    # ---- ingestion ---------------------------------------------------
    async def trigger_refresh(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None: ...

    async def fetch_observations(
        self,
        *,
        farm_id: UUID,
        provider_code: str,
        since: datetime,
        until: datetime,
    ) -> tuple[object, ...]: ...

    async def fetch_forecast(
        self,
        *,
        farm_id: UUID,
        provider_code: str,
        horizon_days: int = 5,
    ) -> tuple[object, ...]: ...

    # ---- derivations -------------------------------------------------
    async def derive_daily(
        self,
        *,
        farm_id: UUID,
        on_date: date_type,
    ) -> None: ...
