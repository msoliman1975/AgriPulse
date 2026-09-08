// The lower half of the screen: what the block reads as, then one area.
//
// Mohamed set this shape on 2026-09-07 — a block summary on top, and
// everything below it scoped to one selected area rather than a stack of
// every area at once.

import { useTranslation } from "react-i18next";

import type { StatusCode, StatusDefinition } from "@/api/farmHealth";
import { Card } from "@/components/Card";
import { Pill } from "@/components/Pill";
import type { Area } from "../lib/areas";
import { areaLabel } from "../lib/areaLabel";
import { STATUS_ORDER, type BlockRow } from "../lib/blockRows";

interface SummaryProps {
  row: BlockRow;
  statuses: StatusDefinition[];
  rows: number;
  cols: number;
  treeCode: string | null;
}

export function BlockSummary({ row, statuses, rows, cols, treeCode }: SummaryProps) {
  const { t, i18n } = useTranslation(["farmHealth"]);
  const arabic = i18n.language.startsWith("ar");
  const lookup = new Map(statuses.map((s) => [s.code, s]));
  const labelOf = (code: StatusCode | null): string => {
    const entry = lookup.get(code ?? "na");
    if (!entry) return code ?? "";
    return arabic ? (entry.label_ar ?? entry.label_en) : entry.label_en;
  };
  const total = row.verdicts.length;

  return (
    <Card>
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-section-title font-semibold tabular-nums text-ap-ink">
          {row.code}
        </h2>
        {rows > 0 && cols > 0 ? (
          <span className="text-sm text-ap-muted">
            {t("farmHealth:summary.grid", { rows, cols, count: total })}
          </span>
        ) : null}
        <span className="ms-auto flex items-center gap-2">
          <span className="text-meta font-semibold uppercase tracking-wide text-ap-muted">
            {t("farmHealth:summary.reads")}
          </span>
          {row.didNotRun ? (
            <span className="inline-flex items-center rounded-full border border-dashed border-ap-line px-2 py-0.5 text-meta text-ap-muted">
              {t("farmHealth:summary.didNotRun")}
            </span>
          ) : (
            <Pill kind="neutral">{labelOf(row.worst)}</Pill>
          )}
        </span>
      </div>

      {row.didNotRun ? (
        <p className="mt-2 text-sm text-ap-muted">
          {t("farmHealth:block.didNotRun", { tree: treeCode })}
        </p>
      ) : (
        <>
          <div className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-ap-line">
            {STATUS_ORDER.filter((code) => row.counts[code] > 0).map((code) => (
              <span
                key={code}
                className="block"
                style={{
                  width: `${(100 * row.counts[code]) / Math.max(1, total)}%`,
                  background: lookup.get(code)?.color ?? "#9AA0A6",
                }}
              />
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-4 text-meta text-ap-muted">
            {STATUS_ORDER.filter((code) => row.counts[code] > 0).map((code) => (
              <span key={code} className="inline-flex items-center gap-1.5">
                <i
                  className="inline-block h-2.5 w-2.5 rounded-sm"
                  style={{ background: lookup.get(code)?.color ?? "#9AA0A6" }}
                />
                <b className="font-semibold tabular-nums text-ap-ink">{row.counts[code]}</b>
                <span>{labelOf(code)}</span>
              </span>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

interface ChipsProps {
  areas: Area[];
  statuses: StatusDefinition[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  onHover: (key: string | null) => void;
}

export function AreaChips({ areas, statuses, selectedKey, onSelect, onHover }: ChipsProps) {
  const { t } = useTranslation(["farmHealth"]);
  const colorOf = new Map(statuses.map((s) => [s.code, s.color]));

  return (
    <div className="flex flex-wrap gap-1.5">
      {areas.map((area) => (
        <button
          key={area.key}
          type="button"
          aria-pressed={area.key === selectedKey}
          onClick={() => onSelect(area.key)}
          onMouseEnter={() => onHover(area.key)}
          onMouseLeave={() => onHover(null)}
          onFocus={() => onHover(area.key)}
          onBlur={() => onHover(null)}
          className={[
            "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm",
            area.key === selectedKey
              ? "border-ap-primary bg-ap-primary-soft text-ap-primary"
              : "border-ap-line bg-ap-panel hover:border-ap-primary",
          ].join(" ")}
        >
          <i
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ background: colorOf.get(area.status) ?? "#9AA0A6" }}
          />
          <span>{areaLabel(t, area.name, area.spots)}</span>
          <span className="text-meta tabular-nums text-ap-muted">
            {t("farmHealth:area.cellCount", { count: area.cells.length })}
          </span>
        </button>
      ))}
    </div>
  );
}

interface DetailProps {
  area: Area;
}

export function AreaDetail({ area }: DetailProps) {
  const { t } = useTranslation(["farmHealth"]);
  return (
    <Card>
      <div className="flex flex-wrap items-baseline gap-3">
        <h3 className="text-section-title font-semibold text-ap-ink">
          {areaLabel(t, area.name, area.spots)}
        </h3>
        <span className="text-sm tabular-nums text-ap-muted">
          {t("farmHealth:area.cellCount", { count: area.cells.length })} ·{" "}
          {t("farmHealth:area.share", { share: area.share })}
        </span>
      </div>
      {/* The reason sentence and the reasoning panel land here next. Until
          then the leaf's own text is what the area has to say. */}
      <p className="mt-2 max-w-none text-sm text-ap-ink">{area.sample.text_en}</p>
    </Card>
  );
}
