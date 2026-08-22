"""Presentation values handed to the notification templates.

The renderer has no conditionals and no filters, so anything a template
cannot compute has to be decided here. Three of these were wrong before
and shipped that way on every channel, which is why each has its own
test rather than sharing one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.settings import get_settings
from app.modules.notifications.presentation import (
    absolute_url,
    action_type_label,
    format_timestamp,
    preferences_url,
    severity_colours,
    severity_label,
)


class TestSeverityLabel:
    def test_english(self) -> None:
        assert severity_label("critical", "en") == "Critical"
        assert severity_label("warning", "en") == "Warning"
        assert severity_label("info", "en") == "Info"

    def test_arabic_is_arabic(self) -> None:
        # The bug this replaces: the label was English for both locales,
        # so an Arabic reader got "CRITICAL" inside an Arabic sentence.
        assert severity_label("critical", "ar") == "حرِج"
        assert severity_label("warning", "ar") == "تحذير"
        assert severity_label("info", "ar") == "معلومة"

    def test_unknown_locale_falls_back_to_english(self) -> None:
        assert severity_label("critical", "fr") == "Critical"

    def test_unknown_severity_renders_itself_not_blank(self) -> None:
        assert severity_label("catastrophic", "en") == "catastrophic"


class TestSeverityColours:
    @pytest.mark.parametrize("severity", ["info", "warning", "critical"])
    def test_each_severity_has_three_distinct_hex_values(self, severity: str) -> None:
        fg, bg, border = severity_colours(severity)
        for value in (fg, bg, border):
            assert value.startswith("#")
            assert len(value) == 7
        assert fg != bg

    def test_severities_do_not_share_a_text_colour(self) -> None:
        # The rail is the only thing readable at thumbnail size; two
        # severities painting the same colour would erase that.
        texts = {severity_colours(s)[0] for s in ("info", "warning", "critical")}
        assert len(texts) == 3

    def test_unknown_severity_gets_the_neutral_fallback(self) -> None:
        assert severity_colours("nonsense") == ("#0f2a1f", "#f7f6f1", "#e3e0d6")


class TestActionTypeLabel:
    def test_english_and_arabic(self) -> None:
        assert action_type_label("fertilize", "en") == "Fertilize"
        assert action_type_label("fertilize", "ar") == "تسميد"
        assert action_type_label("harvest_window", "en") == "Harvest window"

    def test_every_enum_value_has_both_locales(self) -> None:
        # The CHECK enum from tenant migration 0015. A value missing here
        # would print a raw code in a labelled field.
        enum = (
            "irrigate",
            "fertilize",
            "spray",
            "scout",
            "harvest_window",
            "prune",
            "no_action",
            "other",
        )
        for code in enum:
            for locale in ("en", "ar"):
                assert action_type_label(code, locale) != code

    def test_unknown_code_degrades_to_the_code_not_to_blank(self) -> None:
        assert action_type_label("teleport", "en") == "teleport"


class TestFormatTimestamp:
    def test_english(self) -> None:
        moment = datetime(2026, 8, 20, 14, 32, 11, 482913, tzinfo=UTC)
        assert format_timestamp(moment, "en") == "20 Aug 2026, 14:32 UTC"

    def test_arabic(self) -> None:
        moment = datetime(2026, 8, 20, 14, 32, tzinfo=UTC)
        assert format_timestamp(moment, "ar") == "20 أغسطس 2026، 14:32 بتوقيت UTC"

    def test_converts_to_utc_rather_than_printing_the_stored_offset(self) -> None:
        cairo = datetime(2026, 8, 20, 17, 32, tzinfo=timezone(timedelta(hours=3)))
        assert format_timestamp(cairo, "en") == "20 Aug 2026, 14:32 UTC"

    def test_naive_datetime_is_read_as_utc(self) -> None:
        assert format_timestamp(datetime(2026, 8, 20, 14, 32), "en") == "20 Aug 2026, 14:32 UTC"

    def test_none_renders_empty(self) -> None:
        assert format_timestamp(None, "en") == ""


class TestUrls:
    def test_absolute_url_prefixes_the_configured_origin(self) -> None:
        base = get_settings().app_base_url.rstrip("/")
        assert absolute_url("/action-center/abc?item=1") == f"{base}/action-center/abc?item=1"

    def test_absolute_url_does_not_double_the_slash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = get_settings()
        monkeypatch.setattr(settings, "app_base_url", "https://app.agripulse.cloud/")
        assert absolute_url("/x") == "https://app.agripulse.cloud/x"

    def test_preferences_url_points_at_the_persons_own_screen(self) -> None:
        # Not /settings/notifications. That hub is tenant-wide config and every
        # tab is capability-gated, so the link would 403 most recipients.
        assert preferences_url().endswith("/account/notifications")
