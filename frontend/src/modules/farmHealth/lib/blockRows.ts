// Turning one farm's verdicts into the rows of the left rail.
//
// Pure on purpose. The rail's rules — which blocks appear, in what order,
// and what each one counts — are the part that can be wrong without
// anything throwing, so they are tested directly rather than through a
// render.

import type { BlockVerdicts, StatusCode, StatusDefinition, Verdict } from "@/api/farmHealth";

/**
 * The picker value that shows every tree at once. Not a tree code: a code is
 * lower snake case and cannot start with an underscore.
 */
export const ALL_TREES = "__all__";

/** Worst first. The order the rail sorts by and the legend lists. */
export const STATUS_ORDER: StatusCode[] = ["alert", "issue", "good", "very_good", "na"];

export interface BlockRow {
  blockId: string;
  code: string;
  name: string;
  crop: string | null;
  /**
   * The status the block reads as for the selected tree or trees: its
   * cells rolled up by the block-health rule (`rollUp`), and never milder
   * than a whole-block verdict. Under the default rule that is the worst
   * status. Null means no verdict row exists, which means the tree did not
   * run here — not that it ran and found nothing.
   */
  worst: StatusCode | null;
  /** How many verdicts hold each status. Empty when the tree did not run. */
  counts: Record<StatusCode, number>;
  /** Verdicts for the selected tree, block-scoped and cell-scoped alike. */
  verdicts: Verdict[];
  /** True when no verdict row exists for this block and tree. */
  didNotRun: boolean;
}

/** A block as the farm read knows it, plus whatever the blocks list adds. */
export interface BlockMeta {
  id: string;
  code: string;
  name?: string | null;
  crop_name?: string | null;
}

function emptyCounts(): Record<StatusCode, number> {
  return { alert: 0, issue: 0, good: 0, very_good: 0, na: 0 };
}

/** Rank a status by the platform list, falling back to the fixed order. */
export function rankOf(status: StatusCode, statuses: StatusDefinition[]): number {
  const found = statuses.find((s) => s.code === status);
  if (found) return found.rank;
  // The fixed order runs worst first, so invert it into a rank.
  const index = STATUS_ORDER.indexOf(status);
  return index < 0 ? 0 : STATUS_ORDER.length - index;
}

/**
 * The rail's rows for one tree, worst first.
 *
 * Every block in `blocks` gets a row, including the ones the farm read
 * omitted. That is deliberate: the farm read leaves out a block no tree ran
 * on, and dropping it from the rail too would hide the very state the
 * screen exists to make visible. Such a row carries `didNotRun`.
 */
export function buildBlockRows(
  blocks: BlockMeta[],
  farmBlocks: BlockVerdicts[],
  treeCode: string | null,
  statuses: StatusDefinition[],
  rules: ReadonlyMap<string, CellRule> = new Map(),
): BlockRow[] {
  const byBlock = new Map<string, BlockVerdicts>();
  for (const entry of farmBlocks) byBlock.set(entry.block_id, entry);

  const rows: BlockRow[] = blocks.map((block) => {
    const entry = byBlock.get(block.id);
    const verdicts = (entry?.verdicts ?? []).filter(
      (v) => treeCode === null || v.tree_code === treeCode,
    );
    const counts = emptyCounts();
    for (const verdict of verdicts) counts[verdict.status_code] += 1;

    const worst = rollUp(verdicts, rules.get(block.id) ?? DEFAULT_RULE);

    return {
      blockId: block.id,
      code: block.code,
      name: block.name ?? block.code,
      crop: block.crop_name ?? null,
      worst,
      counts,
      verdicts,
      didNotRun: verdicts.length === 0,
    };
  });

  // Worst first; a block the tree did not run on sorts last, because it is
  // an absence rather than a reading. Ties break on the code so the order
  // does not shuffle between frames of a replay.
  return rows.sort((a, z) => {
    const ar = a.worst === null ? -1 : rankOf(a.worst, statuses);
    const zr = z.worst === null ? -1 : rankOf(z.worst, statuses);
    if (ar !== zr) return zr - ar;
    return a.code.localeCompare(z.code);
  });
}

/** How a block's cells make one status. Sent per block by the farm read. */
export interface CellRule {
  rule: "worst" | "share" | "most_common";
  /** The fraction `share` reads. Ignored by the other two rules. */
  share: number | null;
}

export const DEFAULT_RULE: CellRule = { rule: "worst", share: null };

const RANK: Record<StatusCode, number> = { na: 0, very_good: 1, good: 2, issue: 3, alert: 4 };

/** The rule each block of a farm read carries. Absent blocks use the default. */
export function rulesFrom(farmBlocks: BlockVerdicts[]): Map<string, CellRule> {
  return new Map(
    farmBlocks.map((b) => [
      b.block_id,
      { rule: b.cell_rollup ?? "worst", share: b.cell_share ?? null },
    ]),
  );
}

/**
 * One status for a block, from its verdicts, by the block-health rule.
 *
 * The same steps as `_from_rolled_verdicts` and `_roll_cells` in
 * `backend/app/shared/health_definition.py`, so the colour on this map and
 * the class in Farm Management come from one rule:
 *
 *   1. each cell takes the worst status any tree gave it;
 *   2. the cells roll up: `worst` takes the worst cell; `share` takes the
 *      worst status that, counting worse ones, covers at least `share` of
 *      the cells (20% when none is given); `most_common` takes the status
 *      on the most cells, and a tie goes to the worse one;
 *   3. a whole-block verdict counts in full, so the block is never milder
 *      than one.
 */
export function rollUp(verdicts: Verdict[], rule: CellRule): StatusCode | null {
  if (verdicts.length === 0) return null;
  const perCell = new Map<string, StatusCode>();
  const candidates: StatusCode[] = [];
  for (const v of verdicts) {
    if (v.cell_id === null) {
      candidates.push(v.status_code);
      continue;
    }
    const seen = perCell.get(v.cell_id);
    if (seen === undefined || RANK[v.status_code] > RANK[seen])
      perCell.set(v.cell_id, v.status_code);
  }
  const cells = [...perCell.values()];
  if (cells.length > 0) candidates.push(rollCells(cells, rule));
  return candidates.reduce((a, z) => (RANK[z] > RANK[a] ? z : a));
}

function rollCells(cells: StatusCode[], rule: CellRule): StatusCode {
  if (rule.rule === "most_common") {
    const counts = new Map<StatusCode, number>();
    for (const c of cells) counts.set(c, (counts.get(c) ?? 0) + 1);
    let best: StatusCode = cells[0];
    for (const [code, n] of counts) {
      const bn = counts.get(best) ?? 0;
      if (n > bn || (n === bn && RANK[code] > RANK[best])) best = code;
    }
    return best;
  }
  const ordered = [...new Set(cells)].sort((a, z) => RANK[z] - RANK[a]);
  if (rule.rule === "worst") return ordered[0];
  const share = rule.share ?? 0.2;
  for (const code of ordered) {
    const atOrWorse = cells.filter((c) => RANK[c] >= RANK[code]).length;
    if (atOrWorse / cells.length >= share) return code;
  }
  return ordered[ordered.length - 1];
}

/** One entry of the tree picker: the code it selects by, the name it shows. */
export interface TreeOption {
  code: string;
  count: number;
  /** The tree's own name in the reader's language, or the code when it has none. */
  label: string;
}

/**
 * The tree's name for a reader, chosen and never translated.
 *
 * The name belongs to the tree's author, so Arabic falls back to the English
 * name rather than to a translation of it, and both fall back to the code:
 * an older API sends no name at all, and a verdict outlives the catalog row
 * that holds one.
 */
export function treeLabel(
  verdict: { tree_code: string; tree_name_en?: string | null; tree_name_ar?: string | null },
  arabic: boolean,
): string {
  const chosen = arabic ? (verdict.tree_name_ar ?? verdict.tree_name_en) : verdict.tree_name_en;
  return (chosen ?? "").trim() || verdict.tree_code;
}

/**
 * Every tree that has said something about this farm.
 *
 * The picker lists these rather than every published tree: a tree with no
 * verdict on this farm would paint an entirely blank map, and the reader
 * cannot tell that from a broken screen.
 *
 * Sorted by the name a reader sees, not by the code behind it. A list sorted
 * by code reads as unsorted once the codes are hidden, and it would reorder
 * itself when the language changes.
 */
export function treeOptions(farmBlocks: BlockVerdicts[], arabic = false): TreeOption[] {
  const counts = new Map<string, number>();
  const labels = new Map<string, string>();
  for (const block of farmBlocks) {
    for (const verdict of block.verdicts) {
      counts.set(verdict.tree_code, (counts.get(verdict.tree_code) ?? 0) + 1);
      // First writer wins, and every verdict of one tree carries the same
      // name, so this is a lookup rather than a choice.
      if (!labels.has(verdict.tree_code)) {
        labels.set(verdict.tree_code, treeLabel(verdict, arabic));
      }
    }
  }
  return [...counts.entries()]
    .map(([code, count]) => ({ code, count, label: labels.get(code) ?? code }))
    .sort((a, z) => a.label.localeCompare(z.label) || a.code.localeCompare(z.code));
}
