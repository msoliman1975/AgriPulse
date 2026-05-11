"""WeatherProvider Protocol — the contract every weather adapter satisfies.

The orchestrator (`weather/tasks.py`) owns the database state
transitions, idempotency, and scheduling. Providers are stateless
HTTP wrappers; one fetch returns *both* observations (past hourly
data the model has settled on) and forecasts (future hourly).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class HourlyObservation:
    """One hourly past reading (treated as "observed" for our schema).

    All numeric fields are nullable because Open-Meteo can return null
    for any individual variable on an individual hour (e.g. solar
    radiation overnight, sensor outage upstream).
    """

    time: datetime
    air_temp_c: Decimal | None = None
    humidity_pct: Decimal | None = None
    precipitation_mm: Decimal | None = None
    wind_speed_m_s: Decimal | None = None
    wind_direction_deg: Decimal | None = None
    pressure_hpa: Decimal | None = None
    solar_radiation_w_m2: Decimal | None = None
    cloud_cover_pct: Decimal | None = None
    et0_mm: Decimal | None = None


@dataclass(frozen=True, slots=True)
class HourlyForecast:
    """One hourly future reading."""

    time: datetime
    air_temp_c: Decimal | None = None
    humidity_pct: Decimal | None = None
    precipitation_mm: Decimal | None = None
    precipitation_probability_pct: Decimal | None = None
    wind_speed_m_s: Decimal | None = None
    solar_radiation_w_m2: Decimal | None = None
    et0_mm: Decimal | None = None


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Full result of one weather pull for a (latitude, longitude) point."""

    forecast_issued_at: datetime
    observations: tuple[HourlyObservation, ...] = field(default_factory=tuple)
    forecasts: tuple[HourlyForecast, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of a liveness probe — PR-IH5.

    Status:
      - 'ok'      : provider responded normally
      - 'error'   : non-2xx HTTP or other adapter-recognized error
      - 'timeout' : timed out before responding
    """

    status: str
    latency_ms: int | None = None
    error_message: str | None = None


class WeatherProvider(Protocol):
    """The contract every weather adapter satisfies."""

    @property
    def code(self) -> str:
        """Provider code matching `public.weather_providers.code`."""
        ...

    async def probe(self) -> ProbeResult:
        """Cheap liveness check. Should make one bounded-cost request and
        return within a few seconds. Implementations swallow exceptions
        and report them via ProbeResult so the orchestrator never raises
        from a probe call."""
        ...

    async def fetch(
        self,
        *,
        latitude: float,
        longitude: float,
        past_hours: int,
        forecast_hours: int,
    ) -> FetchResult:
        """Fetch a single (lat, lon) point's recent observations + forecast.

        ``past_hours`` and ``forecast_hours`` are hour counts. The
        provider should return at most this many entries in each list,
        anchored on the current UTC hour. The orchestrator sets
        ``forecast_issued_at`` from the response — we don't trust the
        wall clock for it.
        """
        ...

    async def aclose(self) -> None:
        """Close any pooled HTTP client. Called once per task."""
        ...
