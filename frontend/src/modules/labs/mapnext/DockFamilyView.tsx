// One agronomic family of indices — the Vigour & canopy / Nutrition /
// Moisture tabs of the Block Dock.
//
// Replaces the single "Index" tab, whose pill row listed all seven indices
// with no values and no grouping. A family tab answers one question, so it can
// afford to show every member's current reading and 7-day delta side by side
// (the comparison the flat row lost) and still chart the one index in the
// family the block-level API actually serves.
//
// It also has room to say what each index IS and what its number MEANS, which
// no surface in the console did: the reference column carries a definition and
// a scale per index, and the charted reading is turned into a sentence via
// INDEX_BANDS rather than left as a bare decimal.
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { getTimeseries, type IndexCode as ApiIndexCode } from "@/api/indices";
import type { IndexCode, IndexSeries } from "../map/types";
import {
  FAMILY_PRIMARY,
  HEALTH_DOT,
  INDEX_FAMILIES,
  INDEX_META,
  isBlockLevel,
  type IndexFamilyKey,
} from "./constants";
import { bandFor, deltaLabel, fmt, isoDay, isoDaysBefore, shortDate } from "./dockFormat";
import { Dot } from "./ui";

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
  const { t, i18n } = useTranslation("farmConsole");
  const lang = i18n.language;
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
          {shortDate(points[i].time, lang)}
        </text>
      ))}
    </svg>
  );
}

/** One index in the family. Block-level members carry their reading and are
 * clickable — clicking paints the map with that index, which is what the
 * original grouped cards did. Grid-only members are shown disabled rather than
 * hidden, so it stays obvious why they have no block-wide number. */
function IndexCard({
  code,
  series,
  active,
  onSelect,
}: {
  code: ApiIndexCode;
  series: IndexSeries | undefined;
  active: boolean;
  onSelect: () => void;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const gridOnly = !isBlockLevel(code);
  const d = deltaLabel(series?.trend_7d_delta);
  const meaning = t(`dock.meaning.${code}`);

  return (
    <button
      type="button"
      disabled={gridOnly}
      aria-pressed={active}
      title={gridOnly ? t("inspector.gridOnlyIndex", { code: INDEX_META[code].label }) : meaning}
      onClick={onSelect}
      className={clsx(
        "relative flex min-w-[104px] flex-col items-start gap-0.5 rounded-xl border px-3 py-2 text-start",
        active ? "border-ap-primary bg-ap-primary-soft" : "border-ap-line hover:bg-ap-primary-soft/50",
        gridOnly && "cursor-not-allowed opacity-45 hover:bg-transparent",
      )}
    >
      {gridOnly ? null : <Dot color={d.color} className="absolute end-2.5 top-2.5" />}
      <span className="text-xs font-bold tracking-wide text-ap-ink">{INDEX_META[code].label}</span>
      <span className="text-lg font-bold leading-tight tabular-nums text-ap-ink">
        {gridOnly ? "—" : fmt(series?.current ?? null)}
      </span>
      <span className="text-xs font-bold" style={{ color: gridOnly ? HEALTH_DOT.unknown : d.color }}>
        {gridOnly ? t("dock.gridOnly") : `${d.arrow} ${d.text}`}
      </span>
    </button>
  );
}

export function DockFamilyView({
  blockId,
  family,
  indices,
  activeIndex,
  onActiveIndexChange,
}: {
  blockId: string;
  family: IndexFamilyKey;
  /** The 30-day bundle already loaded for the block, so the cards read their
   *  current value and delta without a second round trip per tab. */
  indices: Record<IndexCode, IndexSeries>;
  activeIndex: ApiIndexCode;
  onActiveIndexChange: (c: ApiIndexCode) => void;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [from, setFrom] = useState(() => isoDaysBefore(30));
  const [to, setTo] = useState(() => isoDay());

  const members = INDEX_FAMILIES.find((f) => f.key === family)?.indices ?? [];
  // The tab decides what is charted — its one block-level index — while
  // `activeIndex` stays the map's business. Reading Nutrition therefore never
  // silently repaints the map; clicking a card does that, explicitly.
  const charted = FAMILY_PRIMARY[family];

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
  const chartedBand = bandFor(charted, current);

  return (
    <div className="grid h-full grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
      <div className="flex min-h-0 flex-col gap-2">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label={t(`dock.family.${family}`)}>
          {members.map((code) => (
            <IndexCard
              key={code}
              code={code}
              series={isBlockLevel(code) ? indices[code] : undefined}
              active={activeIndex === code}
              onSelect={() => onActiveIndexChange(code)}
            />
          ))}
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
          {t("dock.index.charting", { code: INDEX_META[charted].label })} ·{" "}
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

        {/* What the number above actually says about the block. The charted
            index is the family's only block-level member, so this is the one
            live interpretation on the tab — the rest carry their scale. */}
        {chartedBand ? (
          <div
            className="mt-2 flex items-start gap-2 rounded-xl border px-3 py-2 text-sm text-ap-ink"
            style={{ borderColor: HEALTH_DOT[chartedBand.tone] }}
          >
            <Dot color={HEALTH_DOT[chartedBand.tone]} className="mt-1.5 shrink-0" />
            <span>{t(`dock.band.${charted}.${chartedBand.key}`)}</span>
          </div>
        ) : null}

        <div className="mt-3 text-xs font-bold uppercase tracking-wide text-ap-primary">
          {t("dock.inThisFamily")}
        </div>
        <div className="mt-1 flex flex-col gap-1.5">
          {members.map((code) => (
            <div key={code} className="rounded-xl border border-ap-line px-3 py-2 text-sm">
              <div className="flex items-baseline gap-2">
                <span className="font-semibold text-ap-ink">{INDEX_META[code].label}</span>
                <span className="text-xs text-ap-muted">
                  {isBlockLevel(code) ? t("dock.blockLevel") : t("dock.gridOnly")}
                </span>
              </div>
              <dl className="mt-1 flex flex-col gap-1.5">
                <div>
                  <dt className="text-[11px] font-bold uppercase tracking-wide text-ap-muted">
                    {t("dock.definition")}
                  </dt>
                  <dd className="text-ap-ink/90">{t(`dock.def.${code}`)}</dd>
                </div>
                <div>
                  <dt className="text-[11px] font-bold uppercase tracking-wide text-ap-muted">
                    {t("dock.howToRead")}
                  </dt>
                  <dd className="text-ap-muted">{t(`dock.scale.${code}`)}</dd>
                </div>
              </dl>
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-ap-muted">{t("dock.readingCaveat")}</p>
      </div>
    </div>
  );
}
