"""Public surface for the `irrigation` module — model-driven daily
watering recommendations.

Other modules import `IrrigationService` (Protocol) and the factory;
the internals are forbidden by the import-linter contract.
"""

from app.modules.irrigation.service import IrrigationService, get_irrigation_service

__all__ = ["IrrigationService", "get_irrigation_service"]
