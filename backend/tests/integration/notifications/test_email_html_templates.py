"""The seeded HTML email bodies, rendered against a real database row.

Deliberately not a fake repository. The last two notification defects
survived because the only tests stubbed the store, so these read the row
migration 0070 actually inserted and render it with the renderer the
subscriber actually calls.

What is pinned:

* version 2 exists for all four (code, locale) pairs, and version 1 is
  still there — an alert that already fired keeps its wording.
* the loader's ``ORDER BY version DESC`` picks 2.
* every ``{{var}}`` the markup asks for is one the context builders
  supply, so nothing renders blank in a customer's inbox.
* escaping runs, so a farm name with markup in it cannot break out.
* no remote asset, because most clients block images by default.
* the body stays well under Gmail's 102 KB clipping threshold.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.templates import render

pytestmark = [pytest.mark.integration]

PLACEHOLDER = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")

PAIRS = [
    ("alert_opened", "en"),
    ("alert_opened", "ar"),
    ("recommendation_opened", "en"),
    ("recommendation_opened", "ar"),
]

# A context with every key the two `_build_render_ctx*` builders produce.
# Values are deliberately hostile: an ampersand and a tag, both of which
# a real farm name or an authored decision-tree sentence can contain.
CTX = {
    "tenant_id": "019eafdc-242c-7320-948e-13490efc67dd",
    "alert_id": "b71e0000-0000-7000-8000-000000000001",
    "recommendation_id": "41a90000-0000-7000-8000-000000000002",
    "block_id": "c1000000-0000-7000-8000-000000000003",
    "block_code": "A-12",
    "farm_id": "8f2c0000-0000-7000-8000-000000000004",
    "farm_name": "Green Farm & Sons",
    "rule_code": "tree:ndvi_drop_v1:leaf_3",
    "rule_name": "NDVI below block baseline",
    "tree_code": "nitrogen_mango_v2",
    "tree_name": "Nitrogen top-dressing",
    "action_type": "fertilize",
    "action_type_label": "Fertilize",
    "severity": "critical",
    "severity_label": "Critical",
    "severity_color": "#b23a38",
    "severity_bg": "#f6e6e5",
    "severity_border": "#e3c2c1",
    "diagnosis": "NDVI fell to 0.31, 27% below the block's five-year mean.",
    "prescription": "Inspect lines 4-7. <script>alert(1)</script>",
    "text": "Apply 18 kg N/ha as urea. <b>Split</b> across two events.",
    "fired_at": "2026-08-20T14:32:11.482913+00:00",
    "fired_at_display": "20 Aug 2026, 14:32 UTC",
    "signal_snapshot_json": "{}",
    "evaluation_snapshot_json": "{}",
    "link_url": "/action-center/8f2c?kind=alert&item=b71e",
    "link_url_abs": "https://app.agripulse.cloud/action-center/8f2c?kind=alert&item=b71e",
    "preferences_url": "https://app.agripulse.cloud/account/notifications",
}


async def _row(session: AsyncSession, code: str, locale: str, version: int) -> dict[str, str]:
    result = (
        await session.execute(
            text(
                "SELECT subject, body, body_html FROM public.notification_templates "
                "WHERE template_code = :c AND locale = :l "
                "AND channel = 'email' AND version = :v"
            ),
            {"c": code, "l": locale, "v": version},
        )
    ).mappings()
    found = result.first()
    assert found is not None, f"no email row for {code}/{locale} v{version}"
    return dict(found)


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "locale"), PAIRS)
async def test_version_2_row_exists(admin_session: AsyncSession, code: str, locale: str) -> None:
    row = await _row(admin_session, code, locale, 2)
    assert row["subject"]
    assert row["body"]
    assert row["body_html"], "version 2 exists to carry body_html — it must not be NULL"


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "locale"), PAIRS)
async def test_version_1_is_left_in_place(
    admin_session: AsyncSession, code: str, locale: str
) -> None:
    # Rollback is a delete of the v2 rows, and an alert already sent keeps
    # the wording it fired with. Both need v1 still on disk.
    row = await _row(admin_session, code, locale, 1)
    assert row["body_html"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "locale"), PAIRS)
async def test_loader_picks_version_2(admin_session: AsyncSession, code: str, locale: str) -> None:
    # Mirrors the subscriber's own query.
    picked = (
        await admin_session.execute(
            text(
                "SELECT version FROM public.notification_templates "
                "WHERE template_code = :c AND locale = :l AND channel = 'email' "
                "ORDER BY version DESC LIMIT 1"
            ),
            {"c": code, "l": locale},
        )
    ).scalar_one()
    assert picked == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "locale"), PAIRS)
async def test_every_variable_the_markup_wants_is_one_the_builders_supply(
    admin_session: AsyncSession, code: str, locale: str
) -> None:
    row = await _row(admin_session, code, locale, 2)
    wanted: set[str] = set()
    for field in ("subject", "body", "body_html"):
        wanted |= set(PLACEHOLDER.findall(row[field] or ""))
    missing = wanted - set(CTX)
    assert not missing, f"{code}/{locale} renders blank for {sorted(missing)}"


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "locale"), PAIRS)
async def test_renders_with_nothing_left_over(
    admin_session: AsyncSession, code: str, locale: str
) -> None:
    row = await _row(admin_session, code, locale, 2)
    for field, escape in (("subject", False), ("body", False), ("body_html", True)):
        out = render(row[field], CTX, escape=escape)
        assert not PLACEHOLDER.findall(out), f"{code}/{locale}.{field} left a placeholder"


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "locale"), PAIRS)
async def test_values_are_escaped_in_the_html_part(
    admin_session: AsyncSession, code: str, locale: str
) -> None:
    row = await _row(admin_session, code, locale, 2)
    out = render(row["body_html"], CTX, escape=True)
    assert "<script>" not in out
    assert "Green Farm &amp; Sons" in out


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "locale"), PAIRS)
async def test_no_remote_asset_and_the_wordmark_is_text(
    admin_session: AsyncSession, code: str, locale: str
) -> None:
    out = render((await _row(admin_session, code, locale, 2))["body_html"], CTX, escape=True)
    assert not re.search(r"<img|src=|url\(", out), "clients block remote images by default"
    assert "AGRIPULSE" in out


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "locale"), PAIRS)
async def test_carries_a_preheader_and_one_absolute_link(
    admin_session: AsyncSession, code: str, locale: str
) -> None:
    row = await _row(admin_session, code, locale, 2)
    html_out = render(row["body_html"], CTX, escape=True)
    assert "mso-hide:all" in html_out, "no preheader — the inbox list shows raw markup"
    # The button and the paste-fallback both carry it.
    assert html_out.count(CTX["link_url_abs"].replace("&", "&amp;")) == 2
    # The text part must carry the absolute one too, never the relative.
    text_out = render(row["body"], CTX)
    assert CTX["link_url_abs"] in text_out
    assert "\n/action-center/" not in text_out


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "locale"), PAIRS)
async def test_arabic_rows_are_rtl_and_english_rows_are_not(
    admin_session: AsyncSession, code: str, locale: str
) -> None:
    out = render((await _row(admin_session, code, locale, 2))["body_html"], CTX, escape=True)
    if locale == "ar":
        assert 'dir="rtl"' in out
        assert "direction:rtl" in out
        assert "Tahoma" in out, "Tahoma is the Arabic face Outlook actually has"
    else:
        assert 'dir="rtl"' not in out


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "locale"), PAIRS)
async def test_body_is_well_under_the_gmail_clipping_threshold(
    admin_session: AsyncSession, code: str, locale: str
) -> None:
    out = render((await _row(admin_session, code, locale, 2))["body_html"], CTX, escape=True)
    assert len(out.encode()) < 40_000, "Gmail clips a message past ~102 KB"
