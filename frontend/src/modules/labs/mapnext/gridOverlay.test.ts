import { describe, expect, it } from "vitest";

import type { Block } from "@/api/blocks";
import type { UnitSummary } from "@/modules/labs/map/types";

import { griddedBlocks } from "./gridOverlay";

// The map turns its sub-block grid on by default when the farm has any zoning,
// which means this runs on every console load rather than only when someone
// opens the Layers popover. What it must not do is send the page hunting
// through every block to find that out.

const block = (id: string): Block => ({ id }) as Block;

const summary = (id: string, gridProductId: string | null): UnitSummary =>
  ({
    id,
    health: "unknown",
    has_alert: false,
    alert_severity: null,
    alert_count: 0,
    ndvi_current: null,
    ndre_current: null,
    ndwi_current: null,
    grid_product_id: gridProductId,
  }) as UnitSummary;

describe("griddedBlocks", () => {
  it("returns the gridded blocks with the product each is zoned against", () => {
    const blocks = [block("b1"), block("b2"), block("b3")];
    const summaries = {
      b1: summary("b1", "p1"),
      b2: summary("b2", null),
      b3: summary("b3", "p2"),
    };
    expect(griddedBlocks(blocks, summaries)).toEqual([
      { blockId: "b1", productId: "p1" },
      { blockId: "b3", productId: "p2" },
    ]);
  });

  it("is empty for a farm with no zoning, which is what keeps the overlay off", () => {
    const blocks = [block("b1"), block("b2")];
    const summaries = { b1: summary("b1", null), b2: summary("b2", null) };
    expect(griddedBlocks(blocks, summaries)).toEqual([]);
  });

  it("finds a single gridded block among many — one is enough to show the grid", () => {
    const blocks = Array.from({ length: 12 }, (_, i) => block(`b${i}`));
    const summaries: Record<string, UnitSummary> = {};
    for (const b of blocks) summaries[b.id] = summary(b.id, null);
    summaries.b7 = summary("b7", "p1");
    expect(griddedBlocks(blocks, summaries)).toEqual([{ blockId: "b7", productId: "p1" }]);
  });

  it("skips a block the summary has no row for rather than guessing", () => {
    // A block can be missing from the summary (added mid-poll); assuming it
    // is gridded would send a cells request that 404s on every refetch.
    expect(griddedBlocks([block("b1")], {})).toEqual([]);
    expect(griddedBlocks(undefined, undefined)).toEqual([]);
  });
});
