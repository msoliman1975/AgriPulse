/**
 * Investor app v2, PR 7: list stats (D6), stage colours and ribbon, the
 * Details facts, and the screens rendered in Arabic (RTL) and English.
 */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@capacitor/preferences", () => {
  const store = new Map<string, string>();
  return {
    Preferences: {
      get: async ({ key }: { key: string }) => ({ value: store.get(key) ?? null }),
      set: async ({ key, value }: { key: string; value: string }) => void store.set(key, value),
      remove: async ({ key }: { key: string }) => void store.delete(key),
      keys: async () => ({ keys: [...store.keys()] }),
    },
  };
});
vi.mock("@/auth/session", () => ({ validAccessToken: async () => "token" }));

import { ApiError, cachedCall, type Activity, type Holding, type Stage } from "@/api/client";
import { dirOf } from "@/i18n";
import {
  completedActivities,
  initials,
  NO_STAGE_COLOR,
  portfolioStats,
  STAGE_COLORS,
  stageColor,
  stageRibbon,
} from "@/logic/portfolio";
import { factRows, StageCard } from "@/screens/DetailsTab";
import { HoldingCard, PortfolioStats } from "@/screens/HoldingsScreen";

const STAGES: Stage[] = [
  { code: "flowering", name_en: "Flowering", name_ar: "التزهير", expected_start: "2026-01-01", expected_end: "2026-01-10" },
  { code: "fruit_set", name_en: "Fruit set", name_ar: "العقد", expected_start: "2026-01-11", expected_end: "2026-01-30" },
  { code: "harvest", name_en: "Harvest", name_ar: "الحصاد", expected_start: "2026-01-31", expected_end: "2026-02-09" },
];

function holding(over: Partial<Holding> = {}): Holding {
  return {
    holding_id: "h1",
    code: "H-001",
    name: "North plot",
    name_ar: "القطعة الشمالية",
    farm_name: "Wadi farm",
    farm_name_ar: "مزرعة الوادي",
    block_code: "B1",
    block_name: "Block 1",
    block_name_ar: "بلوك 1",
    area_m2: "8401.66",
    tree_count: 120,
    crop_name_en: "Mango",
    crop_name_ar: "مانجو",
    variety_name_en: "Keitt",
    variety_name_ar: "كيت",
    planting_date: "2018-03-01",
    crop_image_url: "https://api.example/crop.webp",
    crop_icon_url: "https://api.example/crop-64.webp",
    stage_code: "fruit_set",
    stage_name_en: "Fruit set",
    stage_name_ar: "العقد",
    stage_started_on: "2026-01-11",
    stage_expected_end: "2026-01-30",
    stages: STAGES,
    expected_harvest_on: "2026-01-31",
    current_season: "2026",
    start_date: "2025-06-01",
    end_date: null,
    period: "current",
    acquired_by: "purchase",
    contract_ref: "C-77",
    boundary: { type: "Polygon", coordinates: [] },
    block_boundary: { type: "Polygon", coordinates: [] },
    ...over,
  };
}

const activity = (id: string, status: Activity["status"]): Activity => ({
  id,
  activity_type: "spray",
  title: null,
  title_ar: null,
  scheduled_date: "2026-01-05",
  status,
  completed_at: null,
  photos: [],
});

describe("portfolio stats", () => {
  it("counts current holdings and their area only", () => {
    const s = portfolioStats([
      holding(),
      holding({ holding_id: "h2", area_m2: "4200.83" }),
      holding({ holding_id: "h3", period: "past", area_m2: "99999" }),
      holding({ holding_id: "h4", period: "future", area_m2: "99999" }),
    ]);
    expect(s.currentCount).toBe(2);
    expect(s.currentAreaM2).toBeCloseTo(12602.49, 2);
  });

  it("D6: counts each completed activity once across holdings on one block", () => {
    const shared = [activity("a1", "completed"), activity("a2", "upcoming")];
    expect(
      completedActivities([shared, shared, [activity("a3", "completed"), activity("a4", "in_progress")]]),
    ).toBe(2);
    expect(completedActivities([])).toBe(0);
  });
});

describe("stages", () => {
  it("colours a stage by its place in the season", () => {
    expect(stageColor(STAGES, "flowering")).toBe(STAGE_COLORS[0]);
    expect(stageColor(STAGES, "harvest")).toBe(STAGE_COLORS[2]);
    expect(stageColor(STAGES, "unknown")).toBe(NO_STAGE_COLOR);
    expect(stageColor(undefined, "flowering")).toBe(NO_STAGE_COLOR);
  });

  it("sizes dated stages by their days and places today by date", () => {
    const r = stageRibbon(STAGES, "fruit_set", "2026-01-20");
    expect(r.segments.map((s) => Math.round(s.widthPct))).toEqual([25, 50, 25]);
    // Day 20 of 40, at noon: 19.5 / 40.
    expect(r.markerPct).toBeCloseTo(48.75, 2);
  });

  it("gives undated stages equal widths and marks the middle of the current one", () => {
    const undated = STAGES.map((s) => ({ ...s, expected_start: null, expected_end: null }));
    const r = stageRibbon(undated, "harvest", "2026-01-20");
    expect(r.segments.every((s) => Math.abs(s.widthPct - 100 / 3) < 1e-9)).toBe(true);
    expect(r.markerPct).toBeCloseTo(100 - 100 / 6, 6);
  });

  it("falls back to the current stage when today is outside the dated season", () => {
    const r = stageRibbon(STAGES, "flowering", "2027-05-01");
    expect(r.markerPct).toBeCloseTo(12.5, 6);
    expect(stageRibbon(STAGES, null, "2027-05-01").markerPct).toBeNull();
    expect(stageRibbon([], "x", "2026-01-01")).toEqual({ segments: [], markerPct: null });
  });

  it("takes up to two initials", () => {
    expect(initials("nour hassan ali")).toBe("NH");
    expect(initials("نور حسن")).toBe("نح");
    expect(initials("  ")).toBe("");
  });
});

describe("Details facts", () => {
  it("adds how the holding was acquired and the contract reference (D3)", () => {
    const rows = Object.fromEntries(factRows("en", holding()));
    expect(rows["Acquired by"]).toBe("Purchase");
    expect(rows["Contract reference"]).toBe("C-77");
    const ar = Object.fromEntries(factRows("ar", holding({ acquired_by: "inheritance" })));
    expect(ar["طريقة الاقتناء"]).toBe("ميراث");
  });

  it("leaves both rows out for an older api", () => {
    const rows = Object.fromEntries(
      factRows("en", holding({ acquired_by: undefined, contract_ref: undefined })),
    );
    expect(rows).not.toHaveProperty("Acquired by");
    expect(rows).not.toHaveProperty("Contract reference");
  });
});

describe("screens in Arabic (RTL) and English", () => {
  it("Arabic is right to left", () => {
    expect(dirOf("ar")).toBe("rtl");
    expect(dirOf("en")).toBe("ltr");
  });

  it("renders the holding card in Arabic with the crop icon and stage pill", () => {
    const html = renderToStaticMarkup(
      createElement(HoldingCard, { lang: "ar", h: holding(), onOpen: () => undefined }),
    );
    expect(html).toContain("القطعة الشمالية");
    expect(html).toContain("مزرعة الوادي › بلوك 1 · مانجو كيت");
    expect(html).toContain("2 فدان");
    expect(html).toContain("120 شجرة");
    expect(html).toContain("العقد");
    expect(html).toContain('src="https://api.example/crop-64.webp"');
    // Western digits, never Arabic-Indic.
    expect(html).not.toMatch(/[٠-٩]/);
  });

  it("falls back to the crop's first letter without a picture", () => {
    const html = renderToStaticMarkup(
      createElement(HoldingCard, {
        lang: "en",
        h: holding({ crop_icon_url: null, crop_image_url: null }),
        onOpen: () => undefined,
      }),
    );
    expect(html).not.toContain("<img");
    expect(html).toContain(">M</span>");
  });

  it("shows no stage pill on a past holding", () => {
    const html = renderToStaticMarkup(
      createElement(HoldingCard, {
        lang: "en",
        h: holding({ period: "past", end_date: "2025-12-31" }),
        onOpen: () => undefined,
      }),
    );
    expect(html).not.toContain("pill-stage");
    expect(html).toContain("Until \u20662025-12-31\u2069");
  });

  it("renders the three stat tiles, with a dash while activities load", () => {
    const html = renderToStaticMarkup(
      createElement(PortfolioStats, { lang: "ar", holdings: [holding()], completed: null }),
    );
    expect(html).toContain("حيازات حالية");
    expect(html).toContain("أنشطة منفذة هذا الموسم");
    expect(html).toContain(">–<");
    const en = renderToStaticMarkup(
      createElement(PortfolioStats, { lang: "en", holdings: [holding()], completed: 7 }),
    );
    expect(en).toContain(">7<");
    expect(en).toContain(">2<");
  });

  it("draws the ribbon marker with a logical inset, so RTL mirrors it", () => {
    const html = renderToStaticMarkup(
      createElement(StageCard, { lang: "ar", h: holding(), today: "2026-01-20" }),
    );
    expect(html).toContain("inset-inline-start:48.8%");
    expect(html).not.toMatch(/(^|[;"])left:/);
    expect(html).toContain("مرحلة النمو");
    expect(html).toContain("الحصاد المتوقع");
    expect(html).toContain("2026-01-31");
    expect(html).toContain("ribbon-seg ribbon-on");
  });

  it("says ownership has not started on a future holding", () => {
    const html = renderToStaticMarkup(
      createElement(StageCard, { lang: "en", h: holding({ period: "future" }) }),
    );
    expect(html).toContain("Your ownership has not started yet.");
    expect(html).not.toContain("ribbon");
  });
});

describe("cachedCall", () => {
  it("stores a fresh answer and returns it when the network fails", async () => {
    const fresh = await cachedCall("t1", async () => ({ n: 1 }));
    expect(fresh.offline).toBe(false);
    const offline = await cachedCall("t1", async () => {
      throw new TypeError("Failed to fetch");
    });
    expect(offline.offline).toBe(true);
    expect(offline.data).toEqual({ n: 1 });
  });

  it("throws an HTTP error instead of serving the stored copy", async () => {
    await cachedCall("t2", async () => 1);
    await expect(
      cachedCall("t2", async () => {
        throw new ApiError(404, "not found");
      }),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("throws a network failure when nothing is stored", async () => {
    await expect(
      cachedCall("t3", async () => {
        throw new TypeError("Failed to fetch");
      }),
    ).rejects.toBeInstanceOf(TypeError);
  });
});

describe("dates inside Arabic text", () => {
  it("isolates the date so the bidi algorithm keeps it left to right", async () => {
    const { ltr } = await import("@/i18n");
    expect(ltr("2025-05-31")).toBe("⁦2025-05-31⁩");
    expect(ltr("")).toBe("");
    const html = renderToStaticMarkup(
      createElement(HoldingCard, {
        lang: "ar",
        h: holding({ period: "future", start_date: "2026-12-01" }),
        onOpen: () => undefined,
      }),
    );
    expect(html).toContain("من ⁦2026-12-01⁩");
  });
});
