"""Resolver errors."""

from __future__ import annotations


class SettingNotFoundError(LookupError):
    """Raised when a key is requested that has no platform_defaults row."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Setting key not found: {key!r}")
        self.key = key


class TenantSettingValidationError(ValueError):
    """Raised when an attempted tenant override fails the value-schema check."""

    def __init__(self, key: str, expected: str, got: object) -> None:
        super().__init__(
            f"Tenant override for {key!r} failed value_schema check "
            f"(expected {expected!r}, got {type(got).__name__})"
        )
        self.key = key
        self.expected = expected
        self.got = got
