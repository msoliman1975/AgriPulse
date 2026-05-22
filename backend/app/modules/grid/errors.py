"""Grid-zones domain errors."""

from __future__ import annotations

from fastapi import status

from app.core.errors import APIError


class GridConfigNotFoundError(APIError):
    def __init__(self, block_id: str | None = None, product_id: str | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Grid config not found",
            detail=(
                f"No active grid config for block {block_id}, product {product_id}"
                if block_id and product_id
                else "Grid config not found."
            ),
            type_="https://agripulse.cloud/problems/grid/config-not-found",
        )


class CellSizeInvalidError(APIError):
    """422 — the requested cell size violates a guardrail.

    Detail message names which guardrail tripped so the frontend can
    show a precise hint without re-implementing the rules.
    """

    def __init__(self, *, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Cell size invalid",
            detail=detail,
            type_="https://agripulse.cloud/problems/grid/cell-size-invalid",
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
            type_="https://agripulse.cloud/problems/imagery/product-not-found",
        )
