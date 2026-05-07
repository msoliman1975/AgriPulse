import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "@/api/errors";
import { getForecast, triggerRefresh, type ForecastResponse } from "@/api/weather";
import { formatPrecip, formatProbability, formatTemp } from "@/lib/weatherUnits";
import { usePrefs } from "@/prefs/PrefsContext";
import { useCapability } from "@/rbac/useCapability";

interface Props {
  blockId: string;
  farmId: string;
  /** Display name shown in the panel description ("forecast for {farm}"). */
  farmName?: string | null;
}

/**
 * Block-detail card with a 5-day daily forecast for the block's farm.
 *
 * Data source: `GET /v1/blocks/{id}/weather/forecast?horizon_days=5`,
 * which aggregates the latest forecast issuance into local-tz day buckets
 * server-side. Display units come from the user's `weatherUnit` pref
 * (metric or imperial) — backend always returns canonical SI.
 *
 * RBAC:
 *   - Hidden entirely if the user lacks `weather.read` (BlockDetailPage
 *     gates the mount).
 *   - Refresh button hidden when the user lacks `weather.refresh`.
 */
export function WeatherForecastPanel({ blockId, farmId, farmName }: Props): JSX.Element {
  const { t } = useTranslation("weather");
  const { weatherUnit } = usePrefs();
  const canRefresh = useCapability("weather.refresh", { farmId });

  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);

  const reload = async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const data = await getForecast(blockId, { horizon_days: 5 });
      setForecast(data);
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blockId]);

  const handleRefresh = async (): Promise<void> => {
    setRefreshBusy(true);
    setRefreshMessage(null);
    try {
      const resp = await triggerRefresh(blockId);
      setRefreshMessage(
        resp.queued_farm_ids.length === 0 ? t("refresh.noActive") : t("refresh.queued"),
      );
      // The fetch is async on the worker; give it a moment to land then
      // reload. The user sees the refreshed forecast within ~3-5s in dev.
      window.setTimeout(() => void reload(), 4000);
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setRefreshBusy(false);
    }
  };

  const dateFmt = useMemo(
    () =>
      new Intl.DateTimeFormat(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
      }),
    [],
  );
  const issuedAtFmt = useMemo(
    () => new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }),
    [],
  );

  const description =
    forecast === null
      ? null
      : farmName
        ? t("panel.description", { farmName, timezone: forecast.timezone })
        : t("panel.descriptionFallback", { timezone: forecast.timezone });

  return (
    <section className="card space-y-3" aria-label={t("panel.heading")}>
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-800">{t("panel.heading")}</h2>
          {description ? <p className="text-sm text-slate-600">{description}</p> : null}
          <p className="mt-1 text-xs text-slate-500">{t("panel.farmCaption")}</p>
        </div>
        {canRefresh ? (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => void handleRefresh()}
            disabled={refreshBusy}
          >
            {refreshBusy ? t("refresh.busy") : t("refresh.button")}
          </button>
        ) : null}
      </header>

      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {t("panel.error", { message: error })}
        </p>
      ) : null}
      {refreshMessage ? (
        <p role="status" className="text-sm text-slate-600">
          {refreshMessage}
        </p>
      ) : null}

      {loading ? (
        <p role="status">{t("panel.loading")}</p>
      ) : forecast === null || forecast.days.length === 0 ? (
        <p className="text-sm text-slate-600">{t("panel.empty")}</p>
      ) : (
        <>
          <p className="text-xs text-slate-500">
            {forecast.forecast_issued_at
              ? t("panel.issuedAt", {
                  date: issuedAtFmt.format(new Date(forecast.forecast_issued_at)),
                })
              : t("panel.neverIssued")}
          </p>
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {forecast.days.map((day, idx) => {
              const high = formatTemp(day.high_c, weatherUnit);
              const low = formatTemp(day.low_c, weatherUnit);
              return (
                <li
                  key={day.date}
                  className="rounded-md border border-slate-200 bg-white p-3 text-sm"
                >
                  <p className="font-medium text-slate-800">
                    {idx === 0
                      ? t("day.today")
                      : idx === 1
                        ? t("day.tomorrow")
                        : dateFmt.format(parseLocalDate(day.date))}
                  </p>
                  <p className="mt-1 text-slate-700">
                    <span className="font-semibold">{high.display}</span>
                    {" / "}
                    <span className="text-slate-500">{low.display}</span>
                    {" "}
                    <span className="text-xs text-slate-400">{high.unit}</span>
                  </p>
                  <p className="mt-1 text-slate-600">
                    {t("day.precip")}: {formatPrecip(day.precip_mm_total, weatherUnit)}
                  </p>
                  <p className="text-slate-600">
                    {t("day.precipChance")}: {formatProbability(day.precip_probability_max_pct)}
                  </p>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

/**
 * Parse a YYYY-MM-DD string as a *local* calendar date — `new Date(string)`
 * would interpret it as UTC midnight, which can shift the displayed
 * weekday by a day west of the prime meridian.
 */
function parseLocalDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}
