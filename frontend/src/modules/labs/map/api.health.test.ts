// The block dock shows the server's health class, not one of its own.
//
// Before this, `loadUnitDetail` re-derived health in the browser from the
// block's own 30-day NDVI window while the map polygon painted the `health`
// field the server sent. One page, one block, two answers. These tests fail
// if a second classifier is ever reintroduced here: they hand the loader an
// NDVI that the old rule would have called "critical" (0.10) and expect the
// server's word to win.
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Block } from "@/api/blocks";

vi.mock("@/i18n", () => ({ default: { language: "en" } }));

const getTimeseries = vi.hoisted(() => vi.fn());

vi.mock("@/api/alerts", () => ({ listAlerts: vi.fn(() => Promise.resolve([])) }));
vi.mock("@/api/recommendations", () => ({ listRecommendations: vi.fn(() => Promise.resolve([])) }));
vi.mock("@/api/crops", () => ({
  listCrops: vi.fn(() => Promise.resolve([])),
  listCropVarieties: vi.fn(() => Promise.resolve([])),
  listVarietyStrains: vi.fn(() => Promise.resolve([])),
}));
vi.mock("@/api/blocks", () => ({
  getBlock: vi.fn(() => Promise.resolve({ id: "b1", updated_at: "2026-06-30T00:00:00Z" })),
  listBlocks: vi.fn(() => Promise.resolve([])),
}));
vi.mock("@/api/blocksSummary", () => ({ getBlocksSummary: vi.fn() }));
vi.mock("@/api/cropAssignments", () => ({ listBlockCrops: vi.fn(() => Promise.resolve([])) }));
vi.mock("@/api/farms", () => ({ getFarm: vi.fn() }));
vi.mock("@/api/indices", () => ({ getTimeseries }));
vi.mock("@/api/integrationsHealth", () => ({ listBlockHealth: vi.fn(() => Promise.resolve([])) }));
vi.mock("@/api/irrigation", () => ({ listIrrigationSchedules: vi.fn(() => Promise.resolve([])) }));
vi.mock("@/api/plans", () => ({
  listCalendar: vi.fn(() => Promise.resolve({ activities: [] })),
  listPlans: vi.fn(() => Promise.resolve([])),
}));
vi.mock("@/api/signals", () => ({ listSignalObservations: vi.fn(() => Promise.resolve([])) }));
vi.mock("@/api/weather", () => ({ getForecast: vi.fn(() => Promise.resolve({ days: [] })) }));

const BLOCK = { id: "b1", area_m2: 40_000, parent_unit_id: null } as unknown as Block;

async function load(summaryHealth?: "healthy" | "watch" | "critical" | "unknown" | null) {
  const { loadUnitDetail } = await import("./api");
  return loadUnitDetail({
    farmId: "f1",
    blockId: "b1",
    blocksById: new Map([["b1", BLOCK]]),
    summaryHealth,
  });
}

describe("loadUnitDetail — health comes from the server", () => {
  beforeEach(() => {
    // A fresh module registry per test, so the detail memo starts empty.
    vi.resetModules();
    // 0.10 is far below the 0.40 break point the deleted browser-side rule
    // used. Nothing here may read it.
    getTimeseries.mockResolvedValue({
      points: [{ time: "2026-06-30T00:00:00Z", mean: "0.10" }],
    });
  });

  it("keeps the server's healthy verdict even when NDVI is very low", async () => {
    const detail = await load("healthy");
    expect(detail.health).toBe("healthy");
    expect(detail.indices.ndvi.current).toBeCloseTo(0.1);
  });

  it("keeps the server's critical verdict when there are no alerts at all", async () => {
    const detail = await load("critical");
    expect(detail.health).toBe("critical");
    expect(detail.alerts).toEqual([]);
  });

  it("falls back to unknown when the caller has no summary to pass", async () => {
    const detail = await load(null);
    expect(detail.health).toBe("unknown");
  });

  it("re-stamps health on a memo hit instead of replaying the cached class", async () => {
    const { loadUnitDetail } = await import("./api");
    const args = { farmId: "f1", blockId: "b1", blocksById: new Map([["b1", BLOCK]]) };
    const first = await loadUnitDetail({ ...args, summaryHealth: "healthy" });
    expect(first.health).toBe("healthy");
    // Same block, same language, inside the 30s TTL: the second call is a
    // memo hit. It must still carry the class the summary now reports.
    const second = await loadUnitDetail({ ...args, summaryHealth: "critical" });
    expect(second.health).toBe("critical");
  });
});
