"""Weather-driven disease/pest risk models (Weather-Indices Phase 2, PR-R1).

Pure, side-effect-free library: a registry of per-pathogen accumulation models
that turn a trailing window of daily weather + a block's crop/stage context
into 0-100 risk scores. The daily task, REST surface, condition source, map
overlay and pressure report (PR-R2..R5) all build on this contract.

See ``docs/proposals/weather-indices-first-class.md`` §2.3, §3.
"""

from __future__ import annotations

from app.modules.weather.risk.registry import (
    REGISTRY,
    RiskModelSpec,
    applicable_specs,
    evaluate_risks,
)
from app.modules.weather.risk.types import (
    RiskBlockContext,
    RiskLevel,
    RiskScore,
    RiskWeatherDay,
)

__all__ = [
    "REGISTRY",
    "RiskModelSpec",
    "applicable_specs",
    "evaluate_risks",
    "RiskBlockContext",
    "RiskLevel",
    "RiskScore",
    "RiskWeatherDay",
]
