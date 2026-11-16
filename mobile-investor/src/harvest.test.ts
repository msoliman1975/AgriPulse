/** Investor app v2, PR 9: the Harvest tab, in Arabic (RTL) and English. */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@capacitor/preferences", () => ({ Preferences: {} }));
vi.mock("@/auth/session", () => ({ validAccessToken: async () => "token" }));

import type { Harvest, HarvestPick, Holding } from "@/api/client";
import { formatMoney as rawMoney, type Lang } from "@/i18n";

// Intl puts a no-break space between the code and the amount.
const nb = (s: string): string => s.replace(/\u00a0/g, " ");
const formatMoney = (lang: Lang, n: number, c: string | null): string => nb(rawMoney(lang, n, c));
import { barHeights, inPickOrder } from "@/logic/harvest";
import { emptyNote, HarvestView, pickLabel } from "@/screens/HarvestTab";

const pick = (over: Partial<HarvestPick> = {}): HarvestPick => ({
  pick_no: 1,
  label: null,
  label_ar: null,
  harvested_on: "2026-08-03",
  weight_kg: "1200.00",
  price_per_kg: "12.50",
  revenue: "15000.00",
  ...over,
});

const harvest = (over: Partial<Harvest> = {}): Harvest => ({
  holding_id: "h1",
  season: "2026",
  seasons: ["2026", "2025"],
  currency: "EGP",
  picks: [
    pick({ pick_no: 2, harvested_on: "2026-08-20", weight_kg: "600.00", price_per_kg: null, revenue: null }),
    pick(),
  ],
  total_weight_kg: "1800.00",
  total_revenue: "15000.00",
  average_price_per_kg: "12.50",
  ...over,
});

const holding = (over: Partial<Holding> = {}): Holding =>
  ({
    holding_id: "h1",
    code: "H-1",
    period: "current",
    expected_harvest_on: "2026-08-01",
    ...over,
  }) as Holding;

describe("harvest helpers", () => {
  it("scales bars to the heaviest pick, with a floor", () => {
    expect(barHeights([pick({ weight_kg: "50" }), pick({ weight_kg: "100" }), pick({ weight_kg: "1" })])).toEqual([
      50, 100, 6,
    ]);
    expect(barHeights([pick({ weight_kg: "0" })])).toEqual([6]);
    expect(barHeights([])).toEqual([]);
  });

  it("orders picks as they happened", () => {
    const h = harvest();
    expect(inPickOrder(h.picks).map((p) => p.pick_no)).toEqual([1, 2]);
    expect(h.picks[0].pick_no).toBe(2);
  });

  it("labels a pick by its own label, else its number", () => {
    expect(pickLabel("en", pick({ label: "Early", label_ar: "مبكرة" }))).toBe("Early");
    expect(pickLabel("ar", pick({ label: "Early", label_ar: "مبكرة" }))).toBe("مبكرة");
    expect(pickLabel("ar", pick({ pick_no: 3 }))).toBe("القطفة 3");
    expect(pickLabel("en", pick({ pick_no: 3 }))).toBe("Pick 3");
  });

  it("formats money in the response currency with Western digits", () => {
    expect(formatMoney("en", 15438.17, "EGP")).toBe("EGP 15,438");
    expect(formatMoney("en", 99, "USD")).toBe("USD 99");
    expect(formatMoney("ar", 15438.17, "EGP")).toContain("15,438");
    expect(formatMoney("ar", 15438.17, "EGP")).toContain("ج.م");
    expect(formatMoney("en", 5, "ZZ")).toBe("5 ZZ");
    expect(formatMoney("en", 1234.4, null)).toBe("1,234");
  });

  it("picks the empty note by period", () => {
    expect(emptyNote("en", holding({ period: "future" }))).toBe("Your ownership has not started yet.");
    expect(emptyNote("ar", holding())).toBe("لا يوجد حصاد مسجّل هذا الموسم بعد. متوقع حوالي ⁦2026-08-01⁩.");
    expect(emptyNote("en", holding({ expected_harvest_on: null }))).toBe("No harvest recorded yet this season.");
    expect(emptyNote("en", holding({ period: "past" }))).toBe("No harvest recorded yet this season.");
  });
});

describe("Harvest tab rendering", () => {
  it("renders totals, chart, picks and season chips in Arabic", () => {
    const html = renderToStaticMarkup(createElement(HarvestView, { lang: "ar", h: holding(), data: harvest() }));
    expect(html).toContain("الوزن الإجمالي (كجم)");
    expect(html).toContain(">1,800<");
    expect(html).toContain("ج.م");
    expect(html).toContain("12.5");
    expect(html).toContain("القطفة 1");
    expect(html).toContain("1,200 كجم");
    expect(html).toContain("12.5 للكيلو");
    expect(html).toContain("⁦2026-08-03⁩");
    expect(html).toContain('aria-checked="true" class="chip chip-on">2026<');
    expect(html).toContain(">2025<");
    expect(html).toContain("height:100%");
    expect(html).toContain("height:50%");
    expect(html).not.toMatch(/[٠-٩]/);
    // The first pick (Aug 3) is listed before the second (Aug 20).
    expect(html.indexOf("القطفة 1")).toBeLessThan(html.indexOf("القطفة 2"));
  });

  it("shows the currency from the response, never a fixed one", () => {
    const html = nb(
      renderToStaticMarkup(
        createElement(HarvestView, { lang: "en", h: holding(), data: harvest({ currency: "USD" }) }),
      ),
    );
    expect(html).toContain("USD 15,000");
    expect(html).not.toContain("EGP");
  });

  it("leaves out revenue where a pick has no price", () => {
    const html = renderToStaticMarkup(
      createElement(HarvestView, {
        lang: "en",
        h: holding(),
        data: harvest({ total_revenue: null, average_price_per_kg: null, picks: [pick({ price_per_kg: null, revenue: null })] }),
      }),
    );
    expect(html).not.toContain("pick-revenue");
    expect(html).not.toContain("per kg</span>");
    expect(html).not.toContain("Gross revenue: your share");
  });

  it("hides the picker with one season and notes a past holding", () => {
    const html = renderToStaticMarkup(
      createElement(HarvestView, { lang: "en", h: holding({ period: "past" }), data: harvest({ seasons: ["2025"] }) }),
    );
    expect(html).not.toContain("radiogroup");
    expect(html).toContain("Your ownership has ended. Showing the seasons on record.");
  });

  it("shows the expected-harvest note with no picks", () => {
    const html = renderToStaticMarkup(
      createElement(HarvestView, { lang: "en", h: holding(), data: harvest({ picks: [], seasons: [] }) }),
    );
    expect(html).toContain("Expected around ⁦2026-08-01⁩.");
    expect(html).not.toContain("chart");
  });
});
