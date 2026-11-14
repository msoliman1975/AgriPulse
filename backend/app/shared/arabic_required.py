"""D26 "Arabic everywhere": platform content is saved with English *and* Arabic.

Every platform-authored catalogue row, signal, finding, tree, parameter
description and readiness note carries an Arabic sibling beside each English
text. The rule is enforced when the row is saved, so a missing translation
fails the author's save with a 422 that names the field, instead of a grower
seeing English inside an Arabic screen.

Backward compatibility is the other half of the rule, and the reason this is
a helper rather than ``min_length=1`` on each schema. Seeded content exists
without Arabic, and resaving it unchanged must keep working. So a pair only
needs Arabic when this save is the one that makes it English text:

  * the record is new (there is no ``before``), or
  * its English text changed, or
  * it had Arabic before and this save clears it.

An untouched English-only field on an existing record is left alone.

Tenant-authored content stays optional: a tenant may run English only. The
callers decide scope; this module only decides what a given save is missing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.core.errors import APIError

ARABIC_REQUIRED_PROBLEM = "https://agripulse.cloud/problems/arabic-required"

# One English field and its Arabic sibling, e.g. ("name_en", "name_ar").
Pair = tuple[str, str]


def is_blank(value: Any) -> bool:
    """None, an empty string or whitespace only. Non-strings are not blank."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _norm(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def pair_needs_arabic(
    *,
    en_after: Any,
    ar_after: Any,
    en_before: Any = None,
    ar_before: Any = None,
    is_new: bool,
) -> bool:
    """True when this save leaves English text without the Arabic it needs."""
    if is_blank(en_after) or not is_blank(ar_after):
        return False
    if is_new:
        return True
    if _norm(en_after) != _norm(en_before):
        return True
    # English unchanged: only a save that clears existing Arabic is refused.
    return not is_blank(ar_before)


def missing_arabic(
    after: Mapping[str, Any],
    pairs: Iterable[Pair],
    *,
    before: Mapping[str, Any] | None = None,
    prefix: str = "",
) -> list[Pair]:
    """The pairs in ``after`` that this save leaves without Arabic.

    ``after`` is the record as it will be stored (for a PATCH, the stored row
    with the patch laid over it). ``before`` is the stored row, or ``None``
    for a new record. ``prefix`` is put in front of each returned field name
    so a nested item can be named, e.g. ``"activities[3]."``.
    """
    out: list[Pair] = []
    for en, ar in pairs:
        if pair_needs_arabic(
            en_after=after.get(en),
            ar_after=after.get(ar),
            en_before=before.get(en) if before is not None else None,
            ar_before=before.get(ar) if before is not None else None,
            is_new=before is None,
        ):
            out.append((f"{prefix}{en}", f"{prefix}{ar}"))
    return out


def merged(before: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    """The record a PATCH will leave: the stored row with the patch over it."""
    return {**before, **patch}


def describe_missing(missing: Sequence[Pair]) -> str:
    listed = "; ".join(f"{ar} (Arabic for {en})" for en, ar in missing)
    return (
        "Arabic text is required beside English on new or changed platform content. "
        f"Missing: {listed}."
    )


class ArabicRequiredError(APIError):
    """422 naming every Arabic field this save is missing.

    ``missing_arabic`` in the body lists the Arabic field names, so a form
    can mark each input; ``detail`` says the same in a sentence.
    """

    def __init__(self, missing: Sequence[Pair]) -> None:
        self.missing: tuple[Pair, ...] = tuple(missing)
        super().__init__(
            status_code=422,
            title="Arabic text required",
            detail=describe_missing(self.missing),
            type_=ARABIC_REQUIRED_PROBLEM,
            extras={"missing_arabic": [ar for _en, ar in self.missing]},
        )


def require_arabic(
    after: Mapping[str, Any],
    pairs: Iterable[Pair],
    *,
    before: Mapping[str, Any] | None = None,
    prefix: str = "",
) -> None:
    """Raise :class:`ArabicRequiredError` when :func:`missing_arabic` finds any."""
    missing = missing_arabic(after, pairs, before=before, prefix=prefix)
    if missing:
        raise ArabicRequiredError(missing)
