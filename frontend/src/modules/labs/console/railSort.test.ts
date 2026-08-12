import { describe, expect, it } from "vitest";

import type { Block } from "@/api/blocks";
import type { Health, UnitSummary } from "../map/types";
import { filterUnits, sortUnits, unitValue } from "./railSort";

function block(id: string, code: string, name?: string): Block {
  return { id, code, name: name ?? null } as Block;
}

function summary(
  id: string,
  opts: { health?: Health; alerts?: number; ndvi?: number | null } = {},
): UnitSummary {
  return {
    id,
    health: opts.health ?? "healthy",
    has_alert: (opts.alerts ?? 0) > 0,
    alert_severity: null,
    alert_count: opts.alerts ?? 0,
    ndvi_current: opts.ndvi ?? null,
    ndre_current: null,
    ndwi_current: null,
    grid_product_id: null,
  };
}

const names = (bs: Block[]): string[] => bs.map((b) => b.name ?? b.code);

describe("filterUnits", () => {
  const units = [block("1", "B-01", "North ridge"), block("2", "B-02", "Wadi"), block("3", "B-03")];

  it("returns everything for an empty or whitespace query", () => {
    expect(filterUnits(units, "")).toHaveLength(3);
    expect(filterUnits(units, "   ")).toHaveLength(3);
  });

  it("matches the display name case-insensitively", () => {
    expect(names(filterUnits(units, "NORTH"))).toEqual(["North ridge"]);
  });

  it("matches the code even when a name is set", () => {
    expect(filterUnits(units, "B-02")).toHaveLength(1);
  });

  it("falls back to the code as the display name when there is none", () => {
    expect(filterUnits(units, "b-03")).toHaveLength(1);
  });

  it("does not mutate its input", () => {
    const copy = [...units];
    filterUnits(units, "north");
    expect(units).toEqual(copy);
  });
});

describe("sortUnits", () => {
  const units = [
    block("1", "B-01", "Charlie"),
    block("2", "B-02", "Alpha"),
    block("3", "B-03", "Bravo"),
  ];

  it("sorts by name", () => {
    expect(names(sortUnits(units, {}, "name", "ndvi"))).toEqual(["Alpha", "Bravo", "Charlie"]);
  });

  it("sorts worst health first, with unknown above healthy", () => {
    const summaries = {
      "1": summary("1", { health: "healthy" }),
      "2": summary("2", { health: "critical" }),
      "3": summary("3", { health: "unknown" }),
    };
    expect(names(sortUnits(units, summaries, "health", "ndvi"))).toEqual([
      "Alpha", // critical
      "Bravo", // unknown
      "Charlie", // healthy
    ]);
  });

  it("sorts most alerts first", () => {
    const summaries = {
      "1": summary("1", { alerts: 1 }),
      "2": summary("2", { alerts: 0 }),
      "3": summary("3", { alerts: 5 }),
    };
    expect(names(sortUnits(units, summaries, "alerts", "ndvi"))).toEqual([
      "Bravo",
      "Charlie",
      "Alpha",
    ]);
  });

  it("sorts lowest index value first and sinks blocks with no reading", () => {
    const summaries = {
      "1": summary("1", { ndvi: 0.5 }),
      "2": summary("2", { ndvi: null }),
      "3": summary("3", { ndvi: 0.2 }),
    };
    expect(names(sortUnits(units, summaries, "value", "ndvi"))).toEqual([
      "Bravo", // 0.2
      "Charlie", // 0.5
      "Alpha", // no reading
    ]);
  });

  it("breaks ties by name so the order is stable across refetches", () => {
    const summaries = {
      "1": summary("1", { alerts: 2 }),
      "2": summary("2", { alerts: 2 }),
      "3": summary("3", { alerts: 2 }),
    };
    expect(names(sortUnits(units, summaries, "alerts", "ndvi"))).toEqual([
      "Alpha",
      "Bravo",
      "Charlie",
    ]);
  });

  it("does not mutate its input", () => {
    const copy = [...units];
    sortUnits(units, {}, "name", "ndvi");
    expect(units).toEqual(copy);
  });
});

describe("unitValue", () => {
  it("reads the three block-level indices", () => {
    const s = {
      ...summary("1", { ndvi: 0.4 }),
      ndre_current: 0.3,
      ndwi_current: -0.2,
    };
    expect(unitValue(s, "ndvi")).toBe(0.4);
    expect(unitValue(s, "ndre")).toBe(0.3);
    expect(unitValue(s, "ndwi")).toBe(-0.2);
  });

  it("returns null for grid-only indices rather than inventing an average", () => {
    const s = summary("1", { ndvi: 0.4 });
    expect(unitValue(s, "evi")).toBeNull();
    expect(unitValue(s, "savi")).toBeNull();
    expect(unitValue(s, "gndvi")).toBeNull();
    expect(unitValue(s, "ndmi")).toBeNull();
  });

  it("returns null when the block has no summary at all", () => {
    expect(unitValue(undefined, "ndvi")).toBeNull();
  });
});
