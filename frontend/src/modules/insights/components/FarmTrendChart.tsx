import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  getFarmAnnotations,
  getFarmIndexTimeseries,
  type AnnotationSeverity,
  type FarmIndexTimeseriesPoint,
} from "@/api/insights";
import { Skeleton } from "@/components/Skeleton";

interface Props {
  farmId: string;
  indexCode?: string;
}

/**
 * Multi-block NDVI (or other index) trend chart for the Farm health
 * overview. Replaces the V1 TrendChartCard's "first block only"
 * stopgap with the farm-rollup endpoint (B.2).
 *
 * Layout: one Line per block, colour cycle (10-stop d3-category palette).
 * The y-axis is auto-scaled — NDVI ranges [-1, 1] but most farm
 * conditions sit in [0.2, 0.9]; letting recharts pick keeps the lines
 * readable without forcing the viewer to stare at half-empty axis.
 */
export function FarmTrendChart({ farmId, indexCode = "ndvi" }: Props): ReactNode {
  const { t } = useTranslation("insights");
  const { data, isLoading, isError } = useQuery({
    queryKey: ["insights", "trend", farmId, indexCode] as const,
    queryFn: () => getFarmIndexTimeseries(farmId, { index_code: indexCode }),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });
  // B.3 annotations — independent query so a slow alerts join can't
  // delay the chart's first paint. The trend chart renders without
  // annotations if this fails or is still loading.
  const annotationsQ = useQuery({
    queryKey: ["insights", "annotations", farmId] as const,
    queryFn: () => getFarmAnnotations(farmId),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });

  // Reshape: flat [{time, block_id, block_name, value}] → keyed
  // [{time, <blockName1>: value, <blockName2>: value, ...}] so
  // recharts can render one Line per block from one chartData prop.
  // Block names are used as dataKey because they're stable per query
  // result; if two blocks share a name (rare; codes are unique) the
  // later wins — acceptable for V1 visual exploration.
  const { chartData, blockNames } = useMemo(
    () => _reshapeForRecharts(data?.points ?? []),
    [data?.points],
  );

  return (
    <section
      aria-labelledby="farm-trend-heading"
      className="rounded-xl border border-ap-line bg-ap-panel p-4"
    >
      <header className="flex items-baseline justify-between">
        <h2
          id="farm-trend-heading"
          className="text-sm font-semibold uppercase tracking-wider text-ap-muted"
        >
          {t("trend.title")}
        </h2>
        <span className="text-[11px] text-ap-muted">
          {t("trend.indexLabel", { code: indexCode.toUpperCase() })}
        </span>
      </header>

      <div className="mt-3 min-h-[260px]">
        {isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : isError ? (
          <p className="py-12 text-center text-sm text-ap-crit">{t("trend.loadFailed")}</p>
        ) : chartData.length === 0 ? (
          <p className="py-12 text-center text-sm text-ap-muted">{t("trend.empty")}</p>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 16, left: 0 }}>
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="2 2" />
              <XAxis dataKey="time" tickFormatter={_fmtDateTick} fontSize={11} />
              <YAxis fontSize={11} />
              <Tooltip
                labelFormatter={(label: string) => new Date(label).toLocaleDateString()}
                formatter={(value: number) => value.toFixed(3)}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {blockNames.map((name, i) => (
                <Line
                  key={name}
                  type="monotone"
                  dataKey={name}
                  stroke={_lineColor(i)}
                  strokeWidth={1.75}
                  dot={false}
                  connectNulls
                />
              ))}
              {/* B.3: alert-opened markers. ReferenceLine stroke
                  carries the severity colour; recharts doesn't
                  expose per-line tooltips so the label rides in
                  the line's `label` prop. */}
              {(annotationsQ.data?.annotations ?? []).map((a) => (
                <ReferenceLine
                  key={`${a.time}-${a.block_id ?? "farm"}`}
                  x={a.time}
                  stroke={_annotationColor(a.severity)}
                  strokeWidth={1}
                  strokeDasharray="3 3"
                  ifOverflow="hidden"
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}

// d3-category10 — distinct enough at 10 blocks; >10 wraps. Real
// farms rarely exceed 10 active blocks; B.3 can add a smarter
// hashing scheme if needed.
const PALETTE = [
  "#1f77b4",
  "#ff7f0e",
  "#2ca02c",
  "#d62728",
  "#9467bd",
  "#8c564b",
  "#e377c2",
  "#7f7f7f",
  "#bcbd22",
  "#17becf",
];

function _lineColor(index: number): string {
  return PALETTE[index % PALETTE.length];
}

// Annotation colour palette — matches the HEALTH_CHIP scheme in
// BlockHealthScorecard so the operator's eye reads the same colour
// language across both surfaces.
function _annotationColor(severity: AnnotationSeverity): string {
  if (severity === "critical") return "#A32D2D";
  if (severity === "warning") return "#854F0B";
  return "#9C9C9C";
}

function _fmtDateTick(value: string): string {
  const d = new Date(value);
  // M/d — terse for the x-axis. Tooltip carries the full date.
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

interface ReshapedRow {
  time: string;
  [blockName: string]: string | number;
}

export function _reshapeForRecharts(points: readonly FarmIndexTimeseriesPoint[]): {
  chartData: ReshapedRow[];
  blockNames: string[];
} {
  const byTime = new Map<string, ReshapedRow>();
  const names = new Set<string>();
  for (const p of points) {
    names.add(p.block_name);
    const existing = byTime.get(p.time);
    const value = Number(p.value);
    if (existing) {
      existing[p.block_name] = value;
    } else {
      byTime.set(p.time, { time: p.time, [p.block_name]: value });
    }
  }
  const chartData = Array.from(byTime.values()).sort((a, b) =>
    a.time < b.time ? -1 : a.time > b.time ? 1 : 0,
  );
  return { chartData, blockNames: Array.from(names) };
}
