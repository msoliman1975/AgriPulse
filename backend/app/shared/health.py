"""The health-bucket classifier. One rule, one place.

Every caller that needs a block's health class calls this. There is no
second copy. There were three before: this module, a private
``_classify_health`` in ``farms/blocks_summary_router.py``, and
``classifyHealth`` in ``frontend/src/modules/labs/map/health.ts``. The
frontend one is gone; the class reaches the browser as the ``health``
field on ``GET /farms/{id}/blocks/summary``.

Callers today:
  * ``farms/blocks_summary_router`` — map polygons + the block dock
  * ``insights/service.get_farm_health_summary`` — the scorecard

Known caller drift, NOT a difference in this rule: the two callers do
not count the same alerts. The summary router counts ``status='open'``
only; the insights rollup counts ``open + acknowledged + snoozed``. So
one block can read Critical on the scorecard and Healthy on the map.
Normalising which statuses count is a caller-side change and belongs
with the definition work, not here.

Rule (conservative — any critical alert wins):

  * worstAlertSeverity == 'critical' → critical
  * worstAlertSeverity == 'watch'    → watch
  * ndvi_current is None             → unknown
  * ndvi_current < 0.40              → critical
  * ndvi_current < 0.55              → watch
  * otherwise                        → healthy

Both thresholds and the rule shape match the FE; if you change one,
update both in lockstep so the Labs map and the Insights scorecard
agree.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

Health = Literal["healthy", "watch", "critical", "unknown"]
AlertSeverityBucket = Literal["critical", "watch", None]


_NDVI_CRITICAL_BELOW = Decimal("0.40")
_NDVI_WATCH_BELOW = Decimal("0.55")


def classify_health(
    *,
    worst_alert_severity: AlertSeverityBucket,
    ndvi_current: Decimal | float | None,
) -> Health:
    """Return the rolled-up health bucket for one block.

    `worst_alert_severity` is the highest severity of OPEN alerts on
    the block, mapped to the FE's two visible buckets (`critical` /
    `watch`); `info`-level alerts don't degrade health.

    `ndvi_current` is the most recent NDVI mean. Pass other indices
    only if you also adjust the thresholds — the buckets here are
    NDVI-shaped (0..1 healthy range, 0.4/0.55 break points).
    """
    if worst_alert_severity == "critical":
        return "critical"
    if worst_alert_severity == "watch":
        return "watch"
    if ndvi_current is None:
        return "unknown"
    value = Decimal(str(ndvi_current))
    if value < _NDVI_CRITICAL_BELOW:
        return "critical"
    if value < _NDVI_WATCH_BELOW:
        return "watch"
    return "healthy"


def bucket_alert_severity(severity: str) -> AlertSeverityBucket:
    """Map an alerts.severity column value to the bucket the
    classifier expects. `info` (and anything else) → None so it
    doesn't degrade the block's health."""
    if severity == "critical":
        return "critical"
    if severity == "warning":
        return "watch"
    return None
