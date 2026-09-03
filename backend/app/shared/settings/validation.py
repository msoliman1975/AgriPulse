"""Shared write-side validation for settings values.

Every tier that accepts a value — the platform-defaults editor, the tenant
Integrations pages, and the platform-side per-tenant editor — runs the same
two checks:

  1. the JSON type matches the key's ``value_schema``;
  2. the value satisfies the key's :mod:`~app.shared.settings.constraints`
     entry (range / choices), if it has one.

Before this existed only (1) ran, and only on the platform tier; tenant
overrides were written unvalidated straight through ``json.dumps``.
"""

from __future__ import annotations

from typing import Any

from app.shared.settings.constraints import constraint_for
from app.shared.settings.errors import SettingValueError


def validate_value(*, key: str, value: Any, value_schema: str) -> None:
    """Raise :class:`SettingValueError` if `value` is not writable to `key`."""
    _check_schema(key=key, value=value, value_schema=value_schema)
    _check_constraint(key=key, value=value)


def _check_schema(*, key: str, value: Any, value_schema: str) -> None:
    constraint = constraint_for(key)
    if value is None:
        # `string` has always tolerated null (that is how `email.smtp_host`
        # encoded "fall back to the env config"). Other schemas only allow
        # it when the key opts in.
        if value_schema == "string" or (constraint is not None and constraint.nullable):
            return
        raise SettingValueError(
            key=key,
            detail=f"Setting {key!r} expects value_schema={value_schema!r} and may not be null.",
            expected_schema=value_schema,
        )

    ok: bool
    if value_schema == "string":
        ok = isinstance(value, str)
    elif value_schema == "number":
        ok = isinstance(value, int | float) and not isinstance(value, bool)
    elif value_schema == "boolean":
        ok = isinstance(value, bool)
    elif value_schema == "object":
        ok = isinstance(value, dict)
    elif value_schema == "array":
        ok = isinstance(value, list)
    else:
        ok = True
    if ok:
        return
    raise SettingValueError(
        key=key,
        detail=(
            f"Setting {key!r} expects value_schema={value_schema!r} "
            f"but got {type(value).__name__}."
        ),
        expected_schema=value_schema,
    )


def _check_constraint(*, key: str, value: Any) -> None:
    constraint = constraint_for(key)
    if constraint is None or value is None:
        return

    if constraint.choices is not None and value not in constraint.choices:
        allowed = ", ".join(repr(c) for c in constraint.choices)
        raise SettingValueError(
            key=key,
            detail=f"Setting {key!r} must be one of: {allowed}. Got {value!r}.",
            constraint=constraint.as_dict(),
        )

    if constraint.numeric_choices is not None:
        numeric = isinstance(value, int | float) and not isinstance(value, bool)
        if not numeric or float(value) not in {float(c) for c in constraint.numeric_choices}:
            allowed = ", ".join(str(c) for c in constraint.numeric_choices)
            raise SettingValueError(
                key=key,
                detail=f"Setting {key!r} must be one of: {allowed}. Got {value!r}.",
                constraint=constraint.as_dict(),
            )

    if isinstance(value, int | float) and not isinstance(value, bool):
        if constraint.integer_only and float(value) != int(value):
            raise SettingValueError(
                key=key,
                detail=f"Setting {key!r} must be a whole number. Got {value!r}.",
                constraint=constraint.as_dict(),
            )
        if constraint.minimum is not None and value < constraint.minimum:
            raise SettingValueError(
                key=key,
                detail=f"Setting {key!r} must be >= {constraint.minimum}. Got {value!r}.",
                constraint=constraint.as_dict(),
            )
        if constraint.maximum is not None and value > constraint.maximum:
            raise SettingValueError(
                key=key,
                detail=f"Setting {key!r} must be <= {constraint.maximum}. Got {value!r}.",
                constraint=constraint.as_dict(),
            )
