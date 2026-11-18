import type { BetaLayoutResult } from "./betaLayout";

/** One depth of the tree, as a horizontal band in canvas units. */
export interface LevelBand {
  depth: number;
  count: number;
  top: number;
  bottom: number;
}

/**
 * The bands the level overlay draws: one per depth, spanning its nodes.
 * A hand-placed node still counts toward its own depth, so a dragged node can
 * stretch its band; the label and count stay right.
 */
export function levelBands(layout: BetaLayoutResult): LevelBand[] {
  const byDepth = new Map<number, LevelBand>();
  for (const n of layout.nodes) {
    const band = byDepth.get(n.depth);
    if (band) {
      band.count += 1;
      band.top = Math.min(band.top, n.y);
      band.bottom = Math.max(band.bottom, n.y + n.height);
    } else {
      byDepth.set(n.depth, { depth: n.depth, count: 1, top: n.y, bottom: n.y + n.height });
    }
  }
  return [...byDepth.values()].sort((a, b) => a.depth - b.depth);
}
