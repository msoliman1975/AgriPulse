"""D26: a platform beta tree is saved with Arabic beside every English text.

The designer saves a tree as one document, so "is this text new?" is decided
by comparing the document against the version before it, piece by piece:

  * the tree's own name, description and readiness note;
  * each node's label, matched by node id;
  * each combination rule's card text, matched by its ``code`` when it has
    one and by its finding set otherwise;
  * each parameter's description, matched by parameter name.

A piece that is new, or whose English changed, or whose Arabic this save
clears, must carry Arabic. A piece the author did not touch is left alone,
so a seeded tree that never had Arabic labels still resaves.

The problems come back as :class:`CompileError` rows, the same shape the
compiler returns, so the designer lists them in the publish checks panel
beside the node they name. The check is deliberately not part of
``check_folding_tree``: the compiler judges a definition on its own, and this
rule needs the previous version to judge it against.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.recommendations.folding_compiler import CompileError
from app.shared.arabic_required import pair_needs_arabic

ARABIC_RULE = "arabic-missing"

_TREE_PAIRS: tuple[tuple[str, str, str, str], ...] = (
    # (en key, ar key, what it is in English, what it is in Arabic)
    ("name_en", "name_ar", "The tree name", "اسم الشجرة"),
    ("description_en", "description_ar", "The tree description", "وصف الشجرة"),
    ("readiness_note_en", "readiness_note_ar", "The readiness note", "ملاحظة الجاهزية"),
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _needs(
    after: Mapping[str, Any],
    before: Mapping[str, Any] | None,
    en: str,
    ar: str,
) -> bool:
    return pair_needs_arabic(
        en_after=after.get(en),
        ar_after=after.get(ar),
        en_before=before.get(en) if before is not None else None,
        ar_before=before.get(ar) if before is not None else None,
        is_new=before is None,
    )


def _combination_keys(rule: Mapping[str, Any]) -> list[tuple[str, ...]]:
    """The keys a combination rule is matched by, most specific first.

    Its ``code`` when it has one, then its finding set. Both, because the
    designer's rule form rewrites a rule without its ``code``: matching on the
    code alone would call that edited rule new.
    """
    keys: list[tuple[str, ...]] = []
    code = rule.get("code")
    if isinstance(code, str) and code.strip():
        keys.append(("code", code.strip()))
    codes = rule.get("codes")
    if isinstance(codes, list):
        keys.append(("codes", *sorted(str(c) for c in codes)))
    return keys


def _keyed_errors(
    after_items: Any,
    before_items: Mapping[str, Any] | None,
    en: str,
    ar: str,
) -> list[tuple[str, Mapping[str, Any]]]:
    """The (key, item) pairs of a keyed mapping whose ``en`` text needs Arabic.

    ``before_items`` is the previous version's mapping, or ``None`` when the
    whole tree is new (every item is then new).
    """
    out: list[tuple[str, Mapping[str, Any]]] = []
    for key, item in sorted(_mapping(after_items).items()):
        if not isinstance(item, Mapping):
            continue
        before = before_items.get(key) if before_items is not None else None
        # Absent from the previous version means new in this one.
        before = before if isinstance(before, Mapping) else None
        if _needs(item, before, en, ar):
            out.append((str(key), item))
    return out


def _combination_errors(
    definition: Mapping[str, Any], previous: Mapping[str, Any] | None
) -> list[CompileError]:
    before_rules: dict[tuple[str, ...], Mapping[str, Any]] = {}
    for rule in (previous or {}).get("combinations") or []:
        if isinstance(rule, Mapping):
            for key in _combination_keys(rule):
                before_rules.setdefault(key, rule)
    errors: list[CompileError] = []
    for index, rule in enumerate(definition.get("combinations") or [], start=1):
        if not isinstance(rule, Mapping):
            continue
        before = next((before_rules[k] for k in _combination_keys(rule) if k in before_rules), None)
        if _needs(rule, before, "text_en", "text_ar"):
            errors.append(
                CompileError(
                    rule=ARABIC_RULE,
                    message_en=(
                        f"Combination rule number {index} has English card text but no "
                        "Arabic text."
                    ),
                    message_ar=f"قاعدة الدمج رقم {index} لها نص إنجليزي دون نص عربي.",
                )
            )
    return errors


def check_tree_arabic(
    definition: Mapping[str, Any], previous: Mapping[str, Any] | None
) -> list[CompileError]:
    """Every English text in ``definition`` this save leaves without Arabic.

    ``previous`` is the version this save follows (the latest one, draft or
    published), or ``None`` when the tree is being created.
    """
    errors: list[CompileError] = [
        CompileError(
            rule=ARABIC_RULE,
            message_en=f"{what_en} has English but no Arabic: fill '{ar}'.",
            message_ar=f"{what_ar} بالإنجليزية دون العربية: املأ '{ar}'.",
        )
        for en, ar, what_en, what_ar in _TREE_PAIRS
        if _needs(definition, previous, en, ar)
    ]

    before_nodes = _mapping(previous.get("nodes")) if previous is not None else None
    errors += [
        CompileError(
            rule=ARABIC_RULE,
            message_en=f"Node {nid!r} has an English label but no Arabic label.",
            message_ar=f"العقدة {nid!r} لها تسمية إنجليزية دون تسمية عربية.",
            node_ids=(nid,),
        )
        for nid, _node in _keyed_errors(
            definition.get("nodes"), before_nodes, "label_en", "label_ar"
        )
    ]

    errors += _combination_errors(definition, previous)

    before_params = _mapping(previous.get("parameters")) if previous is not None else None
    errors += [
        CompileError(
            rule=ARABIC_RULE,
            message_en=f"Parameter {name!r} has an English description but no 'description_ar'.",
            message_ar=f"المعامل {name!r} له وصف إنجليزي دون 'description_ar'.",
        )
        for name, _decl in _keyed_errors(
            definition.get("parameters"), before_params, "description", "description_ar"
        )
    ]
    return errors
