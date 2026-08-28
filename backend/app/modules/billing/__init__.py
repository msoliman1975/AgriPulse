"""Billing — plans, terms, entitlements, and the self-serve trial front door.

The module is called `billing`, never `subscription`: that noun is already
taken by `ImageryAoiSubscription` and `WeatherSubscription` and reusing it
would make every grep ambiguous. Inside here the vocabulary is plan, term,
price list, rate, meter and entitlement.

This first slice carries only the trial front door:

  * `public_router` — the API's first unauthenticated routes.
  * `trials_router` — the platform review queue.
  * `tasks` — provisioning, triggered by an approval and nothing else.

`docs/proposals/self-serve-trial-flow.md` is the design of record.
"""

from __future__ import annotations

from app.modules.billing.errors import (
    CapReachedError,
    InvalidTransitionError,
    SignupNotFoundError,
    VerificationTokenError,
)
from app.modules.billing.service import TrialService

__all__ = [
    "CapReachedError",
    "InvalidTransitionError",
    "SignupNotFoundError",
    "TrialService",
    "VerificationTokenError",
]
