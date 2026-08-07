import type { Block } from "@/api/blocks";
import type { UnitSummary } from "@/modules/labs/map/types";

export interface GriddedBlock {
  blockId: string;
  productId: string;
}

/**
 * Which blocks in the farm carry a sub-block grid, and against which imagery
 * product, read straight off the map summary.
 *
 * This used to be discovered the expensive way: ask every block for its
 * imagery subscriptions, take the first, then ask for that block's cells —
 * two requests per block before a single cell could be drawn. That was
 * tolerable while the overlay was opt-in and lazy. It is not tolerable now
 * that the overlay comes up by default, and the same N+1 shape is what
 * exhausted the API's connection pool on this page once already.
 *
 * A block with no grid is simply absent, so an empty result is the signal
 * that the farm has no zoning and the overlay should stay off.
 */
export function griddedBlocks(
  blocks: readonly Block[] | undefined,
  summaries: Record<string, UnitSummary> | undefined,
): GriddedBlock[] {
  if (!blocks || !summaries) return [];
  const out: GriddedBlock[] = [];
  for (const b of blocks) {
    const productId = summaries[b.id]?.grid_product_id ?? null;
    if (productId) out.push({ blockId: b.id, productId });
  }
  return out;
}
