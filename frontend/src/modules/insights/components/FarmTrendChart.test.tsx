import { describe, expect, it } from "vitest";

import type { FarmIndexTimeseriesPoint } from "@/api/insights";

import { _reshapeForRecharts } from "./FarmTrendChart";

function _p(
  time: string,
  block_id: string,
  block_name: string,
  value: string,
): FarmIndexTimeseriesPoint {
  return { time, block_id, block_name, value };
}

describe("_reshapeForRecharts", () => {
  it("returns empty arrays for empty input", () => {
    const out = _reshapeForRecharts([]);
    expect(out.chartData).toEqual([]);
    expect(out.blockNames).toEqual([]);
  });

  it("groups points by time and indexes by block name", () => {
    const out = _reshapeForRecharts([
      _p("2026-05-01T00:00:00Z", "b1", "North", "0.50"),
      _p("2026-05-01T00:00:00Z", "b2", "South", "0.30"),
      _p("2026-05-02T00:00:00Z", "b1", "North", "0.55"),
    ]);
    expect(out.blockNames).toEqual(["North", "South"]);
    expect(out.chartData).toEqual([
      { time: "2026-05-01T00:00:00Z", North: 0.5, South: 0.3 },
      { time: "2026-05-02T00:00:00Z", North: 0.55 },
    ]);
  });

  it("coerces Decimal strings to numbers (recharts needs numeric)", () => {
    const out = _reshapeForRecharts([_p("2026-05-01T00:00:00Z", "b1", "North", "0.1234")]);
    expect(typeof out.chartData[0].North).toBe("number");
    expect(out.chartData[0].North).toBe(0.1234);
  });

  it("sorts chartData by time ascending", () => {
    // Input out of order on purpose — function must sort.
    const out = _reshapeForRecharts([
      _p("2026-05-03T00:00:00Z", "b1", "North", "0.6"),
      _p("2026-05-01T00:00:00Z", "b1", "North", "0.5"),
      _p("2026-05-02T00:00:00Z", "b1", "North", "0.55"),
    ]);
    expect(out.chartData.map((r) => r.time)).toEqual([
      "2026-05-01T00:00:00Z",
      "2026-05-02T00:00:00Z",
      "2026-05-03T00:00:00Z",
    ]);
  });
});
