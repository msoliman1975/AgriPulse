"""Billing domain errors. Routers map these to HTTP; nothing else should."""

from __future__ import annotations


class BillingError(RuntimeError):
    """Base for every error this module raises."""


class SignupNotFoundError(BillingError):
    """No trial signup with that id or handle."""


class VerificationTokenError(BillingError):
    """The verification token is unknown, already used, or expired.

    One error for all three on purpose. Telling a caller which of the three
    it was hands them a way to probe for valid tokens.
    """


class InvalidTransitionError(BillingError):
    """The signup is not in a state where this action makes sense.

    Carries both states so the caller can say what happened without
    guessing.
    """

    def __init__(self, *, current: str, action: str) -> None:
        super().__init__(f"cannot {action} a signup in state {current!r}")
        self.current = current
        self.action = action


class CapReachedError(BillingError):
    """A provisioning cap is reached and no override was given.

    Carries the numbers so the API can say which cap, at what value, and
    when it resets, rather than a bare refusal.
    """

    def __init__(self, *, scope: str, used: int, cap: int, resets_at: str) -> None:
        super().__init__(f"{scope} provisioning cap reached: {used}/{cap}")
        self.scope = scope
        self.used = used
        self.cap = cap
        self.resets_at = resets_at


class DuplicateSignupError(BillingError):
    """A live signup already exists for this address or company domain."""
