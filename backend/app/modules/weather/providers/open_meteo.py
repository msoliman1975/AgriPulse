"""Open-Meteo adapter — implements `WeatherProvider`.

Open-Meteo's free `/v1/forecast` endpoint serves both recent past and
future hourly variables in one call, so a single HTTP roundtrip gives
us everything we need to populate `weather_observations` (past hours)
and `weather_forecasts` (future hours). No auth required for the free
tier.

Why not split observations vs forecast across two endpoints: agronomy
queries care about a continuous timeline. The endpoint is rate-limited
per IP, not per call cost, so collapsing to one fetch is also cheaper.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.weather.providers.protocol import (
    FetchResult,
    HourlyForecast,
    HourlyObservation,
    ProbeResult,
    WeatherProvider,
)

# Probe timeout — kept tight because the probe runs on Beat cadence
# and a slow provider should be visible as a timeout, not a stuck task.
_PROBE_TIMEOUT_SECONDS = 5.0

# Variables we ask Open-Meteo for. Order is documentation-only; the
# response is keyed by name. We map directly onto our hypertable
# column set (data_model § 8.2 / § 8.3).
_HOURLY_VARS: tuple[str, ...] = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "precipitation_probability",
    "wind_speed_10m",
    "wind_direction_10m",
    "pressure_msl",
    "shortwave_radiation",
    "cloud_cover",
    "et0_fao_evapotranspiration",
)

# Max retries for transient 5xx + network errors. Tenacity-style without
# the dep, matching `imagery/providers/sentinel_hub.py`.
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 1.5


class OpenMeteoProvider:
    """`WeatherProvider` implementation backed by Open-Meteo's free API."""

    def __init__(
        self,
        *,
        forecast_url: str | None = None,
        archive_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._forecast_url = forecast_url or settings.open_meteo_forecast_url
        self._archive_url = archive_url or settings.open_meteo_archive_url
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        self._owns_http = http_client is None
        self._log = get_logger(__name__)

    @property
    def code(self) -> str:
        return "open_meteo"

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def probe(self) -> ProbeResult:
        """Tiny `/v1/forecast` call against (0,0) — one hour, one var.

        Open-Meteo's free tier doesn't meter this call cost, so the
        probe cadence is bounded only by the Beat schedule, not quota.
        """
        params: dict[str, Any] = {
            "latitude": 0,
            "longitude": 0,
            "hourly": "temperature_2m",
            "forecast_days": 1,
            "timezone": "UTC",
        }
        started = time.perf_counter()
        try:
            response = await self._http.get(
                self._forecast_url,
                params=params,
                timeout=httpx.Timeout(_PROBE_TIMEOUT_SECONDS),
            )
        except httpx.TimeoutException as exc:
            return ProbeResult(
                status="timeout",
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_message=str(exc),
            )
        except httpx.TransportError as exc:
            return ProbeResult(
                status="error",
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_message=str(exc),
            )
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            return ProbeResult(
                status="error",
                latency_ms=latency_ms,
                error_message=f"HTTP {response.status_code}",
            )
        return ProbeResult(status="ok", latency_ms=latency_ms)

    async def fetch(
        self,
        *,
        latitude: float,
        longitude: float,
        past_hours: int,
        forecast_hours: int,
    ) -> FetchResult:
        # Open-Meteo's `/forecast` accepts past_days + forecast_days
        # rather than hour counts. Convert with a one-day floor so we
        # always get the leading edge of the timeline aligned to a
        # whole-day boundary; we filter back to exact hours below.
        past_days = max(1, (past_hours + 23) // 24)
        forecast_days = max(1, (forecast_hours + 23) // 24)
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(_HOURLY_VARS),
            "past_days": past_days,
            "forecast_days": forecast_days,
            "timezone": "UTC",
        }
        body = await self._get_with_retry(self._forecast_url, params=params)

        hourly = body.get("hourly", {}) or {}
        times: list[str] = list(hourly.get("time", []) or [])
        if not times:
            return FetchResult(forecast_issued_at=_now_utc())

        # Open-Meteo timestamps are local-naive ISO8601 in the requested
        # timezone (UTC here). Parse + tag UTC so we never accidentally
        # write naive timestamps into TIMESTAMPTZ columns.
        parsed_times = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in times]

        air_temp = _decimal_col(hourly.get("temperature_2m"))
        humidity = _decimal_col(hourly.get("relative_humidity_2m"))
        precip = _decimal_col(hourly.get("precipitation"))
        precip_prob = _decimal_col(hourly.get("precipitation_probability"))
        wind_speed = _decimal_col(hourly.get("wind_speed_10m"))
        wind_dir = _decimal_col(hourly.get("wind_direction_10m"))
        pressure = _decimal_col(hourly.get("pressure_msl"))
        radiation = _decimal_col(hourly.get("shortwave_radiation"))
        cloud_cover = _decimal_col(hourly.get("cloud_cover"))
        et0 = _decimal_col(hourly.get("et0_fao_evapotranspiration"))

        now = _now_utc()
        # Anchor the issuance to the response's "current.time" if Open-
        # Meteo returns one; otherwise fall back to wall clock. The
        # `forecast_issued_at` row is what the latest-forecast SQL
        # ranks on, so it must be unique-per-fetch — we never round it.
        current = body.get("current", {}) or {}
        issued_at_str = current.get("time")
        if isinstance(issued_at_str, str):
            try:
                forecast_issued_at = datetime.fromisoformat(issued_at_str).replace(tzinfo=UTC)
            except ValueError:
                forecast_issued_at = now
        else:
            forecast_issued_at = now

        observations: list[HourlyObservation] = []
        forecasts: list[HourlyForecast] = []
        for idx, t in enumerate(parsed_times):
            if t <= now:
                observations.append(
                    HourlyObservation(
                        time=t,
                        air_temp_c=air_temp[idx],
                        humidity_pct=humidity[idx],
                        precipitation_mm=precip[idx],
                        wind_speed_m_s=wind_speed[idx],
                        wind_direction_deg=wind_dir[idx],
                        pressure_hpa=pressure[idx],
                        solar_radiation_w_m2=radiation[idx],
                        cloud_cover_pct=cloud_cover[idx],
                        et0_mm=et0[idx],
                    )
                )
            else:
                forecasts.append(
                    HourlyForecast(
                        time=t,
                        air_temp_c=air_temp[idx],
                        humidity_pct=humidity[idx],
                        precipitation_mm=precip[idx],
                        precipitation_probability_pct=precip_prob[idx],
                        wind_speed_m_s=wind_speed[idx],
                        solar_radiation_w_m2=radiation[idx],
                        et0_mm=et0[idx],
                    )
                )

        # Trim to the caller's requested horizon — Open-Meteo always
        # returns whole-day blocks.
        observations = observations[-past_hours:]
        forecasts = forecasts[:forecast_hours]

        return FetchResult(
            forecast_issued_at=forecast_issued_at,
            observations=tuple(observations),
            forecasts=tuple(forecasts),
        )

    # -- internals ------------------------------------------------------

    async def _get_with_retry(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        """GET with bounded retries on 5xx + network errors."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._http.get(url, params=params)
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt == _MAX_RETRIES - 1:
                    raise
                self._log.warning(
                    "open_meteo_transport_retry",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                continue
            if response.status_code >= 500:
                last_exc = httpx.HTTPStatusError(
                    f"{response.status_code}", request=response.request, response=response
                )
                if attempt == _MAX_RETRIES - 1:
                    response.raise_for_status()
                self._log.warning(
                    "open_meteo_5xx_retry",
                    attempt=attempt + 1,
                    status=response.status_code,
                )
                continue
            response.raise_for_status()
            data = response.json()
            assert isinstance(data, dict)
            return data
        # Unreachable: the loop either returns or raises.
        raise RuntimeError(f"Open-Meteo request failed: {last_exc}")


def _decimal_col(values: Any) -> list[Decimal | None]:
    """Coerce a list-of-floats column into list[Decimal | None]."""
    if not isinstance(values, list):
        return []
    out: list[Decimal | None] = []
    for v in values:
        if v is None:
            out.append(None)
        else:
            # Decimal(str(float)) avoids the float repr noise that
            # would otherwise show up in NUMERIC columns.
            out.append(Decimal(str(v)))
    return out


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


# Type-checker assist: the concrete class satisfies the Protocol.
_check: type[WeatherProvider] = OpenMeteoProvider
