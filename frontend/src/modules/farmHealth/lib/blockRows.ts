// Turning one farm's verdicts into the rows of the left rail.
//
// Pure on purpose. The rail's rules — which blocks appear, in what order,
// and what each one counts — are the part that can be wrong without
// anything throwing, so they are tested directly rather than through a
// render.

import type { BlockVerdicts, StatusCode, StatusDefinition, Verdict } from "@/api/farmHealth";

/** Worst first. The order the rail sorts by and the legend lists. */
export const STATUS_ORDER: StatusCode[] = ["alert", "issue", "good", "very_good", "na"];

export interface BlockRow {
  blockId: string;
  code: string;
  name: string;
  crop: string | null;
  /**
   * The worst status across this block's verdicts for the selected tree.
   * Null means no verdict row exists, which means the tree did not run
   * here — not that it ran and found nothing.
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

    let worst: StatusCode | null = null;
    for (const status of STATUS_ORDER) {
      if (counts[status] > 0) {
        worst = status;
        break;
      }
    }

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
