"""Unit tests for the shared health classifier.

The same rule is duplicated on the FE at
frontend/src/modules/labs/map/health.ts — if the thresholds change
in either site, update the other in lockstep.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.shared.health import bucket_alert_severity, classify_health


class TestAlertSeverityWins:
    """Alert severity outranks NDVI value (conservative rule)."""

    def test_critical_alert_with_great_ndvi_is_critical(self) -> None:
        # NDVI 0.85 = healthy looking, but a critical alert wins.
        assert classify_health(worst_alert_severity="critical", ndvi_current=0.85) == "critical"

    def test_watch_alert_with_great_ndvi_is_watch(self) -> None:
        assert classify_health(worst_alert_severity="watch", ndvi_current=0.85) == "watch"

    def test_no_alert_passes_through_to_ndvi(self) -> None:
        assert classify_health(worst_alert_severity=None, ndvi_current=0.85) == "healthy"


class TestNdviThresholds:
    """When no alert is active, NDVI value picks the bucket."""

    @pytest.mark.parametrize(
        ("ndvi", "expected"),
        [
            (None, "unknown"),
            (0.0, "critical"),
            (0.39, "critical"),
            (0.40, "watch"),
            (0.54, "watch"),
            (0.55, "healthy"),
            (1.0, "healthy"),
        ],
    )
    def test_buckets(self, ndvi: float | None, expected: str) -> None:
        assert classify_health(worst_alert_severity=None, ndvi_current=ndvi) == expected

    def test_accepts_decimal(self) -> None:
        assert classify_health(worst_alert_severity=None, ndvi_current=Decimal("0.6")) == "healthy"


class TestBucketAlertSeverity:
    @pytest.mark.parametrize(
        ("severity", "expected"),
        [
            ("critical", "critical"),
            ("warning", "watch"),
            ("info", None),  # info doesn't degrade health
            ("unknown_value", None),  # defensive against new severities
        ],
    )
    def test_mapping(self, severity: str, expected: str | None) -> None:
        assert bucket_alert_severity(severity) == expected
