// "Index" tab of the Block Dock. The narrow inspector could only afford a
// sparkline over a fixed 30 days; the dock has the width for a real chart
// with its own date range, so this queries the timeseries endpoint directly
// rather than reusing the 30-day window baked into loadUnitDetail.
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { getTimeseries, type IndexCode as ApiIndexCode } from "@/api/indices";
import { BLOCK_LEVEL_INDICES, HEALTH_DOT, INDEX_META, isBlockLevel, MAP_INDEX_ORDER } from "./constants";
import { fmt, isoDay, isoDaysBefore, shortDate } from "./dockFormat";

const PRESETS: { days: number; key: string }[] = [
  { days: 30, key: "d30" },
  { days: 90, key: "d90" },
  { days: 365, key: "season" },
];

interface Point {
  time: string;
  value: number;
}

function Chart({ points }: { points: Point[] }): ReactNode {
  const { t } = useTranslation("farmConsole");
  if (points.length < 2) {
    return (
      <div className="flex h-[168px] items-center justify-center rounded-xl border border-ap-line text-sm text-ap-muted">
        {t("dock.index.notEnough")}
      </div>
    );
  }
  const W = 620;
  const H = 168;
  const padL = 36;
  const padR = 12;
  const padT = 10;
  const padB = 22;
  const vals = points.map((p) => p.value);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const pad = (hi - lo) * 0.35 || 0.05;
  const yMin = lo - pad;
  const yMax = hi + pad;
  const X = (i: number): number => padL + (i / (points.length - 1)) * (W - padL - padR);
  const Y = (v: number): number => padT + (1 - (v - yMin) / (yMax - yMin)) * (H - padT - padB);

  const line = points.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(p.value).toFixed(1)}`).join(" ");
  const gridlines = [0, 1, 2, 3, 4].map((g) => {
    const v = yMin + (g / 4) * (yMax - yMin);
    return { y: Y(v), label: v.toFixed(2) };
  });
  const ticks = [0, Math.floor((points.length - 1) / 2), points.length - 1];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-[168px] w-full"
      role="img"
      aria-label={t("dock.index.chartLabel")}
    >
      {gridlines.map((g) => (
        <g key={g.label}>
          <line x1={padL} x2={W - padR} y1={g.y} y2={g.y} stroke="currentColor" className="text-ap-line" strokeWidth={1} />
          <text x={padL - 6} y={g.y + 3} textAnchor="end" className="fill-ap-muted text-[9px]">
            {g.label}
          </text>
        </g>
      ))}
      <path d={line} fill="none" stroke={HEALTH_DOT.healthy} strokeWidth={2} vectorEffect="non-scaling-stroke" />
      <circle cx={X(points.length - 1)} cy={Y(points[points.length - 1].value)} r={3.5} fill={HEALTH_DOT.healthy} />
      {ticks.map((i, k) => (
        <text
          key={i}
          x={X(i)}
          y={H - 6}
          textAnchor={k === 0 ? "start" : k === 2 ? "end" : "middle"}
          className="fill-ap-muted text-[9px]"
        >
          {shortDate(points[i].time)}
        </text>
      ))}
    </svg>
  );
}

export function DockIndexView({
  blockId,
  activeIndex,
  onActiveIndexChange,
}: {
  blockId: string;
  activeIndex: ApiIndexCode;
  onActiveIndexChange: (c: ApiIndexCode) => void;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [from, setFrom] = useState(() => isoDaysBefore(30));
  const [to, setTo] = useState(() => isoDay());

  // Only the three block-level indices have a time series; the rest exist
  // solely on the sub-block grid, so their pills are disabled.
  const charted = isBlockLevel(activeIndex) ? activeIndex : "ndvi";

  const seriesQ = useQuery({
    queryKey: ["labs/mapnext/dockSeries", blockId, charted, from, to],
    queryFn: () => getTimeseries(blockId, charted, { granularity: "daily", from, to }),
    staleTime: 60_000,
  });

  const points = useMemo<Point[]>(() => {
    const raw = seriesQ.data?.points ?? [];
    return raw
      .map((p) => ({ time: p.time, value: p.mean == null ? Number.NaN : Number(p.mean) }))
      .filter((p): p is Point => Number.isFinite(p.value));
  }, [seriesQ.data]);

  const current = points.length ? points[points.length - 1].value : null;
  // Change over the trailing 14 days of whatever window is on screen.
  const earlier = useMemo(() => {
    if (points.length < 2) return null;
    const cutoff = Date.parse(points[points.length - 1].time) - 14 * 86_400_000;
    const before = points.filter((p) => Date.parse(p.time) <= cutoff);
    return before.length ? before[before.length - 1].value : points[0].value;
  }, [points]);
  const delta = current != null && earlier != null && earlier !== 0 ? ((current - earlier) / Math.abs(earlier)) * 100 : null;

  const meta = INDEX_META[activeIndex];

  return (
    <div className="grid h-full grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] gap-6">
      <div className="flex min-h-0 flex-col gap-2">
        {/* index pills */}
        <div className="flex flex-wrap gap-1" role="group" aria-label={t("dock.index.pickIndex")}>
          {MAP_INDEX_ORDER.map((code) => {
            const disabled = !isBlockLevel(code);
            return (
              <button
                key={code}
                type="button"
                disabled={disabled}
                aria-pressed={activeIndex === code}
                title={disabled ? t("inspector.gridOnlyIndex", { code: INDEX_META[code].label }) : INDEX_META[code].meaning}
                onClick={() => onActiveIndexChange(code)}
                className={clsx(
                  "rounded-lg border px-2.5 py-1 text-xs font-semibold",
                  activeIndex === code
                    ? "border-ap-primary bg-ap-primary-soft text-ap-ink"
                    : "border-ap-line text-ap-muted hover:bg-ap-bg/60",
                  disabled && "cursor-not-allowed opacity-40 hover:bg-transparent",
                )}
              >
                {INDEX_META[code].label}
              </button>
            );
          })}
        </div>

        {/* range */}
        <div className="flex flex-wrap items-center gap-1.5">
          <input
            type="date"
            value={from}
            max={to}
            aria-label={t("dock.index.from")}
            onChange={(e) => setFrom(e.target.value)}
            className="rounded-lg border border-ap-line bg-ap-panel px-2 py-1 text-xs text-ap-ink"
          />
          <span className="text-ap-muted" aria-hidden="true">
            →
          </span>
          <input
            type="date"
            value={to}
            min={from}
            aria-label={t("dock.index.to")}
            onChange={(e) => setTo(e.target.value)}
            className="rounded-lg border border-ap-line bg-ap-panel px-2 py-1 text-xs text-ap-ink"
          />
          {PRESETS.map((p) => (
            <button
              key={p.key}
              type="button"
              onClick={() => {
                setFrom(isoDaysBefore(p.days));
                setTo(isoDay());
              }}
              className="rounded-lg border border-ap-line px-2 py-1 text-xs font-semibold text-ap-muted hover:bg-ap-bg/60"
            >
              {t(`dock.index.preset.${p.key}`)}
            </button>
          ))}
        </div>

        {seriesQ.isLoading ? (
          <div className="h-[168px] animate-pulse rounded-xl bg-ap-line/40" />
        ) : seriesQ.isError ? (
          <div className="flex h-[168px] items-center justify-center rounded-xl border border-ap-line text-sm text-ap-muted">
            {t("dock.index.error")}
          </div>
        ) : (
          <Chart points={points} />
        )}
        <div className="text-xs text-ap-muted">
          {t("dock.index.footer", { count: points.length })}
        </div>
      </div>

      <div className="min-h-0 overflow-auto">
        <div className="flex items-end gap-4">
          <span className="text-3xl font-bold tabular-nums text-ap-ink">{fmt(current)}</span>
          <span className="pb-1 text-xs">
            <span
              className="font-semibold tabular-nums"
              style={{
                color:
                  delta == null
                    ? HEALTH_DOT.unknown
                    : delta > 0.6
                      ? HEALTH_DOT.healthy
                      : delta < -2
                        ? HEALTH_DOT.critical
                        : delta < -0.6
                          ? HEALTH_DOT.watch
                          : HEALTH_DOT.unknown,
              }}
            >
              {delta == null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`}
            </span>
            <br />
            <span className="text-ap-muted">{t("dock.index.over14d")}</span>
          </span>
        </div>

        <div className="mt-3 text-xs font-bold uppercase tracking-wide text-ap-primary">
          {t("dock.index.definition")}
        </div>
        <div className="mt-1 rounded-xl border border-ap-line px-3 py-2.5 text-sm">
          <div className="font-semibold text-ap-ink">
            {meta.label} <span className="font-normal text-ap-muted">· {meta.family}</span>
          </div>
          <p className="mt-1 text-ap-muted">{meta.meaning}</p>
          {!isBlockLevel(activeIndex) ? (
            <p className="mt-1.5 text-ap-muted">
              {t("inspector.gridOnlyIndex", { code: meta.label })}{" "}
              {t("dock.index.showingInstead", { code: INDEX_META[charted].label })}
            </p>
          ) : null}
        </div>

        <div className="mt-3 text-xs font-bold uppercase tracking-wide text-ap-primary">
          {t("dock.index.otherIndices")}
        </div>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {BLOCK_LEVEL_INDICES.filter((c) => c !== activeIndex).map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => onActiveIndexChange(c)}
              className="rounded-lg border border-ap-line px-2.5 py-1 text-xs font-semibold text-ap-muted hover:bg-ap-bg/60"
            >
              {INDEX_META[c].label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
