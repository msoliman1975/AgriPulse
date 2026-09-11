"""The consolidated message's render context and its optional sections.

Two things are easy to get wrong here and neither shows up in a type
check: a section whose body is empty leaving its heading behind, and
pre-built markup being escaped into visible tags.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.modules.notifications.subscribers import (
    _block_count_label,
    _build_digest_ctx,
    _finding_blocks,
    _format_block_list,
)
from app.modules.notifications.templates import SafeMarkup, render

TENANT = UUID("01a041ef-e184-723b-b1cb-9d6e656fe00d")
FARM = UUID("01a0443c-dfe2-7369-997b-b75c27cca0e2")
ALERT = UUID("01a08c72-f41f-7fd7-bd6a-253cdc5e8aa8")
WHEN = datetime(2026, 9, 10, 17, 52, tzinfo=UTC)

TREE = {
    "name_en": "My new tree",
    "name_ar": "شجرتي الجديدة",
    "description_en": "Flags blocks whose canopy signal has gone missing.",
    "description_ar": "يرصد القطع التي اختفت إشارة غطائها.",
}
FARM_ROW = {"id": FARM, "name": "Mango Republic", "name_ar": "جمهورية المانجو"}


def _row(**over: object) -> dict:
    row = {
        "farm_id": FARM,
        "group_key": "mango_overmature_risk:leaf_alert_1:scout:warning",
        "tree_code": "mango_overmature_risk",
        "severity": "warning",
        "rule_code": "tree:mango_overmature_risk:leaf_alert_1",
        "action_type": "scout",
        "diagnosis_en": "No Crops here",
        "diagnosis_ar": "لا توجد محاصيل هنا",
        "signal_snapshot": {"indices.ndvi.mean": None},
        "anchor_alert_id": ALERT,
        "first_created_at": WHEN,
        "alert_count": 23,
        "block_codes": [f"{n:03d}" for n in range(1, 24)],
    }
    row.update(over)
    return row


# --- the count, which is the point of the message ----------------------


def test_block_count_label_singular_and_plural() -> None:
    assert _block_count_label(1, "en") == "1 block"
    assert _block_count_label(23, "en") == "23 blocks"


def test_arabic_block_count_takes_its_own_forms() -> None:
    assert _block_count_label(1, "ar") == "قطعة واحدة"
    assert _block_count_label(2, "ar") == "قطعتان"
    assert _block_count_label(5, "ar") == "5 قطع"
    assert _block_count_label(23, "ar") == "23 قطعة"


def test_truncated_list_states_how_many_were_cut() -> None:
    """Never a bare ellipsis: the reader has to be able to tell three
    blocks from thirty, which is the one number this message carries."""
    codes = [f"{n:03d}" for n in range(1, 11)]
    assert _format_block_list(codes, 3, "en") == "001, 002, 003 and 7 more"


def test_short_list_is_not_truncated() -> None:
    assert _format_block_list(["011", "012"], 3, "en") == "011, 012"


def test_block_list_is_sorted_so_two_runs_read_the_same() -> None:
    assert _format_block_list(["044", "011", "029"], 9, "en") == "011, 029, 044"


# --- optional sections -------------------------------------------------


def test_absent_description_leaves_no_heading() -> None:
    blocks = _finding_blocks(description="", snapshot={"indices.ndvi.mean": 0.2}, locale="en")
    assert "WHY THIS TREE RAN" not in blocks["extra_blocks_text"]
    assert "Why this tree ran" not in blocks["extra_blocks_html"]
    # The section that DOES have a body is still there.
    assert "WHAT WE MEASURED" in blocks["extra_blocks_text"]


def test_absent_evidence_leaves_no_heading() -> None:
    blocks = _finding_blocks(description="Something.", snapshot={}, locale="en")
    assert "WHAT WE MEASURED" not in blocks["extra_blocks_text"]
    assert "WHY THIS TREE RAN" in blocks["extra_blocks_text"]


def test_both_absent_yields_empty_strings_not_whitespace() -> None:
    """An empty block must be "" exactly. A block that is "\\n" puts a
    blank line in the body of every message that has nothing to add."""
    blocks = _finding_blocks(description=None, snapshot=None, locale="en")
    assert blocks["extra_blocks_text"] == ""
    assert blocks["extra_blocks_html"] == ""
    assert blocks["action_block_text"] == ""
    assert blocks["action_block_html"] == ""


def test_present_block_ends_with_a_blank_line() -> None:
    """The spacing contract the templates rely on. A template places these
    back to back with no newlines of its own."""
    blocks = _finding_blocks(description="Something.", snapshot=None, locale="en")
    assert blocks["extra_blocks_text"].endswith("\n\n")


def test_tree_alert_gets_no_what_to_do_heading() -> None:
    """A tree leaf writes a diagnosis and no prescription. Version 2 of the
    template printed "WHAT TO DO" above blank space on every one of them."""
    blocks = _finding_blocks(description=None, snapshot=None, locale="en", prescription=None)
    assert blocks["action_block_text"] == ""


def test_prescription_when_present_becomes_the_callout() -> None:
    blocks = _finding_blocks(
        description=None, snapshot=None, locale="en", prescription="Irrigate within 48 hours."
    )
    assert "WHAT TO DO" in blocks["action_block_text"]
    assert "Irrigate within 48 hours." in blocks["action_block_html"]


# --- escaping ----------------------------------------------------------


def test_prebuilt_markup_survives_html_escaping() -> None:
    """`escape=True` protects values that land inside markup. The evidence
    table IS markup, so it is exempt — and the exemption is a type, not a
    flag, so nothing that came from a database column can claim it by
    accident."""
    blocks = _finding_blocks(description=None, snapshot={"indices.ndvi.mean": 0.2}, locale="en")
    out = render("{{evidence}}", {"evidence": blocks["extra_blocks_html"]}, escape=True)
    assert "<table" in out
    assert "&lt;table" not in out


def test_ordinary_values_are_still_escaped() -> None:
    out = render("{{name}}", {"name": "Ben & Sons <Farm>"}, escape=True)
    assert out == "Ben &amp; Sons &lt;Farm&gt;"


def test_evidence_values_are_escaped_inside_the_table() -> None:
    blocks = _finding_blocks(
        description=None, snapshot={"block.growth_stage": "<b>flowering</b>"}, locale="en"
    )
    assert "&lt;b&gt;flowering&lt;/b&gt;" in blocks["extra_blocks_html"]
    assert "<b>flowering</b>" not in blocks["extra_blocks_html"]


def test_safe_markup_is_a_str_so_nothing_downstream_has_to_know() -> None:
    assert isinstance(SafeMarkup("<i>x</i>"), str)


# --- the whole context -------------------------------------------------


def test_context_carries_what_the_reader_was_missing() -> None:
    ctx = _build_digest_ctx(row=_row(), tree=TREE, farm=FARM_ROW, locale="en", tenant_id=TENANT)
    assert ctx["tree_name"] == "My new tree"
    assert ctx["tree_description"] == TREE["description_en"]
    assert ctx["block_count"] == "23"
    assert ctx["block_count_label"] == "23 blocks"
    assert ctx["verdict"] == "No Crops here"
    assert ctx["evidence"] == "NDVI mean: no data"
    assert ctx["severity_label"] == "Warning"


def test_link_goes_to_the_queue_not_to_one_row() -> None:
    """`?item=` opens exactly one alert, which is the opposite of what the
    reader of a 23-block message needs."""
    ctx = _build_digest_ctx(row=_row(), tree=TREE, farm=FARM_ROW, locale="en", tenant_id=TENANT)
    assert ctx["link_url"] == f"/action-center/{FARM}?kind=alert"
    assert "item=" not in ctx["link_url"]


def test_arabic_context_uses_arabic_everywhere() -> None:
    ctx = _build_digest_ctx(row=_row(), tree=TREE, farm=FARM_ROW, locale="ar", tenant_id=TENANT)
    assert ctx["tree_name"] == TREE["name_ar"]
    assert ctx["farm_name"] == FARM_ROW["name_ar"]
    assert ctx["tree_description"] == TREE["description_ar"]
    assert ctx["severity_label"] == "تحذير"
    assert ctx["verdict"] == "لا توجد محاصيل هنا"


def test_missing_tree_falls_back_to_its_code_not_to_blank() -> None:
    ctx = _build_digest_ctx(row=_row(), tree=None, farm=FARM_ROW, locale="en", tenant_id=TENANT)
    assert ctx["tree_name"] == "mango_overmature_risk"
    assert ctx["tree_description"] == ""


def test_alert_family_variable_names_are_also_published() -> None:
    """The single-alert templates say `rule_name`; the digest says
    `tree_name`. Both resolve, so one family can be read against the
    other without a translation step."""
    ctx = _build_digest_ctx(row=_row(), tree=TREE, farm=FARM_ROW, locale="en", tenant_id=TENANT)
    assert ctx["rule_name"] == ctx["tree_name"]
    assert ctx["rule_description"] == ctx["tree_description"]
