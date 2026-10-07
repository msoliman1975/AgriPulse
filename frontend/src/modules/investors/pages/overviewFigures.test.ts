import { describe, expect, it } from "vitest";

import type { FarmHoldingsMap, FarmInvestor, Holding } from "@/api/investors";
import { overviewFigures } from "./InvestmentsOverviewPage";

function holding(over: Partial<Holding> & { id: string; block_id: string }): Holding {
  return {
    code: over.id.toUpperCase(),
    name: over.id,
    name_ar: null,
    area_m2: "1000",
    status: "available",
    tree_count: null,
    current_owner: null,
    archived_at: null,
    block_code: over.block_id,
    ...over,
  } as unknown as Holding;
}

function owner(investorId: string, since: string): Holding["current_owner"] {
  return {
    ownership_id: `o-${investorId}-${since}`,
    investor_id: investorId,
    investor_code: investorId,
    investor_name: investorId,
    investor_name_ar: null,
    since,
    other_farm_holdings: 0,
  };
}

function investor(id: string, here: number): FarmInvestor {
  return {
    id,
    code: id,
    full_name: id,
    full_name_ar: null,
    status: "not_invited",
    archived_at: null,
    holdings_in_farm: here,
    area_in_farm_m2: "0",
    other_farms: 0,
    other_farm_holdings: 0,
  } as unknown as FarmInvestor;
}

const map = {
  farm_id: "f",
  blocks: [
    { id: "b1", code: "B1", area_m2: "10000", eligible: true },
    { id: "b2", code: "B2", area_m2: "10000", eligible: true },
    { id: "b3", code: "B3", area_m2: "10000", eligible: true },
    // A pivot split into sectors: its area is not land a holding can sit on.
    { id: "p", code: "P", area_m2: "50000", eligible: false },
  ],
  holdings: [
    holding({
      id: "h1",
      block_id: "b1",
      area_m2: "2000",
      tree_count: 40,
      current_owner: owner("A", "2026-03-01"),
    }),
    holding({
      id: "h2",
      block_id: "b1",
      area_m2: "1000",
      tree_count: null,
      current_owner: owner("A", "2026-01-15"),
    }),
    holding({
      id: "h3",
      block_id: "b2",
      area_m2: "3000",
      tree_count: 60,
      current_owner: owner("B", "2026-02-01"),
    }),
    holding({ id: "h4", block_id: "b2", area_m2: "1500", status: "available", tree_count: 20 }),
    holding({ id: "h5", block_id: "b2", area_m2: "500", status: "draft" }),
  ],
} as unknown as FarmHoldingsMap;

describe("overviewFigures", () => {
  const f = overviewFigures(map, [investor("A", 2), investor("B", 1), investor("C", 0)]);

  it("splits the eligible block area by holding status", () => {
    expect(f.blockArea).toBe(30000);
    expect(f.areaSold).toBe(6000);
    expect(f.areaForSale).toBe(1500);
    expect(f.areaDraft).toBe(500);
    expect(f.areaUndrawn).toBe(22000);
  });

  it("lists owners by area, with their earliest start and typed trees", () => {
    expect(f.owners.map((o) => o.investor.id)).toEqual(["A", "B"]);
    // A tie on area (3000 each) keeps the investor list's order.
    const a = f.owners[0];
    expect(a.holdings.map((h) => h.id)).toEqual(["h1", "h2"]);
    expect(a.since).toBe("2026-01-15");
    expect(a.trees).toBe(40);
    expect(f.withoutHolding.map((i) => i.id)).toEqual(["C"]);
  });

  it("counts holdings per block and the blocks with none", () => {
    expect(f.blocks.map((b) => [b.code, b.holdings, b.sold, b.forSale, b.draft])).toEqual([
      ["B1", 2, 2, 0, 0],
      ["B2", 3, 1, 1, 1],
    ]);
    expect(f.blocksWithout).toBe(1);
  });
});
