"""Farm timezone resolution.

The 5-day forecast endpoint buckets hourly forecasts into days in the
farm's local timezone — "today" should mean today where the weather
is happening, not where the user is sitting. We don't store a tz on
`farms`; instead we derive it server-side from the farm's centroid
via `timezonefinder`'s bundled lat/lon -> IANA dataset.

Resolution is in-process LRU-cached because `TimezoneFinder` reads its
~50 MB shapefile on first call. One instance per worker, shared across
requests.
"""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from timezonefinder import TimezoneFinder

_DEFAULT_TZ = "UTC"


@lru_cache(maxsize=1)
def _finder() -> TimezoneFinder:
    return TimezoneFinder()


@lru_cache(maxsize=1024)
def tz_name_for_centroid(latitude: float, longitude: float) -> str:
    """Return an IANA tz name (e.g. ``Africa/Cairo``) for the given point.

    Falls back to UTC if the lookup misses (open ocean, edge cases).
    The cache key is the float pair — callers should pass farm-stable
    centroids, not per-request fresh values.
    """
    name = _finder().timezone_at(lng=longitude, lat=latitude)
    return name or _DEFAULT_TZ


def tz_for_centroid(latitude: float, longitude: float) -> ZoneInfo:
    """Same as :func:`tz_name_for_centroid` but returns a ``ZoneInfo``."""
    return ZoneInfo(tz_name_for_centroid(latitude, longitude))
