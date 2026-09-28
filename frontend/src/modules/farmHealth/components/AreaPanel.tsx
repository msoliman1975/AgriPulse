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
import { treeLabel, type BlockRow } from "../lib/blockRows";

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
  /** True when the picker shows every tree at once. */
  allTrees?: boolean;
}

export function BlockSummary({ row, statuses, rows, cols, treeName, allTrees }: SummaryProps) {
  const { t, i18n } = useTranslation(["farmHealth"]);
  const arabic = i18n.language.startsWith("ar");
  const lookup = new Map(statuses.map((s) => [s.code, s]));
  const labelOf = (code: StatusCode | null): string => {
    const entry = lookup.get(code ?? "na");
    if (!entry) return code ?? "";
    return arabic ? (entry.label_ar ?? entry.label_en) : entry.label_en;
  };
  // Cells, not verdicts: with every tree shown, one cell holds one verdict
  // per tree, and "242 cells" on an 11x11 grid is plainly false.
  const total = new Set(row.verdicts.map((v) => v.cell_id ?? "block")).size;

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

      {/* The colour bar and its per-status counts stood here until
          2026-09-14. The rail on the left carries the same bar on every
          block's row, so under the map it was a second copy of an answer the
          reader already had, in the band the tree's own sentence needs. */}
      {row.didNotRun ? (
        <p className="mt-2 text-sm text-ap-muted">
          {allTrees
            ? t("farmHealth:block.noTreeRan")
            : t("farmHealth:block.didNotRun", { tree: treeName })}
        </p>
      ) : null}
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
}

/**
 * The selected area, its sentence, and why the tree said it.
 *
 * The reasoning sat behind a "Show how this was decided" button until
 * 2026-09-14. Mohamed asked for it always on: it is the answer the screen
 * exists to give, and a click stood between every reader and it.
 */
export function AreaDetail({ area, statuses, farmId, blockId }: DetailProps) {
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

      {area.verdicts.length > 1 ? (
        // Every tree at once: each tree's own sentence and its own walk, worst
        // first. One sentence for the area would pick one tree's words and
        // hide the rest, which is the opposite of why the view shows them all.
        <ul className="mt-2 flex flex-col divide-y divide-ap-line">
          {area.verdicts.map((verdict) => (
            <TreeVerdict
              key={verdict.id}
              verdict={verdict}
              statuses={statuses}
              farmId={farmId}
              blockId={blockId}
            />
          ))}
        </ul>
      ) : (
        <>
          {/* Full width on purpose. A narrow measure here cost height the
              reasoning below needs — Mohamed, 2026-09-07. */}
          <p className="mt-2 text-sm text-ap-ink">{text}</p>

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
        </>
      )}
    </div>
  );
}

/** One tree's answer about the cells of an area, in the all-trees view. */
function TreeVerdict({
  verdict,
  statuses,
  farmId,
  blockId,
}: {
  verdict: Verdict;
  statuses: StatusDefinition[];
  farmId: string;
  blockId: string;
}) {
  const { i18n } = useTranslation(["farmHealth"]);
  const arabic = i18n.language.startsWith("ar");
  const status = statuses.find((s) => s.code === verdict.status_code);
  const text = arabic ? (verdict.text_ar ?? verdict.text_en) : verdict.text_en;
  return (
    <li className="py-3 first:pt-0">
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="text-sm font-semibold text-ap-ink">{treeLabel(verdict, arabic)}</span>
        <span className="inline-flex items-center gap-1.5 text-sm text-ap-muted">
          <i
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ background: status?.color ?? "#9AA0A6" }}
          />
          {status ? (arabic ? (status.label_ar ?? status.label_en) : status.label_en) : ""}
        </span>
      </div>
      <p className="mt-1 text-sm text-ap-ink">{text}</p>
      <div className="mt-2">
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
    </li>
  );
}

interface BlockDetailProps {
  verdict: Verdict;
  statuses: StatusDefinition[];
  farmId: string;
  blockId: string;
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
export function BlockVerdictDetail({ verdict, statuses, farmId, blockId }: BlockDetailProps) {
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
    </section>
  );
}
