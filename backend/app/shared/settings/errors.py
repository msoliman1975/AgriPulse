"""Resolver errors."""

from __future__ import annotations


class SettingNotFoundError(LookupError):
    """Raised when a key is requested that has no platform_defaults row."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Setting key not found: {key!r}")
        self.key = key


class SettingValueError(ValueError):
    """Raised when a write fails the value_schema or per-key constraint check.

    Carries enough detail for the router to build an RFC 7807 body without
    re-deriving why the value was rejected.
    """

    def __init__(
        self,
        *,
        key: str,
        detail: str,
        expected_schema: str | None = None,
        constraint: dict[str, object] | None = None,
    ) -> None:
        super().__init__(detail)
        self.key = key
        self.detail = detail
        self.expected_schema = expected_schema
        self.constraint = constraint

    def extras(self) -> dict[str, object]:
        out: dict[str, object] = {"key": self.key}
        if self.expected_schema is not None:
            out["expected_schema"] = self.expected_schema
        if self.constraint is not None:
            out["constraint"] = self.constraint
        return out


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
