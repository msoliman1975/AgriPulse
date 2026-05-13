"""Weather domain errors. Mirrors `imagery/errors.py` shape."""

from __future__ import annotations

from fastapi import status

from app.core.errors import APIError


class WeatherProviderNotFoundError(APIError):
    """409 raised when a subscription is created against a missing provider_code."""

    def __init__(self, provider_code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Unknown weather provider",
            detail=(
                f"No active weather provider with code {provider_code!r}. "
                "Check public.weather_providers."
            ),
            type_="https://agripulse.cloud/problems/weather/provider-not-found",
        )


class WeatherSubscriptionNotFoundError(APIError):
    def __init__(self, subscription_id: str | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Subscription not found",
            detail=(
                f"No weather subscription with id {subscription_id}"
                if subscription_id
                else "Subscription not found."
            ),
            type_="https://agripulse.cloud/problems/weather/subscription-not-found",
        )


class WeatherSubscriptionAlreadyExistsError(APIError):
    """409 â€” `(block_id, provider_code) WHERE is_active` is unique."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Subscription already exists",
            detail=("An active weather subscription for this block and provider already exists."),
            type_="https://agripulse.cloud/problems/weather/subscription-conflict",
        )


class BlockNotVisibleError(APIError):
    """404 surfaced from weather routes when the caller has no scope on the block.

    Same problem-type URI as imagery's clone so the SPA treats them the same.
    """

    def __init__(self, block_id: str | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Block not found",
            detail=(f"No block with id {block_id}" if block_id else "Block not found."),
            type_="https://agripulse.cloud/problems/farms/block-not-found",
        )
