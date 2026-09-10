"""Why a block reads the way it does, as prose rather than a table.

The walk behind a verdict is already fully structured: every decision node
carries the question its author wrote, in English and Arabic, and the trace
records what each node read and whether it matched. All 166 decision nodes in
the shipped trees carry both labels. The screen was rendering that as a grid
of four columns, and a reader asking "why is this block green" had to
assemble the answer themselves.

This module turns one walk into one paragraph, in both languages.

**It never rephrases the author's words.** A template cannot invert "Is rain
forecast within the next 24 hours?" into "No rain is forecast" — not in
English without guessing, and not in Arabic at all. So the question is kept
exactly as written and the answer is attached to it:

    Is rain forecast within the next 24 hours? No — the reading was
    rain mm 24h 0, against 2.

That is the honest limit of a template. Rewriting those into flowing
statements is what a language model would add later; the numbers would stay
here, where they cannot be paraphrased into something untrue.

**Every check is narrated, in the order it ran.** Mohamed chose that over a
summary on 2026-09-09: the paragraph is what a reader trusts, and a count of
"three other checks passed" asks them to take the rest on faith.

Two of the rules below came from running this over a REAL production walk
rather than a fixture, and are marked where they sit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from app.modules.recommendations.status_codes import STATUS_BY_CODE

# Both languages live here rather than in a locale file because the paragraph
# is assembled from fragments and the joins differ per language: Arabic needs
# its own punctuation, and a fragment that reads well alone can read wrongly
# once joined.
_WORDS: dict[str, dict[str, str]] = {
    "en": {
        "yes": "Yes",
        "no": "No",
        "checked_on": "Checked on {when}.",
        "one_check": "The tree checked one thing.",
        "n_checks": "The tree checked {n} things, in this order.",
        "no_checks": "The tree reached this answer without testing anything.",
        "concludes": "So {tree} reports {status}: “{text}”",
        "concludes_no_text": "So {tree} reports {status}.",
        "read": "the reading was {value}",
        "read_against": "the reading was {value}, against {test}",
        "against_only": "the test was {test}",
        "pruned": (
            "The detailed checks behind this answer are no longer stored — "
            "evaluation runs are kept for a limited time. The answer itself "
            "still stands."
        ),
        "sep": " ",
    },
    "ar": {
        "yes": "نعم",
        "no": "لا",
        "checked_on": "تم الفحص في {when}.",
        "one_check": "فحصت الشجرة أمرًا واحدًا.",
        "n_checks": "فحصت الشجرة {n} أمور، بهذا الترتيب.",
        "no_checks": "وصلت الشجرة إلى هذه النتيجة دون أي فحص.",
        "concludes": "لذلك تُبلغ {tree} عن {status}: «{text}»",
        "concludes_no_text": "لذلك تُبلغ {tree} عن {status}.",
        "read": "القراءة {value}",
        "read_against": "القراءة {value}، مقابل {test}",
        "against_only": "الاختبار {test}",
        "pruned": (
            "تفاصيل الفحوصات خلف هذه النتيجة لم تعد محفوظة — تُحفظ جولات "
            "التقييم لمدة محدودة. النتيجة نفسها ما زالت قائمة."
        ),
        "sep": " ",
    },
}

# How an operator reads inside a sentence. Symbols beat words: "0.61, against
# > 0.50" reads the same way in both languages, and a translated "greater
# than" would have to agree with the gender of what follows in Arabic.
_OPERATORS: dict[str, str] = {
    "gt": ">",
    "gte": "≥",
    "ge": "≥",
    "lt": "<",
    "lte": "≤",
    "le": "≤",
    "eq": "=",
    "ne": "≠",
    "in": "∈",
    "not_in": "∉",
    "between": "between",
}

# Index codes read as initialisms, not as words. "smi mean" in a sentence
# reads like a typo; "SMI (mean)" reads like a measurement.
_INITIALISMS: frozenset[str] = frozenset(
    {
        "ndvi",
        "ndre",
        "ndmi",
        "ndwi",
        "evi",
        "savi",
        "msavi",
        "msi",
        "smi",
        "cwsi",
        "bsi",
        "gndvi",
        "lst",
        "ece",
        "ec",
        "ph",
        "et0",
    }
)

# The leading segment of a ref says where the number came from. It is
# scaffolding for the evaluator, not something to read aloud.
_SOURCE_PREFIXES: frozenset[str] = frozenset(
    {
        "indices",
        "index",
        "signals",
        "signal",
        "weather",
        "weather_index",
        "weather_risk",
        "block",
        "crop_attribute",
        "crop_attributes",
        "grid",
        "water_balance",
        "params",
    }
)


def _fmt_number(value: Any) -> str:
    """A number as a reader would write it, not as Python prints it.

    `0.6100000000000001` is what a float sometimes carries out of JSONB, and
    a reading that precise on screen reads as a broken instrument.
    """
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def _fmt_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, list | tuple):
        return ", ".join(_fmt_number(v) for v in value)
    return _fmt_number(value)


def _humanise_ref(ref: str) -> str:
    """`indices.smi.mean` as `SMI (mean)`, `block.growth_stage` as `growth stage`.

    From a real production walk on 2026-09-09, which read "the reading was
    crop_attribute.tree_size_class.value medium". The dotted ref is how the
    evaluator addresses a number; printed into a sentence it is exactly the
    tabular reading this paragraph exists to replace.
    """
    parts = [p for p in ref.split(".") if p]
    if parts and parts[0] in _SOURCE_PREFIXES:
        parts = parts[1:]
    # A trailing `.value` is the evaluator reaching into a wrapper.
    if len(parts) > 1 and parts[-1] == "value":
        parts = parts[:-1]
    if not parts:
        return ref
    head = parts[0]
    name = head.upper() if head.lower() in _INITIALISMS else head.replace("_", " ")
    if len(parts) == 1:
        return name
    qualifier = " ".join(p.replace("_", " ") for p in parts[1:])
    return f"{name} ({qualifier})"


def _ref_text(operand: Any) -> str | None:
    """A condition operand as the dotted ref the values dict is keyed by."""
    if not isinstance(operand, Mapping):
        return None
    source = operand.get("source")
    if not source:
        return None
    parts = [str(source)]
    for key in ("index_code", "code", "name", "key", "metric", "field"):
        if operand.get(key):
            parts.append(str(operand[key]))
    return ".".join(parts)


def _test_text(condition: Any) -> str | None:  # noqa: PLR0911
    """What the node compared against: `> 0.50`, `between 3 and 7`.

    One return per shape a condition can take, which is why PLR0911 is
    silenced: each is a different reason there is nothing to compare.

    None when the node's condition is a group (`all_of` / `any_of`): a group
    has no single threshold, and summarising several would be a number the
    reader cannot check.

    Also None for every walk recorded so far — `_serialize_path` keeps five
    fields per step and the condition is not one of them. The parameter
    fallback in `_split_values` is what carries the threshold today.
    """
    if not isinstance(condition, Mapping):
        return None
    tree = condition.get("tree") if "tree" in condition else condition
    if not isinstance(tree, Mapping):
        return None
    op = tree.get("op")
    if not isinstance(op, str):
        return None
    symbol = _OPERATORS.get(op, op)
    if op == "between":
        low, high = tree.get("low"), tree.get("high")
        if low is None or high is None:
            return None
        return f"{symbol} {_fmt_value(low)} and {_fmt_value(high)}"
    right = tree.get("right")
    if right is None:
        return None
    ref = _ref_text(right)
    return f"{symbol} {_humanise_ref(ref)}" if ref else f"{symbol} {_fmt_value(right)}"


def _split_values(
    step: Mapping[str, Any], values: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    """What the node read, and what it was compared against.

    A step records no condition, so the threshold cannot be read from the walk
    directly. What IS there is the tree's resolved parameters, under
    `params.*`, and those are the thresholds: a node testing soil moisture
    against `params.medium_smi_normal_floor` stored both numbers side by side.
    Printing them as two readings — which the first version did, and a real
    production walk showed — told a reader the block's moisture was 0.7643
    AND 0.4.
    """
    source = step.get("values")
    if not isinstance(source, Mapping) or not source:
        source = values if isinstance(values, Mapping) else {}
    readings: list[str] = []
    limits: list[str] = []
    for ref, value in source.items():
        text = f"{_humanise_ref(str(ref))} {_fmt_value(value)}"
        (limits if str(ref).startswith("params.") else readings).append(text)
    return readings[:3], limits[:3]


def _step_sentence(
    step: Mapping[str, Any],
    values: Mapping[str, Any],
    words: Mapping[str, str],
    *,
    arabic: bool,
) -> str:
    label = step.get("label_ar") if arabic else step.get("label_en")
    if not label:
        # A tenant-authored tree may carry only English. An English question
        # inside an Arabic paragraph is better than a blank line.
        label = step.get("label_en") or step.get("node_id") or ""
    question = str(label).strip()
    if question and not question.endswith(("?", "؟")):
        question = f"{question}?"

    answer = words["yes"] if step.get("matched") else words["no"]

    readings, limits = _split_values(step, values)
    test = _test_text(step.get("condition")) or (", ".join(limits) if limits else None)
    reading = ", ".join(readings) if readings else None
    if reading and test:
        detail = words["read_against"].format(value=reading, test=test)
    elif reading:
        detail = words["read"].format(value=reading)
    elif test:
        detail = words["against_only"].format(test=test)
    else:
        return f"{question} {answer}."
    return f"{question} {answer} — {detail}."


def _when(evaluated_at: datetime | str | None) -> str | None:
    if evaluated_at is None:
        return None
    if isinstance(evaluated_at, str):
        return evaluated_at[:10]
    # The date only. The hour is in the card's own header, and repeating it
    # inside the sentence made the paragraph read like a log line.
    return evaluated_at.strftime("%Y-%m-%d")


def compose(
    *,
    status_code: str,
    tree_code: str,
    tree_name: str | None = None,
    text: str | None,
    node_path: Sequence[Mapping[str, Any]],
    resolved_values: Mapping[str, Any] | None = None,
    evaluated_at: datetime | str | None = None,
    reasoning_available: bool = True,
    language: str = "en",
) -> str:
    """One verdict's walk as a paragraph in ``language``.

    The answer comes last, after the checks that produced it, because that is
    the order the tree ran in and the order a reader can follow. The status
    and the leaf's own sentence are repeated there even though the card shows
    them above: this paragraph is quoted into reports and emails, where
    nothing else is on the page.

    ``tree_name`` is the tree's own name, and is what the last sentence uses.
    Without it the paragraph ended "So t_mango_cwsi reports Alert", which put
    an authoring handle in the one sentence a grower reads. The code stays
    the fallback, because a verdict outlives its catalog row.
    """
    words = _WORDS.get(language, _WORDS["en"])
    tree_label = (tree_name or "").strip() or tree_code
    arabic = language == "ar"
    status = STATUS_BY_CODE.get(status_code)
    status_label = (
        status_code if status is None else (status.label_ar if arabic else status.label_en)
    )

    parts: list[str] = []
    when = _when(evaluated_at)
    if when:
        parts.append(words["checked_on"].format(when=when))

    if not reasoning_available:
        parts.append(words["pruned"])
    else:
        # A leaf carries `matched=None`: it is the answer, not a check.
        # Counting it makes the number one higher than the questions a reader
        # can see.
        steps = [s for s in node_path if isinstance(s, Mapping) and s.get("matched") is not None]
        if not steps:
            parts.append(words["no_checks"])
        else:
            parts.append(
                words["one_check"] if len(steps) == 1 else words["n_checks"].format(n=len(steps))
            )
            values = resolved_values or {}
            for step in steps:
                parts.append(_step_sentence(step, values, words, arabic=arabic))

    if text:
        parts.append(
            words["concludes"].format(tree=tree_label, status=status_label, text=text.strip())
        )
    else:
        parts.append(words["concludes_no_text"].format(tree=tree_label, status=status_label))
    return words["sep"].join(parts)


def compose_both(
    *,
    text_en: str | None = None,
    text_ar: str | None = None,
    tree_name_en: str | None = None,
    tree_name_ar: str | None = None,
    **kwargs: Any,
) -> dict[str, str]:
    """The paragraph in both languages, which is what every caller wants.

    ``text_en`` and ``text_ar`` are separate because the leaf's own sentence
    is the author's, not a translation: passing one text for both languages
    put an English conclusion at the end of an Arabic paragraph, which is
    what a real production walk showed on 2026-09-09.

    The tree's name is chosen per language the same way, and for the same
    reason: the Arabic name is the author's, not a translation of the English
    one. An Arabic reader with no Arabic name falls back to the English name
    before falling back to the code.
    """
    return {
        "en": compose(**kwargs, text=text_en, tree_name=tree_name_en, language="en"),
        "ar": compose(
            **kwargs,
            text=text_ar or text_en,
            tree_name=tree_name_ar or tree_name_en,
            language="ar",
        ),
    }
