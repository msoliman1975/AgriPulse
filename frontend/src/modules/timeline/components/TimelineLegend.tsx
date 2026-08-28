// What the colours on the replay mean.
//
// The Farm Console's `IndexLegend` answers "how much land is in each
// class"; this one answers only "what is this colour". The replay has no
// per-class areas — it never asks TiTiler for statistics, because doing it
// once per pass would be one request per frame — so a column of areas here
// would be either empty or a lie.
//
// What it does NOT do is restate the class table. The rows, the colours
// and the boundaries all come from `indexClasses.ts`, the same module that
// builds the TiTiler colormap the replay's pixels are painted with, and
// the class names come from the same `farmConsole:legend.class.*` copy the
// console reads. One table, one wording, two screens — so a reader who has
// learned the console's greens has learned this map's greens, and neither
// can drift from the pixels.

import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { getIndexCatalog, type AnyIndexCode } from "@/api/indices";
import { Card } from "@/components/Card";
import { indexDecimals } from "@/lib/indexFormat";
import { THERMAL_NATIVE_RESOLUTION_M } from "@/lib/thermalResolution";
import {
  CLASS_HINT,
  CLASS_VOCAB,
  classesFor,
  formatRange,
  lowerBound,
  READ_RELATIVELY,
} from "@/modules/labs/console/indexClasses";
import { INDEX_META, isThermalIndex } from "@/modules/labs/mapnext/constants";

interface Props {
  code: AnyIndexCode;
  className?: string;
}

/** Same as the console legend: two decimals for a dimensionless index. */
const LEGEND_DIMENSIONLESS_DECIMALS = 2;

export function TimelineLegend({ code, className }: Props): ReactNode {
  const { t } = useTranslation(["timeline", "farmConsole"]);
  const [collapsed, setCollapsed] = useState(false);

  // The index's display unit, from the platform catalog. Same query key as
  // the console's, so a reader arriving from there pays nothing for it, and
  // a failure degrades to the dimensionless case rather than to a wrong
  // hardcoded unit.
  const catalogQ = useQuery({
    queryKey: ["indices", "catalog"] as const,
    queryFn: getIndexCatalog,
    staleTime: 60 * 60_000,
  });
  const indexUnit = catalogQ.data?.find((e) => e.code === code)?.unit ?? "";

  const num = (n: number): string =>
    n.toFixed(indexUnit ? indexDecimals(indexUnit) : LEGEND_DIMENSIONLESS_DECIMALS);

  const vocab = CLASS_VOCAB[code];
  const hint = CLASS_HINT[code];

  // Highest VALUE first, so the range column reads downward whichever index
  // is on. Not "best first": NDWI's scale is inverted, so its healthy end
  // sits at the bottom while its colours still run red-for-bad.
  const rows = useMemo(
    () =>
      classesFor(code)
        .map((cls, i) => ({ cls, lo: lowerBound(code, i) }))
        .reverse(),
    [code],
  );

  const header = (
    <div className="flex items-center gap-2">
      <span className="text-card-title font-bold text-ap-ink">{INDEX_META[code].label}</span>
      {/* The unit sits in the heading, not on every row: a narrow range
          column cannot repeat "°C" six times without truncating numbers. */}
      {indexUnit ? (
        <span dir="ltr" className="text-meta font-semibold text-ap-muted">
          {indexUnit}
        </span>
      ) : null}
      <span className="text-meta text-ap-muted">{t("timeline:legend.title")}</span>
    </div>
  );

  const toggle = (
    <button
      type="button"
      onClick={() => setCollapsed((v) => !v)}
      aria-expanded={!collapsed}
      title={collapsed ? t("timeline:legend.expand") : t("timeline:legend.collapse")}
      className="grid h-6 w-6 place-items-center rounded-md text-ap-muted hover:bg-ap-bg"
    >
      {collapsed ? "▴" : "▾"}
    </button>
  );

  return (
    <Card
      className={className}
      title={header}
      actions={toggle}
      noPadding
      data-testid="timeline-legend"
    >
      {collapsed ? null : (
        <>
          <ul className="max-h-56 overflow-auto py-0.5">
            {rows.map(({ cls, lo }) => (
              <li key={cls.key} className="flex items-center gap-2 px-3 py-[3px]">
                <span
                  aria-hidden="true"
                  className="h-3 w-3 flex-none rounded-sm"
                  style={{ backgroundColor: cls.color }}
                />
                {/* dir="ltr" is load-bearing under RTL: a range is two LTR
                    runs around a dash, and the Arabic paragraph direction
                    reorders them, so "0.20 – 0.40" renders as
                    "0.40 – 0.20" — a different, wrong claim. */}
                <span
                  dir="ltr"
                  className="w-[74px] flex-none text-start text-meta tabular-nums text-ap-muted"
                >
                  {formatRange(lo, cls.max, num)}
                </span>
                <span className="min-w-0 flex-1 truncate text-meta text-ap-ink">
                  {t(`farmConsole:legend.class.${vocab}.${cls.key}`)}
                  {hint?.classKey === cls.key ? (
                    <span className="ms-1 text-ap-accent">
                      · {t("farmConsole:legend.hint", { index: hint.suggest })}
                    </span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>

          {isThermalIndex(code) || READ_RELATIVELY.has(code) ? (
            <div className="flex flex-col gap-1 border-t border-ap-line bg-ap-bg/60 px-3 py-1.5">
              {isThermalIndex(code) ? (
                <span className="text-meta leading-snug text-ap-muted">
                  {t("farmConsole:legend.thermalCaveat", {
                    metres: THERMAL_NATIVE_RESOLUTION_M,
                  })}
                </span>
              ) : null}
              {READ_RELATIVELY.has(code) ? (
                <span className="text-meta leading-snug text-ap-muted">
                  {t("farmConsole:legend.relativeCaveat")}
                </span>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}
