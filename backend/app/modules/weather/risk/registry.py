"""Registry of weather-driven risk models — the extensible add-only spine.

Adding a pathogen/pest for a new (or existing) crop is a single
:class:`RiskModelSpec` entry plus its pure model function: no schema change,
no task change, no endpoint change. The daily task (PR-R2) calls
:func:`evaluate_risks` per block and persists whatever non-null
:class:`RiskScore` rows come back into ``weather_risk_daily``.

Crop applicability is a path *prefix* match so a model written for ``mango``
fires for every cultivar block (``mango``, ``mango.keitt``,
``mango.keitt.large``) without enumerating them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.modules.weather.risk import models
from app.modules.weather.risk.types import RiskBlockContext, RiskScore, RiskWeatherDay

RiskModel = Callable[[Sequence[RiskWeatherDay], RiskBlockContext], RiskScore | None]

# Default trailing window each accumulation model integrates over (days).
_DEFAULT_WINDOW_DAYS = 14


@dataclass(frozen=True, slots=True)
class RiskModelSpec:
    """One registered risk model and the crops/window it applies to."""

    risk_code: str
    crop_prefix: str
    kind: str  # "disease" | "pest" — for UI grouping + the future risk catalog
    model: RiskModel
    window_days: int = _DEFAULT_WINDOW_DAYS


# The V1 registry: three mango models (proposal §10 Q1 — "mango-first, three").
# Append-only; a new crop/pathogen slots in here as one more spec.
REGISTRY: tuple[RiskModelSpec, ...] = (
    RiskModelSpec("powdery_mildew", "mango", "disease", models.powdery_mildew),
    RiskModelSpec("anthracnose", "mango", "disease", models.anthracnose),
    RiskModelSpec("fruit_fly", "mango", "pest", models.fruit_fly),
)


def _crop_applies(crop_prefix: str, crop_path: str) -> bool:
    """True when ``crop_path`` is the prefix crop or one of its descendants."""
    return crop_path == crop_prefix or crop_path.startswith(crop_prefix + ".")


def applicable_specs(crop_path: str) -> list[RiskModelSpec]:
    """Specs whose crop prefix matches ``crop_path`` (e.g. ``mango.keitt``)."""
    return [s for s in REGISTRY if _crop_applies(s.crop_prefix, crop_path)]


def evaluate_risks(
    windows: dict[str, Sequence[RiskWeatherDay]] | Sequence[RiskWeatherDay],
    ctx: RiskBlockContext,
) -> list[RiskScore]:
    """Run every model applicable to ``ctx.crop_path`` and collect the scores.

    ``windows`` is either a single trailing window reused for all models, or a
    mapping ``{risk_code: window}`` when callers pre-slice per model
    ``window_days``. Models that return ``None`` (insufficient data) are
    dropped, so the result is exactly the rows to upsert.
    """
    out: list[RiskScore] = []
    for spec in applicable_specs(ctx.crop_path):
        window = windows.get(spec.risk_code, ()) if isinstance(windows, dict) else windows
        score = spec.model(window, ctx)
        if score is not None:
            out.append(score)
    return out


__all__ = [
    "RiskModel",
    "RiskModelSpec",
    "REGISTRY",
    "applicable_specs",
    "evaluate_risks",
]
