import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { isApiError } from "@/api/errors";
import {
  getTimeseries,
  type IndexCode,
  type IndexTimeseriesPoint,
  type TimeseriesGranularity,
} from "@/api/indices";

interface Props {
  blockId: string;
  /** Defaults to NDVI; user can switch via the combobox. */
  initialIndex?: IndexCode;
}

const ALL_INDICES: readonly IndexCode[] = ["ndvi", "ndwi", "evi", "savi", "ndre", "gndvi"] as const;

interface ChartPoint {
  time: number;
  mean: number | null;
}

/**
 * Recharts LineChart of one index's daily/weekly mean over time.
 * Renders Latin numerals regardless of UI language (ARCHITECTURE § 11).
 */
export function IndexTrendChart({ blockId, initialIndex = "ndvi" }: Props): JSX.Element {
  const { t } = useTranslation("indices");
  const [indexCode, setIndexCode] = useState<IndexCode>(initialIndex);
  const [granularity, setGranularity] = useState<TimeseriesGranularity>("daily");
  const [points, setPoints] = useState<IndexTimeseriesPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTimeseries(blockId, indexCode, { granularity })
      .then((resp) => {
        if (cancelled) return;
        setPoints(resp.points);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [blockId, indexCode, granularity]);

  const chartData = useMemo<ChartPoint[]>(
    () =>
      points.map((p) => ({
        time: new Date(p.time).getTime(),
        mean: p.mean !== null ? Number(p.mean) : null,
      })),
    [points],
  );

  // Latin numerals + ISO-style date even in Arabic UI per ARCH § 11.
  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat("en-US", { month: "short", day: "2-digit" }),
    [],
  );
  const numFmt = useMemo(() => new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 }), []);

  return (
    <section className="card space-y-3" aria-label={t("trend.heading")}>
      <header>
        <h2 className="text-lg font-semibold text-slate-800">{t("trend.heading")}</h2>
      </header>

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="label" htmlFor={`index-picker-${blockId}`}>
            {t("controls.indexLabel")}
          </label>
          <select
            id={`index-picker-${blockId}`}
            className="input"
            value={indexCode}
            onChange={(e) => setIndexCode(e.target.value as IndexCode)}
          >
            {ALL_INDICES.map((code) => (
              <option key={code} value={code}>
                {t(`names.${code}`)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor={`granularity-picker-${blockId}`}>
            {t("controls.granularityLabel")}
          </label>
          <select
            id={`granularity-picker-${blockId}`}
            className="input"
            value={granularity}
            onChange={(e) => setGranularity(e.target.value as TimeseriesGranularity)}
          >
            <option value="daily">{t("controls.daily")}</option>
            <option value="weekly">{t("controls.weekly")}</option>
          </select>
        </div>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {t("trend.error", { message: error })}
        </p>
      ) : loading ? (
        <p role="status">{t("trend.loading")}</p>
      ) : chartData.length === 0 ? (
        <p className="text-sm text-slate-600">{t("trend.empty")}</p>
      ) : (
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 16, left: 0 }}>
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="2 2" />
              <XAxis
                dataKey="time"
                type="number"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(v: number) => dateFmt.format(new Date(v))}
                label={{ value: t("axis.time"), position: "insideBottom", offset: -8 }}
              />
              <YAxis
                domain={[-1, 1]}
                tickFormatter={(v: number) => numFmt.format(v)}
                label={{
                  value: t("axis.value"),
                  angle: -90,
                  position: "insideLeft",
                }}
              />
              <Tooltip
                labelFormatter={(v: number) => dateFmt.format(new Date(v))}
                formatter={(value: number) => [numFmt.format(value), t("tooltip.mean")]}
              />
              <Line
                type="monotone"
                dataKey="mean"
                stroke="#16a34a"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
