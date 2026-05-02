"""Imagery domain errors.

Each subclass carries a stable problem-type URI plus the HTTP status the
FastAPI exception handler will surface. `SentinelHubNotConfiguredError`
is intentionally a 503 (service unavailable) — the API itself is up,
the upstream provider is misconfigured. The Celery task path catches
it and writes a `failed` job with `error_message='sentinel_hub_not_configured'`
rather than re-raising; see PR-B.
"""

from __future__ import annotations

from fastapi import status

from app.core.errors import APIError


class SentinelHubNotConfiguredError(APIError):
    """Raised when SentinelHubProvider is constructed without credentials.

    Surfaces as a 503 from API endpoints; logged + recorded as a failed
    ingestion job by the Celery task path.
    """

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            title="Sentinel Hub not configured",
            detail=(
                "Sentinel Hub OAuth credentials are missing. "
                "Set SENTINEL_HUB_CLIENT_ID and SENTINEL_HUB_CLIENT_SECRET."
            ),
            type_="https://missionagre.io/problems/imagery/not-configured",
        )


class SubscriptionNotFoundError(APIError):
    def __init__(self, subscription_id: str | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Subscription not found",
            detail=(
                f"No imagery subscription with id {subscription_id}"
                if subscription_id
                else "Subscription not found."
            ),
            type_="https://missionagre.io/problems/imagery/subscription-not-found",
        )


class IngestionJobNotFoundError(APIError):
    def __init__(self, job_id: str | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Ingestion job not found",
            detail=(f"No ingestion job with id {job_id}" if job_id else "Ingestion job not found."),
            type_="https://missionagre.io/problems/imagery/job-not-found",
        )


class ProductNotFoundError(APIError):
    def __init__(self, product_id: str | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Imagery product not found",
            detail=(
                f"No imagery product with id {product_id}"
                if product_id
                else "Imagery product not found."
            ),
            type_="https://missionagre.io/problems/imagery/product-not-found",
        )


class SubscriptionAlreadyExistsError(APIError):
    """Raised on duplicate (block_id, product_id, is_active) — uniqueness violation."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Subscription already exists",
            detail="An active subscription for this block and product already exists.",
            type_="https://missionagre.io/problems/imagery/subscription-conflict",
        )
