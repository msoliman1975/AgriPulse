// The index legend — what the colours on the map mean, and how much land is
// in each of them.
//
// Three things distinguish it from a colour ramp with numbers on it:
//   * every class carries an AREA in the user's unit, because "24.1 feddan
//     very sparse" is the sentence someone acts on;
//   * the swatches come from the map's own ramp table (map/gridRamp.ts), so
//     the legend cannot drift from the pixels it describes;
//   * when there is nothing to measure it says WHY, in one compact line,
//     rather than rendering an empty 300px panel that reads as broken.
//
// That last case is not an edge case. A farm with no imagery subscription on
// any block — which is the normal state of a newly onboarded tenant — has no
// grid, so this panel's headline feature has nothing to show. It is built
// first here for that reason.
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { IndexCode as ApiIndexCode } from "@/api/indices";
import { Card } from "@/components/Card";
import { formatAreaValue, m2ToUnit } from "@/lib/units";
import { usePrefs } from "@/prefs/PrefsContext";
import { HEALTH_DOT, INDEX_META } from "../mapnext/constants";
import {
  BAND_VOCAB,
  computeLegend,
  formatRange,
  LEGEND_HINT,
  type LegendGroup,
} from "./legendBins";

interface Props {
  /** Raw farm-grid groups; `undefined` while the query is idle or loading. */
  groups: readonly LegendGroup[] | undefined;
  code: ApiIndexCode;
  /** Narrow the totals to one block, or null for the whole farm. */
  scopeBlockId: string | null;
  scopeBlockName: string | null;
  /** Whether the grid overlay is switched on at all. */
  showGrid: boolean;
  /** How many blocks on this farm carry a sub-block grid. */
  griddedCount: number;
  /** Active imagery subscriptions across the farm; null while unknown. */
  imagerySubCount: number | null;
  loading: boolean;
  onOpenImagerySettings?: () => void;
  className?: string;
}

export function IndexLegend({
  groups,
  code,
  scopeBlockId,
  scopeBlockName,
  showGrid,
  griddedCount,
  imagerySubCount,
  loading,
  onOpenImagerySettings,
  className,
}: Props): ReactNode {
  const { t, i18n } = useTranslation(["farmConsole", "farms"]);
  const { unit } = usePrefs();
  const [collapsed, setCollapsed] = useState(false);

  const summary = computeLegend(groups, code, scopeBlockId);
  const vocab = BAND_VOCAB[code];
  const hint = LEGEND_HINT[code];

  const area = (m2: number): string =>
    formatAreaValue(m2ToUnit(m2, unit), { locale: i18n.language, fractionDigits: 1 });
  const unitLabel = t(`farms:area.${unit}`);
  const num = (n: number): string => n.toFixed(2);

  const scopeLabel =
    scopeBlockId && scopeBlockName
      ? t("farmConsole:legend.scopeBlock", { name: scopeBlockName })
      : t("farmConsole:legend.scopeFarm");

  const header = (
    <div className="flex items-center gap-2">
      <span className="text-card-title font-bold text-ap-ink">{INDEX_META[code].label}</span>
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

  // ---- nothing to measure: say which of the three reasons it is ----------
  const diagnostic = pickDiagnostic({ showGrid, griddedCount, imagerySubCount, loading });
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
            {summary.rows.map((row) => {
              const showHint = hint?.bandKey === row.key;
              return (
                <li key={row.key} className="flex items-center gap-2 px-3 py-[3px]">
                  <span
                    aria-hidden="true"
                    className="h-3 w-3 flex-none rounded-sm"
                    style={{ backgroundColor: row.color }}
                  />
                  <span className="w-[74px] flex-none text-meta tabular-nums text-ap-muted">
                    {formatRange(row, num)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-meta text-ap-ink">
                    {t(`farmConsole:legend.band.${vocab}.${row.key}`)}
                    {showHint ? (
                      <span className="ms-1 text-ap-accent">
                        · {t("farmConsole:legend.hint", { index: hint.suggest })}
                      </span>
                    ) : null}
                  </span>
                  <span
                    className={
                      "flex-none text-meta font-semibold tabular-nums " +
                      (row.areaM2 > 0 ? "text-ap-ink" : "text-ap-muted/60")
                    }
                  >
                    {area(row.areaM2)}
                  </span>
                </li>
              );
            })}
          </ul>

          <div className="flex items-center gap-3 border-t border-ap-line bg-ap-bg/60 px-3 py-1.5">
            <span className="text-meta text-ap-muted">
              {t("farmConsole:legend.covered")}{" "}
              <b className="tabular-nums text-ap-ink">{area(summary.coveredM2)}</b>
            </span>
            {summary.noDataM2 > 0 ? (
              <span className="text-meta text-ap-muted" title={t("farmConsole:legend.noDataHint")}>
                <span
                  aria-hidden="true"
                  className="me-1 inline-block h-2 w-2 rounded-sm align-middle"
                  style={{ backgroundColor: HEALTH_DOT.unknown }}
                />
                {t("farmConsole:legend.noData")}{" "}
                <b className="tabular-nums text-ap-ink">{area(summary.noDataM2)}</b>
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
 * Which of the three "nothing to show" reasons applies. Ordered from the most
 * specific cause to the least, so the message names the thing the user would
 * actually have to fix rather than the symptom nearest the surface.
 */
function pickDiagnostic({
  showGrid,
  griddedCount,
  imagerySubCount,
  loading,
}: {
  showGrid: boolean;
  griddedCount: number;
  imagerySubCount: number | null;
  loading: boolean;
}): Diagnostic | null {
  if (griddedCount === 0) {
    // No imagery anywhere is the upstream cause: a grid cannot be computed
    // without a subscription, so saying "configure a grid" would send the
    // user to a screen that cannot help them yet.
    if (imagerySubCount === 0) {
      return {
        titleKey: "emptyNoSubsTitle",
        bodyKey: "emptyNoSubsBody",
        ctaKey: "emptyNoSubsCta",
      };
    }
    return {
      titleKey: "emptyNoGridTitle",
      bodyKey: "emptyNoGridBody",
      ctaKey: "emptyNoGridCta",
    };
  }
  if (!showGrid) return { titleKey: "emptyOffTitle", bodyKey: "emptyOffBody" };
  // Grid is on and blocks are zoned — the rows simply have not arrived yet.
  if (loading) return null;
  return null;
}
