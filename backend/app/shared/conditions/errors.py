"""Errors raised by the condition language."""

from __future__ import annotations


class ConditionParseError(ValueError):
    """Raised when a condition tree dict cannot be interpreted.

    The evaluator catches this and returns ``(False, {})`` so a
    malformed rule never crashes a sweep — but tests can opt in to
    strict parsing by calling the parse helpers directly.
    """
