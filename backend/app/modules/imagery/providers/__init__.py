"""Imagery provider adapters.

Each provider implements `app.modules.imagery.providers.protocol.ImageryProvider`.
Concrete adapters (e.g., `SentinelHubProvider`, future `PlanetScopeProvider`)
live next to the Protocol and are wired by `service.py` via dependency
injection.
"""

from app.modules.imagery.providers.protocol import (
    DiscoveredScene,
    FetchResult,
    ImageryProvider,
)

__all__ = [
    "DiscoveredScene",
    "FetchResult",
    "ImageryProvider",
]
