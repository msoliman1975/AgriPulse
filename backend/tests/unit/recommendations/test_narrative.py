"""The paragraph behind a verdict.

The walk was rendered as a four-column table, and a reader asking "why is this
block green" had to assemble the answer themselves. These tests pin what the
prose says, in both languages, because the composed sentence is the product —
asserting the fragments it is built from would pass while the sentence read
wrongly.

The last two came from running the composer over a REAL production walk
rather than these fixtures, which is where both defects showed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.recommendations.narrative import compose, compose_both

NDVI_STEP = {
    "node_id": "ndvi_floor",
    "matched": True,
    "label_en": "Is canopy greenness above the floor for this tree size?",
    "label_ar": "هل خضرة المجموع الخضري فوق الحد الأدنى لحجم الشجرة؟",
    "values": {"indices.ndvi.mean": 0.61},
    "condition": {
        "tree": {
            "op": "gt",
            "left": {"source": "indices", "index_code": "ndvi", "key": "mean"},
            "right": 0.5,
        }
    },
}
RAIN_STEP = {
    "node_id": "rain_24h",
    "matched": False,
    "label_en": "Is rain forecast within the next 24 hours?",
    "label_ar": "هل يتوقع هطول مطر خلال 24 ساعة؟",
    "values": {"weather.rain_mm_24h": 0},
    "condition": {
        "tree": {"op": "gte", "left": {"source": "weather", "key": "rain_mm_24h"}, "right": 2}
    },
}
LEAF_STEP = {"node_id": "leaf_ok", "matched": None, "label_en": None, "label_ar": None}


def _compose(**over):
    kwargs = {
        "status_code": "good",
        "tree_code": "mango_canopy_health_v1",
        "text": "Canopy greenness is within the seasonal baseline.",
        "node_path": [NDVI_STEP, RAIN_STEP, LEAF_STEP],
        "resolved_values": {},
        "evaluated_at": datetime(2026, 9, 8, 15, 17, tzinfo=UTC),
        "language": "en",
    }
    kwargs.update(over)
    return compose(**kwargs)


# ---- what the paragraph says ---------------------------------------------


def test_it_says_when_it_was_checked() -> None:
    assert _compose().startswith("Checked on 2026-09-08.")


def test_it_counts_the_checks_and_excludes_the_leaf() -> None:
    """The leaf is the answer, not a check. Counting it makes the number one
    higher than the questions a reader can see."""
    assert "The tree checked 2 things, in this order." in _compose()


def test_one_check_is_not_pluralised() -> None:
    assert "The tree checked one thing." in _compose(node_path=[NDVI_STEP, LEAF_STEP])


def test_each_check_keeps_the_authors_question_word_for_word() -> None:
    # The template never rephrases: it cannot invert an authored question into
    # a statement without guessing, so it keeps it and answers it.
    assert "Is canopy greenness above the floor for this tree size? Yes" in _compose()
    assert "Is rain forecast within the next 24 hours? No" in _compose()


def test_a_check_carries_its_reading_and_its_threshold() -> None:
    """Without the threshold a reader cannot tell how close to the edge the
    block sits, which is the whole reason to read this."""
    assert "the reading was NDVI (mean) 0.61, against > 0.5" in _compose()


def test_it_ends_with_the_verdict_and_the_trees_own_sentence() -> None:
    assert _compose().endswith(
        "So mango_canopy_health_v1 reports Good: “Canopy greenness is within the "
        "seasonal baseline.”"
    )


def test_a_verdict_with_no_text_still_concludes() -> None:
    assert _compose(text=None).endswith("So mango_canopy_health_v1 reports Good.")


# ---- the awkward shapes ---------------------------------------------------


def test_a_pruned_walk_says_so_rather_than_showing_nothing() -> None:
    """Retention removes the run; the verdict outlives it. An empty paragraph
    would read as "the tree did nothing"."""
    text = _compose(reasoning_available=False)

    assert "no longer stored" in text
    assert "Is canopy greenness" not in text
    # The answer still stands, and still gets said.
    assert "reports Good" in text


def test_a_walk_with_no_decision_nodes_says_that_too() -> None:
    assert "without testing anything" in _compose(node_path=[LEAF_STEP])


def test_a_float_is_not_printed_at_machine_precision() -> None:
    """0.6100000000000001 out of JSONB reads as a broken instrument."""
    step = {**NDVI_STEP, "values": {"indices.ndvi.mean": 0.6100000000000001}}

    assert "0.61," in _compose(node_path=[step, LEAF_STEP])


def test_a_group_condition_offers_no_single_threshold() -> None:
    """`all_of` has no one number to compare against, and summarising several
    would be a number the reader cannot check."""
    step = {
        **NDVI_STEP,
        "condition": {"tree": {"all_of": [{"op": "gt", "right": 0.5}, {"op": "lt", "right": 0.9}]}},
    }
    text = _compose(node_path=[step, LEAF_STEP])

    assert "the reading was NDVI (mean) 0.61." in text
    assert "against" not in text


def test_a_step_with_neither_reading_nor_test_is_still_answered() -> None:
    step = {"node_id": "stage", "matched": True, "label_en": "Is the block bearing?"}

    assert "Is the block bearing? Yes." in _compose(node_path=[step, LEAF_STEP])


def test_a_question_mark_is_not_doubled() -> None:
    assert _compose().count("this tree size?") == 1
    assert "??" not in _compose()


def test_a_label_without_a_question_mark_gains_one() -> None:
    step = {**NDVI_STEP, "label_en": "Canopy greenness above the floor"}

    assert "Canopy greenness above the floor? Yes" in _compose(node_path=[step, LEAF_STEP])


# ---- Arabic ---------------------------------------------------------------


def test_arabic_uses_the_authors_arabic_question() -> None:
    text = _compose(language="ar")

    assert "هل خضرة المجموع الخضري فوق الحد الأدنى لحجم الشجرة؟ نعم" in text
    assert "هل يتوقع هطول مطر خلال 24 ساعة؟ لا" in text


def test_arabic_names_the_status_in_arabic() -> None:
    assert "جيد" in _compose(language="ar")


def test_arabic_falls_back_to_the_english_label_when_there_is_no_arabic_one() -> None:
    """A tenant-authored tree may carry only English. A blank line would be
    worse than an English question inside an Arabic paragraph."""
    step = {**NDVI_STEP, "label_ar": None}

    assert "Is canopy greenness above the floor" in _compose(
        node_path=[step, LEAF_STEP], language="ar"
    )


def test_both_languages_each_quote_their_own_leaf_text() -> None:
    """A real walk on 2026-09-09 ended an Arabic paragraph with the English
    sentence, because one text was passed for both languages."""
    both = compose_both(
        status_code="issue",
        tree_code="t_cwsi_irrigation_stress",
        text_en="Water stress is above the band for this tree size.",
        text_ar="إجهاد الماء أعلى من النطاق لهذا الحجم.",
        node_path=[NDVI_STEP, LEAF_STEP],
        evaluated_at=datetime(2026, 9, 8, tzinfo=UTC),
    )

    assert "reports Issue" in both["en"]
    assert "Water stress is above the band" in both["en"]
    assert "مشكلة" in both["ar"]
    assert "إجهاد الماء أعلى من النطاق" in both["ar"]
    assert "Water stress" not in both["ar"]


def test_arabic_falls_back_to_the_english_sentence_when_the_leaf_has_no_arabic() -> None:
    both = compose_both(
        status_code="good",
        tree_code="qa_v1",
        text_en="All clear.",
        text_ar=None,
        node_path=[LEAF_STEP],
    )

    assert "All clear." in both["ar"]


# ---- what a real production walk exposed ---------------------------------


def test_a_ref_is_never_printed_raw() -> None:
    """The real walk read "the reading was crop_attribute.tree_size_class.value
    medium", which is the tabular reading this paragraph replaces."""
    step = {
        "node_id": "size",
        "matched": True,
        "label_en": "Are the trees in the medium size class?",
        "values": {
            "crop_attribute.tree_size_class.value": "medium",
            "block.growth_stage": "maturation",
        },
    }
    text = _compose(node_path=[step, LEAF_STEP])

    assert "tree size class medium" in text
    assert "growth stage maturation" in text
    assert "crop_attribute" not in text
    assert ".value" not in text


def test_a_threshold_is_not_reported_as_a_reading() -> None:
    """A step records no condition, so the threshold can only come from the
    tree's resolved parameters. The first version printed both as readings,
    telling a reader the block's moisture was 0.7643 AND 0.4."""
    step = {
        "node_id": "medium_not_cut",
        "matched": True,
        "label_en": "Is soil moisture still at the fully watered level?",
        "values": {"indices.smi.mean": 0.7643, "params.medium_smi_normal_floor": 0.4},
    }
    text = _compose(node_path=[step, LEAF_STEP])

    assert "the reading was SMI (mean) 0.7643, against medium smi normal floor 0.4" in text
