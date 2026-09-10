// The lower half of the screen: what the block reads as, then one area.
//
// Mohamed set this shape on 2026-09-07 — a block summary on top, and
// everything below it scoped to one selected area rather than a stack of
// every area at once.
//
// On 2026-09-10 he asked for one section rather than three. The block's
// colour bar, the whole-block sentence and the selected area were three
// separate cards, each with its own border and its own padding, and on a
// half-height panel that was three frames around about eight lines of text.
// So the parts below render as SECTIONS with no frame of their own, and
// `PanelSections` puts the single frame around them and rules a line between
// each.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { StatusCode, StatusDefinition, Verdict } from "@/api/farmHealth";
import { Card } from "@/components/Card";
import { Pill } from "@/components/Pill";
import type { Area } from "../lib/areas";
import { areaLabel } from "../lib/areaLabel";
import { Reasoning } from "./Reasoning";
import { STATUS_ORDER, treeLabel, type BlockRow } from "../lib/blockRows";

/**
 * The one frame around the block panel.
 *
 * `divide-y` rules the lines, so a section never has to know whether it is
 * first, last, or the only one on screen — which it cannot know: a block
 * tree writes one whole-block verdict and no areas, and a cell tree the
 * reverse.
 */
export function PanelSections({ children }: { children: ReactNode }) {
  return (
    <Card noPadding>
      <div className="divide-y divide-ap-line px-4 [&>*]:py-4">{children}</div>
    </Card>
  );
}

interface SummaryProps {
  row: BlockRow;
  statuses: StatusDefinition[];
  rows: number;
  cols: number;
  /** The tree's name, as the picker shows it. Never its code. */
  treeName: string | null;
}

export function BlockSummary({ row, statuses, rows, cols, treeName }: SummaryProps) {
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
    <section>
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-section-title font-semibold tabular-nums text-ap-ink">{row.code}</h2>
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
          {t("farmHealth:block.didNotRun", { tree: treeName })}
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
    </section>
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
  statuses: StatusDefinition[];
  farmId: string;
  blockId: string;
  /** Open by default is wrong: the reasoning is a follow-up question. */
  open: boolean;
  onToggle: () => void;
}

export function AreaDetail({ area, statuses, farmId, blockId, open, onToggle }: DetailProps) {
  const { t, i18n } = useTranslation(["farmHealth"]);
  const arabic = i18n.language.startsWith("ar");
  // The verdict text is the tree author's own sentence, so it is chosen
  // rather than translated.
  const text = arabic ? (area.sample.text_ar ?? area.sample.text_en) : area.sample.text_en;

  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <h3 className="text-section-title font-semibold text-ap-ink">
          {areaLabel(t, area.name, area.spots)}
        </h3>
        <span className="text-sm tabular-nums text-ap-muted">
          {t("farmHealth:area.cellCount", { count: area.cells.length })} ·{" "}
          {t("farmHealth:area.share", { share: area.share })}
        </span>
      </div>

      {/* Full width on purpose. A narrow measure here cost height the
          reasoning below needs — Mohamed, 2026-09-07. */}
      <p className="mt-2 text-sm text-ap-ink">{text}</p>

      <div className="mt-2">
        <button
          type="button"
          aria-expanded={open}
          onClick={onToggle}
          className="text-sm font-medium text-ap-accent underline underline-offset-4"
        >
          {open ? t("farmHealth:reasoning.hide") : t("farmHealth:reasoning.show")}
        </button>
      </div>

      {open ? (
        <div className="mt-3 border-t border-ap-line pt-3">
          <Reasoning
            blockId={blockId}
            verdictId={area.sample.id}
            farmId={farmId}
            leafNodeId={area.leafNodeId}
            kind={area.sample.kind}
            statusCode={area.status}
            statuses={statuses}
          />
        </div>
      ) : null}
    </div>
  );
}

interface BlockDetailProps {
  verdict: Verdict;
  statuses: StatusDefinition[];
  farmId: string;
  blockId: string;
  open: boolean;
  onToggle: () => void;
}

/**
 * A whole-block verdict, said in full.
 *
 * A block tree writes one verdict with no cell, so it produced no areas and
 * this card had no counterpart: the panel showed the colour bar, the words
 * "1 Good", and nothing else. The tree's own sentence and the walk behind it
 * were both in the payload already — the screen just never asked for them,
 * so "why is this block good" had no answer on the page that exists to say
 * why.
 */
export function BlockVerdictDetail({
  verdict,
  statuses,
  farmId,
  blockId,
  open,
  onToggle,
}: BlockDetailProps) {
  const { t, i18n } = useTranslation(["farmHealth"]);
  const arabic = i18n.language.startsWith("ar");
  const status = statuses.find((s) => s.code === verdict.status_code);
  // The verdict text is the tree author's own sentence, so it is chosen
  // rather than translated.
  const text = arabic ? (verdict.text_ar ?? verdict.text_en) : verdict.text_en;

  return (
    <section>
      <div className="flex flex-wrap items-baseline gap-3">
        <h3 className="text-section-title font-semibold text-ap-ink">
          {t("farmHealth:block.wholeBlock")}
        </h3>
        <span className="inline-flex items-center gap-1.5 text-sm text-ap-muted">
          <i
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ background: status?.color ?? "#9AA0A6" }}
          />
          {status ? (arabic ? (status.label_ar ?? status.label_en) : status.label_en) : ""}
        </span>
        {/* The tree's name, not its code. `t_mango_cwsi` put the plumbing on
            the line that names the author of the sentence below it. */}
        <span className="ms-auto text-meta text-ap-muted">
          {treeLabel(verdict, arabic)} · v{verdict.tree_version}
        </span>
      </div>

      <p className="mt-2 text-sm text-ap-ink">{text}</p>

      <div className="mt-2">
        <button
          type="button"
          aria-expanded={open}
          onClick={onToggle}
          className="text-sm font-medium text-ap-accent underline underline-offset-4"
        >
          {open ? t("farmHealth:reasoning.hide") : t("farmHealth:reasoning.show")}
        </button>
      </div>

      {open ? (
        <div className="mt-3 border-t border-ap-line pt-3">
          <Reasoning
            blockId={blockId}
            verdictId={verdict.id}
            farmId={farmId}
            leafNodeId={verdict.leaf_node_id}
            kind={verdict.kind}
            statusCode={verdict.status_code}
            statuses={statuses}
          />
        </div>
      ) : null}
    </section>
  );
}
