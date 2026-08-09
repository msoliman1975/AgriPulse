// Language coverage for the block-detail composition layer.
//
// `loadUnitDetail` resolves bilingual backend fields (alert diagnosis,
// recommendation text, crop catalogue names) to ONE language while it builds
// the detail, then memoises the result. Both halves of that had to agree with
// the active language and neither did: recommendations were pinned to
// `text_en`, and the memo was keyed on the block alone, so switching to
// Arabic replayed the English payload for the rest of the TTL.
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Block } from "@/api/blocks";

const lang = vi.hoisted(() => ({ value: "en" }));
vi.mock("@/i18n", () => ({
  default: {
    get language() {
      return lang.value;
    },
  },
}));

const listAlerts = vi.hoisted(() => vi.fn());
const listRecommendations = vi.hoisted(() => vi.fn());
const listCrops = vi.hoisted(() => vi.fn());

vi.mock("@/api/alerts", () => ({ listAlerts }));
vi.mock("@/api/recommendations", () => ({ listRecommendations }));
vi.mock("@/api/crops", () => ({
  listCrops,
  listCropVarieties: vi.fn(() => Promise.resolve([])),
  listVarietyStrains: vi.fn(() => Promise.resolve([])),
}));
vi.mock("@/api/blocks", () => ({
  getBlock: vi.fn(() => Promise.resolve({ id: "b1", updated_at: "2026-06-30T00:00:00Z" })),
  listBlocks: vi.fn(() => Promise.resolve([])),
}));
vi.mock("@/api/blocksSummary", () => ({ getBlocksSummary: vi.fn() }));
vi.mock("@/api/cropAssignments", () => ({
  listBlockCrops: vi.fn(() =>
    Promise.resolve([
      {
        id: "bc1",
        crop_id: "c1",
        crop_variety_id: null,
        crop_variety_strain_id: null,
        crop_path: "mango",
        season_label: "Summer 2026",
        planting_date: null,
        growth_stage: "fruit_set",
        status: "active",
        is_active_now: true,
      },
    ]),
  ),
}));
vi.mock("@/api/farms", () => ({ getFarm: vi.fn() }));
vi.mock("@/api/indices", () => ({ getTimeseries: vi.fn(() => Promise.resolve({ points: [] })) }));
vi.mock("@/api/integrationsHealth", () => ({ listBlockHealth: vi.fn(() => Promise.resolve([])) }));
vi.mock("@/api/irrigation", () => ({ listIrrigationSchedules: vi.fn(() => Promise.resolve([])) }));
vi.mock("@/api/plans", () => ({
  listCalendar: vi.fn(() => Promise.resolve({ activities: [] })),
  listPlans: vi.fn(() => Promise.resolve([])),
}));
vi.mock("@/api/signals", () => ({ listSignalObservations: vi.fn(() => Promise.resolve([])) }));
vi.mock("@/api/weather", () => ({ getForecast: vi.fn(() => Promise.resolve({ days: [] })) }));

const BLOCK = { id: "b1", area_m2: 40_000, parent_unit_id: null } as unknown as Block;

async function load(): Promise<import("./types").UnitDetail> {
  const { loadUnitDetail } = await import("./api");
  return loadUnitDetail({
    farmId: "f1",
    blockId: "b1",
    blocksById: new Map([["b1", BLOCK]]),
  });
}

describe("loadUnitDetail — language", () => {
  beforeEach(() => {
    // A fresh module registry per test, so the detail memo starts empty.
    vi.resetModules();
    lang.value = "en";
    listAlerts.mockResolvedValue([
      {
        id: "a1",
        severity: "critical",
        rule_code: "ndvi_drop",
        diagnosis_en: "Canopy vigour dropped",
        diagnosis_ar: "انخفضت حيوية المجموع الخضري",
        prescription_en: "Scout the block",
        prescription_ar: "افحص الحقل",
        created_at: "2026-06-30T00:00:00Z",
      },
    ]);
    listRecommendations.mockResolvedValue([{ text_en: "Irrigate 30 mm", text_ar: "اروِ ٣٠ ملم" }]);
    listCrops.mockResolvedValue([{ id: "c1", name_en: "Mango", name_ar: "مانجو" }]);
  });

  it("renders alerts, recommendations and the crop name in the active language", async () => {
    const en = await load();
    expect(en.alerts[0].message).toBe("Canopy vigour dropped");
    expect(en.recommendations).toEqual(["Irrigate 30 mm"]);
    expect(en.crop_assignment?.crop_name).toBe("Mango");

    // Same block, language switched. The memo must not replay the English
    // payload — the react-query key carries the language, so a stale hit here
    // is invisible: the query refetches and gets the old object right back.
    lang.value = "ar";
    const ar = await load();
    expect(ar.alerts[0].message).toBe("انخفضت حيوية المجموع الخضري");
    expect(ar.recommendations).toEqual(["اروِ ٣٠ ملم"]);
    expect(ar.crop_assignment?.crop_name).toBe("مانجو");
  });

  it("falls back to English when a row has no Arabic variant", async () => {
    listAlerts.mockResolvedValue([
      {
        id: "a1",
        severity: "warning",
        rule_code: "ndvi_drop",
        diagnosis_en: "English-only rule",
        diagnosis_ar: null,
        prescription_en: null,
        prescription_ar: null,
        created_at: "2026-06-30T00:00:00Z",
      },
    ]);
    listRecommendations.mockResolvedValue([{ text_en: "English-only advice", text_ar: null }]);
    lang.value = "ar";
    const ar = await load();
    expect(ar.alerts[0].message).toBe("English-only rule");
    expect(ar.recommendations).toEqual(["English-only advice"]);
  });

  it("keeps the raw activity type alongside the English label", async () => {
    const { listCalendar } = await import("@/api/plans");
    vi.mocked(listCalendar).mockResolvedValue({
      activities: [{ block_id: "b1", scheduled_date: "2026-07-02", activity_type: "soil_prep" }],
    } as never);
    const en = await load();
    expect(en.activities[0].activity_type).toBe("soil_prep");
    expect(en.activities[0].label).toBe("Soil prep");
  });
});
