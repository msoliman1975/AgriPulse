"""Public surface for the `plans` module (vegetation plans + activities).

Other modules import `PlansService` (Protocol) and the factory; the
internals (repository, models, router, schemas) are forbidden by the
"plans internals are private" import-linter contract.
"""

from app.modules.plans.service import PlansService, get_plans_service

__all__ = ["PlansService", "get_plans_service"]
