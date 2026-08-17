// The index legend — what the colours on the map mean, and how much land is
// in each of them.
//
// Three things distinguish it from a colour ramp with numbers on it:
//   * every class carries an AREA in the user's unit, because "24.1 feddan
//     very sparse" is the sentence someone acts on;
//   * the swatches ARE the colours painted on the ground — both come from
//     indexClasses.ts, one as a TiTiler interval colormap and one as these
//     rows, so the legend cannot drift from the pixels it describes;
//   * when there is nothing to measure it says WHY, in one compact line,
//     rather than rendering an empty 300px panel that reads as broken.
//
// The areas are counted from PIXELS inside the current block boundary. They
// used to be summed from sub-block cell aggregates, which reported 205.0
// feddan of land on a 164.9-feddan farm: two blocks' grids had been
// materialised against older, larger boundaries and never regenerated, and
// the legend faithfully added up geometry that no longer existed.
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { AnyIndexCode as ApiIndexCode } from "@/api/indices";
import { Card } from "@/components/Card";
import { indexDecimals } from "@/lib/indexFormat";
import { THERMAL_NATIVE_RESOLUTION_M } from "@/lib/thermalResolution";
import { formatAreaValue, m2ToUnit } from "@/lib/units";
import { usePrefs } from "@/prefs/PrefsContext";
import { INDEX_META, isThermalIndex } from "../mapnext/constants";
import {
  CLASS_HINT,
  CLASS_VOCAB,
  classesFor,
  formatRange,
  lowerBound,
  NO_DATA_COLOR,
  READ_RELATIVELY,
} from "./indexClasses";
import type { ClassAreaSummary } from "./pixelTiles";

interface Props {
  code: ApiIndexCode;
  /** Per-class areas for the current scope; undefined while loading. */
  areas: ClassAreaSummary | undefined;
  /** Narrow the totals to one block, or null for the whole farm. */
  scopeBlockId: string | null;
  scopeBlockName: string | null;
  /** Whether the pixel layer is switched on at all. */
  showPixels: boolean;
  /** Blocks carrying an index raster for the selected scene. */
  assetCount: number;
  /** Active imagery subscriptions across the farm; null while unknown. */
  imagerySubCount: number | null;
  loading: boolean;
  /**
   * The index's display unit from `public.indices_catalog` — `°C` for `lst`,
   * empty for the dimensionless rest.
   *
   * A prop rather than a query of this component's own: the legend fetches
   * nothing else, and the catalog is platform-wide curated data the console
   * already reads once and caches for every farm and index the reader visits.
   * Not hardcoded either — a local code-to-unit table is exactly the mirror
   * that drifted and left `ndmi` uncheckable in Insights for a year.
   */
  indexUnit?: string;
  onOpenImagerySettings?: () => void;
  className?: string;
}

export function IndexLegend({
  code,
  areas,
  scopeBlockId,
  scopeBlockName,
  showPixels,
  assetCount,
  imagerySubCount,
  loading,
  indexUnit = "",
  onOpenImagerySettings,
  className,
}: Props): ReactNode {
  const { t, i18n } = useTranslation(["farmConsole", "farms"]);
  const { unit } = usePrefs();
  const [collapsed, setCollapsed] = useState(false);

  const classes = classesFor(code);
  const vocab = CLASS_VOCAB[code];
  const hint = CLASS_HINT[code];

  const area = (m2: number): string =>
    formatAreaValue(m2ToUnit(m2, unit), { locale: i18n.language, fractionDigits: 1 });
  const unitLabel = t(`farms:area.${unit}`);

  // Class boundaries at the precision the reading carries.
  //
  // Two decimals for the dimensionless indices, which is what these rows have
  // always shown and is exactly right for boundaries that are round numbers
  // like 0.20 and 0.40 — `indexFormat`'s three is for a CHART VALUE, where the
  // extra digit is real, and a third zero here would be noise on ten legends.
  // A unit overrides it: `20.00 – 30.00 °C` off a sensor whose native pixel is
  // 100 m across is false precision wearing the shape of rigour.
  const LEGEND_DIMENSIONLESS_DECIMALS = 2;
  const num = (n: number): string =>
    n.toFixed(indexUnit ? indexDecimals(indexUnit) : LEGEND_DIMENSIONLESS_DECIMALS);

  const scopeLabel =
    scopeBlockId && scopeBlockName
      ? t("farmConsole:legend.scopeBlock", { name: scopeBlockName })
      : t("farmConsole:legend.scopeFarm");

  const header = (
    <div className="flex items-center gap-2">
      <span className="text-card-title font-bold text-ap-ink">{INDEX_META[code].label}</span>
      {/* The unit sits here rather than on every row: a range column repeating
          "°C" six times says nothing the heading cannot say once, and the
          column is too narrow to carry it without truncating the numbers. */}
      {indexUnit ? (
        <span dir="ltr" className="text-meta font-semibold text-ap-muted">
          {indexUnit}
        </span>
      ) : null}
      <span className="text-meta text-ap-muted">
        {t(`farmConsole:dock.family.${INDEX_META[code].family}`)}
      </span>
    </div>
  );

  const toggle = (
    <button
      type="button"
      onClick={() => setCollapsed((v) => !v)}
      aria-expanded={!collapsed}
      title={collapsed ? t("farmConsole:legend.expand") : t("farmConsole:legend.collapse")}
      className="grid h-6 w-6 place-items-center rounded-md text-ap-muted hover:bg-ap-bg"
    >
      {collapsed ? "▴" : "▾"}
    </button>
  );

  // ---- nothing to measure: say which reason it is ------------------------
  const diagnostic = pickDiagnostic({ assetCount, imagerySubCount, loading });
  if (diagnostic) {
    return (
      <Card className={className} title={header} actions={toggle} noPadding>
        {collapsed ? null : (
          <div className="px-3 py-2.5">
            <p className="text-meta font-semibold text-ap-ink">
              {t(`farmConsole:legend.${diagnostic.titleKey}`)}
            </p>
            <p className="mt-0.5 text-meta leading-snug text-ap-muted">
              {t(`farmConsole:legend.${diagnostic.bodyKey}`)}
            </p>
            {diagnostic.ctaKey && onOpenImagerySettings ? (
              <button
                type="button"
                onClick={onOpenImagerySettings}
                className="mt-1.5 text-meta font-semibold text-ap-primary underline"
              >
                {t(`farmConsole:legend.${diagnostic.ctaKey}`)}
              </button>
            ) : null}
          </div>
        )}
      </Card>
    );
  }

  // Highest VALUE first, so the range column reads monotonically downward
  // whichever index is on. That is not the same as "best first": NDWI's scale
  // is inverted, so its healthy end sits at the BOTTOM of the panel while its
  // colours still run red-for-bad. The numbers and the colours each stay
  // self-consistent; conflating them is what made the old ramp wrong.
  const rows = classes
    .map((cls, i) => ({ cls, lo: lowerBound(code, i), areaM2: areas?.areaM2ByClass[i] ?? 0 }))
    .reverse();

  return (
    <Card className={className} title={header} actions={toggle} noPadding>
      {collapsed ? null : (
        <>
          <div className="flex items-center justify-between gap-2 border-b border-ap-line px-3 py-1.5">
            <span className="text-meta text-ap-muted">{scopeLabel}</span>
            <span className="text-meta font-semibold text-ap-muted">
              {t("farmConsole:legend.areaHeader")} · {unitLabel}
            </span>
          </div>

          <ul className="max-h-56 overflow-auto py-0.5">
            {rows.map(({ cls, lo, areaM2 }) => {
              const showHint = hint?.classKey === cls.key;
              return (
                <li key={cls.key} className="flex items-center gap-2 px-3 py-[3px]">
                  <span
                    aria-hidden="true"
                    className="h-3 w-3 flex-none rounded-sm"
                    style={{ backgroundColor: cls.color }}
                  />
                  {/* dir="ltr" is load-bearing under RTL: a range is two
                      LTR runs around a dash, and the Arabic paragraph
                      direction reorders them, so "0.20 – 0.40" renders as
                      "0.40 – 0.20" — a different, wrong claim. */}
                  <span
                    dir="ltr"
                    className="w-[74px] flex-none text-start text-meta tabular-nums text-ap-muted"
                  >
                    {formatRange(lo, cls.max, num)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-meta text-ap-ink">
                    {t(`farmConsole:legend.class.${vocab}.${cls.key}`)}
                    {showHint ? (
                      <span className="ms-1 text-ap-accent">
                        · {t("farmConsole:legend.hint", { index: hint.suggest })}
                      </span>
                    ) : null}
                  </span>
                  <span
                    className={
                      "flex-none text-meta font-semibold tabular-nums " +
                      (areaM2 > 0 ? "text-ap-ink" : "text-ap-muted/60")
                    }
                  >
                    {area(areaM2)}
                  </span>
                </li>
              );
            })}
          </ul>

          <div className="flex flex-col gap-1 border-t border-ap-line bg-ap-bg/60 px-3 py-1.5">
            <div className="flex items-center gap-3">
              <span className="text-meta text-ap-muted">
                {t("farmConsole:legend.covered")}{" "}
                <b className="tabular-nums text-ap-ink">{area(areas?.coveredM2 ?? 0)}</b>
              </span>
              {areas && areas.noDataM2 > 0 ? (
                <span className="text-meta text-ap-muted" title={t("farmConsole:legend.noDataHint")}>
                  <span
                    aria-hidden="true"
                    className="me-1 inline-block h-2 w-2 rounded-sm align-middle"
                    style={{ backgroundColor: NO_DATA_COLOR }}
                  />
                  {t("farmConsole:legend.noData")}{" "}
                  <b className="tabular-nums text-ap-ink">{area(areas.noDataM2)}</b>
                </span>
              ) : null}
            </div>
            {/* Two things the reader is owed, stated rather than implied. */}
            {!showPixels ? (
              <span className="text-meta leading-snug text-ap-muted">
                {t("farmConsole:legend.pixelsOffNote")}
              </span>
            ) : null}
            {/* Resolution first, then the relative caveat. A thermal reading
                carries BOTH — its scale is provisional AND its pixel is 100 m
                across, which is larger than most blocks on this farm. Saying
                only the second would let a reader trust the shape of the map
                at a detail the sensor cannot resolve. */}
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
        </>
      )}
    </Card>
  );
}

interface Diagnostic {
  titleKey: string;
  bodyKey: string;
  ctaKey?: string;
}

/**
 * Which "nothing to show" reason applies, from the most specific cause to the
 * least, so the message names the thing the user would actually have to fix
 * rather than the symptom nearest the surface.
 *
 * Note what is NOT a reason any more: the pixel layer being switched off. The
 * classes and their areas still describe the block fills, which paint the same
 * classes — so the panel keeps working and merely says so in its footer.
 */
function pickDiagnostic({
  assetCount,
  imagerySubCount,
  loading,
}: {
  assetCount: number;
  imagerySubCount: number | null;
  loading: boolean;
}): Diagnostic | null {
  if (assetCount === 0) {
    if (loading || imagerySubCount === null) return null;
    // No imagery anywhere is the upstream cause: there is no raster to read
    // without a subscription, so saying "no imagery for this date" would send
    // the user scrubbing a timeline that can never help them.
    if (imagerySubCount === 0) {
      return {
        titleKey: "emptyNoSubsTitle",
        bodyKey: "emptyNoSubsBody",
        ctaKey: "emptyNoSubsCta",
      };
    }
    return { titleKey: "emptyNoSceneTitle", bodyKey: "emptyNoSceneBody" };
  }
  return null;
}
